import re
"""Site web (FastAPI) : pages, offres à trier, décisions et annulation, fiche détaillée."""
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from stage_scraper import db, requetes
from stage_scraper.offre import nouvelle_offre
from stage_scraper.web import serveur


@pytest.fixture
def base(tmp_path, monkeypatch):
    chemin = tmp_path / "site.db"
    with closing(db.connecter(chemin)) as c:
        db.initialiser(c)
        db.enregistrer_offres(c, [
            nouvelle_offre(source="test", source_id="1", titre="Stage Data IA", entreprise="Doctolib", lieu="Paris, France",
                           description="Annonce complète", lien="https://exemple.fr/1"),
            nouvelle_offre(source="test", source_id="2", titre="Stage ML", entreprise="Owkin", lieu="Paris"),
            nouvelle_offre(source="test", source_id="3", titre="Stage Marketing", entreprise="Acme", lieu="Paris"),
        ], passage_id=1)
        c.execute("UPDATE offres SET score = 9, section = 'Santé', poste_ia_data = 1, duree = '5 mois', "
                  "date_debut = '2027-04-15', resume = 'Résumé', pourquoi = 'IA en santé' WHERE id = 1")
        c.execute("UPDATE offres SET score = 3 WHERE id = 3")
        c.commit()
    monkeypatch.setenv("STAGE_SCRAPER_BASE", str(chemin))
    return chemin


@pytest.fixture
def client(base):
    with TestClient(serveur.app) as c:
        yield c


def test_pages(client):
    for chemin in ("/", "/a-trier", "/profil", "/statique/js/profil.js", "/statique/css/site.css", "/statique/js/swipe.js", "/statique/img/fond-manhattan.jpg"):
        assert client.get(chemin).status_code == 200, chemin
    assert "Ton stage" in client.get("/").text
    # le navigateur revérifie toujours les fichiers du site : jamais de vieux CSS en cache
    assert client.get("/statique/css/site.css").headers["cache-control"] == "no-cache"


def test_offres_a_trier(client):
    d = client.get("/api/a-trier").json()
    cartes = {o["id"]: o for o in d["offres"]}
    assert set(cartes) == {1, 2, 3}
    doctolib = cartes[1]
    assert doctolib["lieu"] == "Paris" and doctolib["initiale"] == "D" and doctolib["score"] == 9
    assert [p["texte"] for p in doctolib["puces"]] == ["IA / data", "5 mois", "Avril 2027"]
    assert cartes[3]["bof"] and not doctolib["bof"]
    assert cartes[2]["resume"] == "Pas encore notée par l'IA."
    assert "description" not in doctolib            # l'annonce complète vient avec la fiche
    assert d["selection"] == 0


def test_decisions_et_annulation(client, base):
    oui = client.post("/api/decision", json={"offre_id": 1, "action": "candidate"}).json()
    non = client.post("/api/decision", json={"offre_id": 2, "action": "ecarte"}).json()
    assert client.post("/api/raison", json={"offre_id": 2, "raison": "Pas mon domaine"}).json() == {"ok": True}
    tard = client.post("/api/decision", json={"offre_id": 3, "action": "plus_tard"}).json()
    d = client.get("/api/a-trier").json()
    assert [(o["id"], o["plus_tard"]) for o in d["offres"]] == [(3, True)] and d["selection"] == 1
    with closing(db.connecter(base)) as c:
        assert requetes.offres_pas_interesse(c)[0]["raison"] == "Pas mon domaine"

    for decision in (oui, non, tard):
        assert client.post("/api/annuler", json=decision).json() == {"ok": True}
    d = client.get("/api/a-trier").json()
    assert sorted((o["id"], o["plus_tard"]) for o in d["offres"]) == [(1, False), (2, False), (3, False)]
    assert d["selection"] == 0


def test_erreurs(client):
    assert client.post("/api/decision", json={"offre_id": 1, "action": "nimporte"}).status_code == 400
    assert client.post("/api/decision", json={"offre_id": 999, "action": "candidate"}).status_code == 400
    assert client.get("/api/offres/999").status_code == 404


def test_fiche(client):
    o = client.get("/api/offres/1").json()
    assert o["description"] == "Annonce complète" and o["titre"] == "Stage Data IA"
    assert o["liens"] == [{"site": "test", "lien": "https://exemple.fr/1"}]


def test_phrase_scrap():
    from datetime import datetime
    s = {"date": "2026-11-19 08:02:00", "auto": True, "nouvelles": 12, "top": 1, "en_erreur": ["careerjet"]}
    p = serveur.phrase_scrap(s, maintenant=datetime(2026, 11, 19, 10, 0))
    assert p["titre"] == "Dernier scrap aujourd'hui à 8 h 02"
    assert p["texte"] == "12 nouvelles offres, dont 1 notée 8 ou plus. En erreur : careerjet."
    assert serveur.phrase_scrap(None) is None


def test_ma_selection(client):
    oui = client.post("/api/decision", json={"offre_id": 1, "action": "candidate"}).json()
    d = client.get("/api/selection").json()
    assert [e["cle"] for e in d["etapes"]] == ["preparation", "envoyee", "entretien", "terminee"]
    (f,) = d["fiches"]
    assert (f["id"], f["entreprise"], f["etape"], f["action"], f["bouton"]) == (
        oui["candidature_id"], "Doctolib", "preparation", "preparer", "Préparer")
    assert d["a_trier"] == 1   # Owkin ; Acme (3/10) est « Bof »
    cid = f["id"]

    # notes gardées, puis « C'est envoyé » et annulation
    assert client.post(f"/api/selection/{cid}/dates", json={"notes": "Contact : RH"}).status_code == 200
    jeton = client.post(f"/api/selection/{cid}/etape", json={"etape": "envoyee"}).json()["jeton"]
    fiche = client.get(f"/api/selection/{cid}").json()
    assert fiche["etape"] == "envoyee" and fiche["notes"] == "Contact : RH" and fiche["date_relance"]
    assert client.post("/api/selection/annuler", json={"jeton": jeton}).json() == {"ok": True}
    assert client.get(f"/api/selection/{cid}").json()["etape"] == "preparation"
    assert client.post("/api/selection/annuler", json={"jeton": jeton}).status_code == 410   # une seule fois

    # une date d'entretien range l'offre dans « Entretien »
    client.post(f"/api/selection/{cid}/dates", json={"date_entretien": "2026-11-26 14:00"})
    assert client.get(f"/api/selection/{cid}").json()["etape"] == "entretien"

    # terminée : refus ou acceptation
    assert client.post(f"/api/selection/{cid}/etape", json={"etape": "terminee", "resultat": "nimporte"}).status_code == 400
    client.post(f"/api/selection/{cid}/etape", json={"etape": "terminee", "resultat": "accepté"})
    assert client.get(f"/api/selection/{cid}").json()["statut"] == "accepté"

    # retirer, puis annuler
    jeton = client.post(f"/api/selection/{cid}/retirer").json()["jeton"]
    assert client.get(f"/api/selection/{cid}").status_code == 404
    client.post("/api/selection/annuler", json={"jeton": jeton})
    assert client.get(f"/api/selection/{cid}").status_code == 200


def test_offre_trouvee_ailleurs(client):
    assert client.post("/api/selection/nouvelle", json={}).status_code == 400
    cid = client.post("/api/selection/nouvelle", json={"entreprise": "Lifen", "poste": "Stage data",
                                                       "envoyee": "2026-11-10"}).json()["id"]
    f = client.get(f"/api/selection/{cid}").json()
    assert (f["trouvee_ailleurs"], f["etape"], f["date_candidature"]) == (True, "envoyee", "2026-11-10")
    client.post(f"/api/selection/{cid}/dates", json={"annonce": "Texte collé"})
    assert client.get(f"/api/selection/{cid}").json()["description"] == "Texte collé"
    assert client.get("/selection").status_code == 200


def test_journal_et_corbeille(client):
    j = client.get("/api/journal").json()
    assert j["credit"]["total"] > 0 and j["offres_en_base"] == 3 and j["a_trier"] == 2
    client.post("/api/decision", json={"offre_id": 2, "action": "ecarte"})
    c = client.get("/api/corbeille").json()
    toi = next(l for l in c["listes"] if l["cle"] == "toi")
    assert [o["id"] for o in toi["offres"]] == [2] and toi["offres"][0]["remettre"]
    assert client.post("/api/corbeille/remettre", json={"offre_id": 2, "liste": "tri"}).status_code == 400
    client.post("/api/corbeille/remettre", json={"offre_id": 2, "liste": "toi"})
    assert next(l for l in client.get("/api/corbeille").json()["listes"] if l["cle"] == "toi")["total"] == 0
    for page in ("/journal", "/corbeille", "/selection", "/a-trier"):
        html = client.get(page).text
        assert '<!-- menu -->' not in html and f'class="on" href="{page}"' in html


def test_reglages(client, tmp_path, monkeypatch):
    import shutil
    from stage_scraper.config import CHEMIN_CONFIG
    copie = tmp_path / "config.yaml"
    shutil.copyfile(CHEMIN_CONFIG, copie)
    monkeypatch.setenv("STAGE_SCRAPER_CONFIG", str(copie))   # jamais le vrai config.yaml
    avant_vrai = CHEMIN_CONFIG.read_text(encoding="utf-8")

    d = client.get("/api/reglages").json()
    assert "alternance" in d["criteres"]["contrats"] and d["criteres"]["entreprises_suivies"][0]["nom"] == "Doctolib"
    assert set(d["groupes"]) == {"priorite_absolue", "grand_groupe", "scale_up", "ecosysteme"}

    postes = d["criteres"]["postes"] + ["growth hacker", "  ", "Growth Hacker"]
    r = client.post("/api/reglages", json={"postes": postes, "anciennete_max_jours": 60}).json()
    assert set(r["changements"]) == {"exclusions postes", "anciennete_max_jours"}
    d = client.get("/api/reglages").json()
    assert d["criteres"]["postes"].count("growth hacker") == 1 and d["criteres"]["anciennete_max_jours"] == 60
    assert (tmp_path / "config.yaml.bak").exists()
    assert client.post("/api/reglages", json={"anciennete_max_jours": 60}).json() == {"changements": []}

    assert client.post("/api/reglages", json={"anciennete_max_jours": 0}).status_code == 400
    assert client.post("/api/reglages", json={"inconnu": 1}).status_code == 400
    assert client.post("/api/reglages", json={"entreprises_suivies": [{"nom": "X", "groupe": "pirate"}]}).status_code == 400
    assert CHEMIN_CONFIG.read_text(encoding="utf-8") == avant_vrai


def test_reglages_documents_et_tri(client, tmp_path, monkeypatch):
    from stage_scraper.web import serveur
    monkeypatch.setitem(serveur.DOCUMENTS, "modele", lambda config: tmp_path / "profil" / "modele.txt")
    assert client.post("/api/reglages/documents/cv", content=b"pas un pdf").status_code == 400
    assert client.post("/api/reglages/documents/modele?fichier=lettre.exe", content=b"x").status_code == 400
    assert client.post("/api/reglages/documents/modele?fichier=lettre.txt", content="Madame, Monsieur".encode()).json() == {"ok": True}
    assert (tmp_path / "profil" / "modele.txt").read_text(encoding="utf-8") == "Madame, Monsieur"
    assert client.get("/api/reglages/apercu/autre").status_code == 404
    assert "Tri des" in client.post("/api/reglages/retrier").json()["texte"]


# ---------------------------------------------------------------- dossier de candidature (faux client d'IA)

FAUX_CV_SITE = "[Prénom Nom]\nProjet de prédiction de la glycémie | Python, scikit-learn\nValidation croisée groupée par patient."


class FauxIA:
    """Remplace Claude et Gemini : renvoie les réponses données, dans l'ordre. Aucun appel réseau."""
    def __init__(self, *reponses):
        self.reponses, self.appels = list(reponses), []

    def appeler(self, modele, systeme, contents, schema=None, reflexion=None, outils=None):
        import json
        self.appels.append(modele)
        r = self.reponses.pop(0)
        if isinstance(r, Exception):
            raise r
        return {"role": "model", "parts": [{"text": json.dumps(r, ensure_ascii=False)}]}, {"input_tokens": 100, "output_tokens": 50}


@pytest.fixture
def ia(monkeypatch):
    from stage_scraper import claude, cv
    from stage_scraper.web import serveur
    monkeypatch.setattr(cv, "texte_cv", lambda config: FAUX_CV_SITE)
    monkeypatch.setattr(cv, "modele_lettre", lambda config: None)
    monkeypatch.setattr(cv, "nom_reel", lambda config: "Alex Martin")
    monkeypatch.setattr(claude, "secret", lambda nom: None)   # pas de clé Claude : Gemini (gratuit)
    faux = FauxIA()
    monkeypatch.setattr(serveur, "CLIENT_IA", faux)
    return faux


def test_dossier_preparer_retoucher_telecharger(client, ia):
    from stage_scraper import gemini
    cid = client.post("/api/decision", json={"offre_id": 1, "action": "candidate"}).json()["candidature_id"]
    d = client.get(f"/api/selection/{cid}/dossier").json()
    assert d["cv_present"] and d["diagnostic"] is None and d["lettre"] is None and d["prix"]["analyse"] == "gratuit, Gemini"

    ia.reponses += [
        {"adequation": "forte", "synthese": "Python et projet santé.", "pour": ["Python"], "contre": [], "alertes": [],
         "exigences": [], "conseils_cv": [], "a_apprendre": []},
        {"reponse": "Voici un premier jet.", "lettre": "Madame, Monsieur,\nJe suis [Prénom Nom].", "affirmations": []},
    ]
    d = client.post(f"/api/selection/{cid}/dossier/preparer", json={}).json()
    assert d["diagnostic"]["adequation"] == "forte"
    assert d["lettre"]["numero"] == 1 and d["lettre"]["auteur"] == "l'IA"
    assert [m["role"] for m in d["messages"]] == ["assistant", "user", "assistant"]
    assert d["messages"][-1]["detail"] == "Gemini (gratuit)" and d["messages"][-1]["version"] == 1
    assert len(ia.appels) == 2 and all(m.startswith("gemini") for m in ia.appels)

    # rien ne manque : « préparer » ne rappelle pas l'IA
    client.post(f"/api/selection/{cid}/dossier/preparer", json={})
    assert len(ia.appels) == 2

    # modification à la main, puis retouche par l'IA (la lettre tapée est gardée avant)
    assert client.post(f"/api/selection/{cid}/dossier/lettre", json={"texte": "Madame,\nJe suis [Prénom Nom]."}).json()["change"]
    ia.reponses.append({"reponse": "Plus court.", "lettre": "Madame,\n[Prénom Nom]", "affirmations": []})
    d = client.post(f"/api/selection/{cid}/dossier/message",
                    json={"texte": "Plus court", "lettre_actuelle": "Madame,\nJe suis [Prénom Nom] !"}).json()
    assert d["lettre"]["numero"] == 3 and d["lettre"]["texte"] == "Madame,\n[Prénom Nom]"
    assert [v["auteur"] for v in d["versions"]] == ["IA", "toi", "IA"]

    # revenir à la version 1 ; téléchargement signé (vrai nom remis, en local)
    assert client.post(f"/api/selection/{cid}/dossier/version", json={"numero": 1}).json()["lettre"]["numero"] == 1
    assert client.post(f"/api/selection/{cid}/dossier/version", json={"numero": 9}).status_code == 404
    txt = client.get(f"/api/selection/{cid}/dossier/lettre.txt")
    assert txt.text == "Madame, Monsieur,\nJe suis Alex Martin." and "Lettre_Doctolib.txt" in txt.headers["content-disposition"]
    assert client.get(f"/api/selection/{cid}/dossier/lettre.docx").content[:2] == b"PK"

    # l'IA ne répond pas : message d'erreur lisible, rien n'est perdu
    ia.reponses += [gemini.ErreurGemini("503")] * 3   # chaque modèle de secours échoue aussi
    r = client.post(f"/api/selection/{cid}/dossier/message", json={"texte": "Encore"})
    assert r.status_code == 400 and "L'IA n'a pas pu terminer" in r.json()["detail"]
    assert client.post(f"/api/selection/{cid}/dossier/message", json={"texte": "  "}).status_code == 400


def test_dossier_sans_cv(client, ia, monkeypatch):
    from stage_scraper import cv
    monkeypatch.setattr(cv, "texte_cv", lambda config: None)
    cid = client.post("/api/decision", json={"offre_id": 1, "action": "candidate"}).json()["candidature_id"]
    assert client.get(f"/api/selection/{cid}/dossier").json()["cv_present"] is False
    r = client.post(f"/api/selection/{cid}/dossier/preparer", json={})
    assert r.status_code == 400 and "CV" in r.json()["detail"] and ia.appels == []


# ---------------------------------------------------------------- assistant (faux client d'IA)

def test_assistant(client, ia):
    from stage_scraper import gemini
    assert client.get("/assistant").status_code == 200
    d = client.get("/api/assistant").json()
    assert d["messages"] == [] and d["nb_offres"] >= 1 and "a_trier" in d["menu"]

    ia.reponses.append({"reponse": "Voici **une** offre.", "offres": [{"id": 1, "raison": "IA chez Doctolib"},
                                                                      {"id": 999, "raison": "inventée"}]})
    d = client.post("/api/assistant", json={"question": "Un stage IA ?"}).json()
    assert [m["role"] for m in d["messages"]] == ["user", "assistant"]
    propose = d["messages"][1]["offres"]
    assert [o["id"] for o in propose] == [1] and propose[0]["raison"] == "IA chez Doctolib"   # id inventé ignoré
    assert propose[0]["etat"] == "a_trier" and propose[0]["candidature_id"] is None

    # l'état suit les décisions prises ailleurs
    cid = client.post("/api/decision", json={"offre_id": 1, "action": "candidate"}).json()["candidature_id"]
    o = client.get("/api/assistant").json()["messages"][1]["offres"][0]
    assert (o["etat"], o["candidature_id"]) == ("selection", cid)

    # l'historique part avec la question suivante ; une erreur ne garde pas la question
    ia.reponses += [gemini.ErreurGemini("503")]
    r = client.post("/api/assistant", json={"question": "Et chez Owkin ?"})
    assert r.status_code == 400 and "Pas de réponse" in r.json()["detail"]
    assert len(client.get("/api/assistant").json()["messages"]) == 2
    assert client.post("/api/assistant", json={"question": " "}).status_code == 400

    assert client.post("/api/assistant/effacer", json={}).json() == {"messages": []}
    assert client.get("/api/assistant").json()["messages"] == []


def test_css_et_js_versionnes(client):
    """Une vieille copie de site.css gardée par le navigateur ne doit jamais servir : l'adresse change avec le contenu."""
    page = client.get("/profil").text
    assert re.search(r'/statique/css/site\.css\?v=[0-9a-f]{10}"', page)
    assert re.search(r'/statique/js/profil\.js\?v=[0-9a-f]{10}"', page)
    assert '<script type="importmap">' in page and '"/statique/js/commun.js": "/statique/js/commun.js?v=' in page
    assert page.index("importmap") < page.index('type="module"')
    assert client.get(re.search(r'/statique/css/site\.css\?v=\w+', page).group(0)).status_code == 200
