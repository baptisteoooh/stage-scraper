"""Entretien d'accueil (/bienvenue) : questions, réponses en puces ou libres, récapitulatif, écriture du profil.

Toujours sur une copie de config.yaml ; l'IA est remplacée par un faux client (aucun appel réseau)."""
from contextlib import closing
from datetime import date

import pytest

from stage_scraper import db, entretien, profil, reglages
from stage_scraper.web import langue
from test_profil import copie  # noqa: F401  (copie de config.yaml aux critères de référence)
from test_site_web import base, client  # noqa: F401  (fixtures)

JOUR = date(2026, 11, 21)


@pytest.fixture
def neuve(copie):  # noqa: F811
    """Un profil jamais configuré : pas de phrase « Ce que tu cherches », entretien jamais fait."""
    donnees = reglages.lire(copie)
    donnees["profil"]["recherche"] = ""
    reglages.ecrire(donnees, copie)
    return copie


@pytest.fixture
def conn(tmp_path):
    with closing(db.connecter(tmp_path / "x.db")) as c:
        db.initialiser(c)
        yield c


@pytest.fixture
def sans_ia(monkeypatch):
    monkeypatch.setattr(entretien, "secret", lambda nom: None)   # jamais de vrai Gemini, même si .env a une clé


class FauxGemini:
    """Rend, dans l'ordre, des appels d'outils : {'outil': [changements]} ou {'pas_compris': raison}."""
    def __init__(self, *reponses):
        self.reponses, self.appels = list(reponses), []

    def appeler(self, modele, systeme, contents, schema=None, reflexion=None, outils=None, forcer_outil=False):
        self.appels.append({"systeme": systeme, "outils": [o["name"] for o in outils or []], "forcer": forcer_outil})
        r = self.reponses.pop(0)
        if "pas_compris" in r:
            appel = {"name": "pas_compris", "args": {"raison": r["pas_compris"]}}
        else:
            appel = {"name": "modifier_profil", "args": {"changements": r["outil"]}}
        return {"role": "model", "parts": [{"functionCall": appel}]}, {}


def _repondre(conn, chemin, q, valeurs, **kw):
    return entretien.repondre(conn, chemin, {}, q, valeurs=valeurs, aujourd_hui=JOUR, **kw)


# --------------------------------------------------------------------------- état et questions

def test_a_faire(copie, neuve):  # noqa: F811
    assert entretien.a_faire(reglages.lire(neuve))
    donnees = reglages.lire(neuve)
    donnees["profil"]["recherche"] = "Un stage en robotique"
    assert not entretien.a_faire(donnees)


def test_questions_d_un_profil_neuf(neuve):
    donnees = reglages.lire(neuve)
    assert [q["id"] for q in entretien.liste_questions()] == list(entretien.QUESTIONS)
    quoi = entretien.question("quoi", donnees, {}, JOUR)
    assert quoi["numero"] == 1 and quoi["total"] == 6
    assert quoi["rangees"][0]["choisis"] == []                       # les valeurs du modèle ne sont pas présélectionnées
    assert "Conseil santé" not in [c["id"] for c in quoi["rangees"][0]["choix"]]
    quand = entretien.question("quand", reglages.lire(neuve), {}, JOUR)
    debut, duree = quand["rangees"]
    assert debut["choix"][0] == {"id": "2026-12", "libelle": "Décembre 2026"} and len(debut["choix"]) == 10
    assert [c["libelle"] for c in duree["choix"]][:2] == ["2 à 3 mois", "3 à 4 mois"] and debut["libelle"] == "Début"
    # une réponse déjà donnée est présélectionnée quand on revient sur la question
    quoi = entretien.question("quoi", reglages.lire(neuve), {"domaines": ["Robotique", "Data science"]}, JOUR)
    assert quoi["rangees"][0]["choisis"] == ["Robotique", "Data science"]


def test_questions_d_un_profil_existant_preremplies(copie):  # noqa: F811
    q = lambda qid: entretien.question(qid, reglages.lire(copie), {}, JOUR)  # noqa: E731
    p = profil.lire(reglages.lire(copie))
    assert q("quoi")["rangees"][0]["choisis"] == p["domaines"]      # « Conseil santé » compris (puce ajoutée)
    assert [r["choisis"] for r in q("quand")["rangees"]] == [["2027-04"], ["3-5"]]
    assert [r["choisis"] for r in q("ou")["rangees"]] == [["idf"], ["tout"]]
    assert q("contrats")["rangees"][0]["choisis"] == ["stage_cdd"]
    assert q("secteurs")["rangees"][0]["choisis"] == ["sante"]
    entreprises = q("entreprises")["rangees"][0]
    suivies = {e["nom"] for e in p["entreprises"]}
    assert entreprises["choisis"] == [] and entreprises["choix"] and not suivies & {c["id"] for c in entreprises["choix"]}


# --------------------------------------------------------------------------- parcours complet

def test_parcours_en_puces_puis_c_est_bon(neuve, conn):
    texte_avant = neuve.read_text(encoding="utf-8")
    v = {}
    for q, choix, retenu in [
        ("quoi", {"domaines": ["Data science", "IA / machine learning"]}, "Data science et IA / machine learning"),
        ("quand", {"debut": ["2027-04"], "duree": ["3-5"]}, "Avril 2027 · 3 à 5 mois"),
        ("ou", {"zone": ["petite"], "teletravail": ["hybride"]}, "À Paris et en petite couronne, en hybride"),
        ("contrats", {"contrats": ["stage"]}, "Stage seulement"),
        ("secteurs", {"secteurs": ["sante", "biotech"]}, "Santé / medtech et biotech"),
        ("entreprises", {"entreprises": ["Doctolib", "Alan"]}, "Doctolib et Alan"),
    ]:
        r = _repondre(conn, neuve, q, v, choix=choix)
        assert r["compris"] and r["retenu"] == retenu, q
        v = r["valeurs"]
    assert neuve.read_text(encoding="utf-8") == texte_avant                 # rien n'est écrit avant « C'est bon »
    assert v["fin_au_plus_tard"] == "2027-08-31" and v["debut_au_plus_tard"] == "2027-05-10"

    a = entretien.apercu(neuve, v)
    assert a["erreur"] is None
    assert "".join(s["texte"] for s in a["segments"]) == (
        "Tu cherches un stage en Data science et IA / machine learning, à partir d'avril 2027 pour 3 à 5 mois, "
        "à Paris et en petite couronne, en hybride, dans ces secteurs : santé / medtech et biotech, "
        "en suivant de près Doctolib et Alan.")
    assert {s["question"] for s in a["segments"]} == set(entretien.QUESTIONS) | {None}
    en = "".join(s["texte"] for s in entretien.apercu(neuve, v, "en")["segments"])
    assert en.startswith("You're looking for an internship in Data science") and "starting April 2027 for 3–5 months" in en

    r = entretien.terminer(neuve, v, JOUR)
    p = profil.lire(reglages.lire(neuve))
    assert p == r["profil"]
    assert p["domaines"] == ["Data science", "IA / machine learning"] and p["contrats"] == ["stage"]
    assert p["departements"] == ["75", "92", "93", "94"] and (p["hybride"], p["full_remote"]) == (True, False)
    assert [e["nom"] for e in p["entreprises"]] == ["Doctolib", "Alan"]     # premier entretien : la liste du modèle est remplacée
    assert next(e for e in p["entreprises"] if e["nom"] == "Doctolib")["outil"] == "ashby"   # détail d'une entreprise connue gardé
    assert "biotech" in p["secteurs_cible"] and "biotech" not in p["secteurs_ok"]
    assert p["recherche"] == "Un stage en Data science et IA / machine learning (secteurs : santé / medtech et biotech)"
    assert "stage data science" in p["requetes"] and "stage biotech" in p["requetes"] and "stage bioinformatique" not in p["requetes"]
    texte = neuve.read_text(encoding="utf-8")
    assert "entretien_accueil: 2026-11-21" in texte and "# Secteurs" in texte and "# Scoring IA" in texte
    assert not entretien.a_faire(reglages.lire(neuve))


def test_entretien_refait_ajoute_sans_retirer(copie, conn):  # noqa: F811
    avant = profil.lire(reglages.lire(copie))
    v = _repondre(conn, copie, "quoi", {}, choix={"domaines": avant["domaines"] + ["Robotique"]})["valeurs"]
    r = _repondre(conn, copie, "entreprises", v, choix={"entreprises": ["Alan"]})
    assert r["retenu"] == "Alan"
    entretien.terminer(copie, r["valeurs"], JOUR)
    p = profil.lire(reglages.lire(copie))
    assert [e["nom"] for e in p["entreprises"]] == [e["nom"] for e in avant["entreprises"]] + ["Alan"]
    assert p["requetes"][:len(avant["requetes"])] == avant["requetes"] and "stage robotique" in p["requetes"]
    assert p["recherche"] == avant["recherche"]                             # sa phrase à lui n'est pas remplacée


def test_reponses_refusees_rien_n_est_ecrit(copie, conn):  # noqa: F811
    texte_avant = copie.read_text(encoding="utf-8")
    with pytest.raises(entretien.EntretienImpossible, match="réponse inconnue"):
        _repondre(conn, copie, "ou", {}, choix={"zone": ["lyon"]})
    with pytest.raises(entretien.EntretienImpossible, match="question inconnue"):
        _repondre(conn, copie, "salaire", {}, choix={"x": ["1"]})
    with pytest.raises(profil.ProfilInvalide):                             # brouillon incohérent
        _repondre(conn, copie, "contrats", {"duree_min": 6, "duree_max": 3}, choix={"contrats": ["stage"]})
    assert copie.read_text(encoding="utf-8") == texte_avant


# --------------------------------------------------------------------------- réponses libres

@pytest.mark.parametrize("q, texte, attendu", [
    ("quand", "de mi-mai à fin août, 3 à 4 mois", {"debut_ideal": "2027-05-15", "duree_min": 3, "duree_max": 4}),
    ("quand", "septembre 2027, 6 mois", {"debut_au_plus_tot": "2027-09-01", "duree_max": 6}),
    ("ou", "Paris ou les Hauts-de-Seine, télétravail ok", {"departements": ["75", "92"], "hybride": True}),
    ("ou", "toute l'Île-de-France, full remote", {"departements": list(profil.DEPARTEMENTS), "full_remote": True}),
    ("quoi", "computer vision et robotique", {"domaines": ["IA / machine learning", "Robotique"]}),
    ("contrats", "stage seulement", {"contrats": ["stage"]}),
    ("contrats", "les CDD aussi", {"contrats": ["stage", "cdd"]}),
    ("entreprises", "Alan et Qonto", {}),
    ("secteurs", "la santé, mais pas la pharma", {}),
])
def test_reponse_libre_sans_ia(copie, conn, sans_ia, q, texte, attendu):  # noqa: F811
    r = _repondre(conn, copie, q, {}, texte=texte)
    assert r["compris"], texte
    for champ, valeur in attendu.items():
        assert r["valeurs"][champ] == valeur, champ
    if q == "entreprises":
        assert [e["nom"] for e in r["valeurs"]["entreprises"]][-2:] == ["Alan", "Qonto"]
    if q == "secteurs":
        assert "medtech" in r["valeurs"]["secteurs_cible"] and "pharma" not in r["valeurs"]["secteurs_cible"]


def test_reponse_libre_pas_comprise(copie, conn, sans_ia):  # noqa: F811
    r = _repondre(conn, copie, "quand", {"contrats": ["stage"]}, texte="je ne sais pas trop")
    assert r == {"valeurs": {"contrats": ["stage"]}, "retenu": None, "compris": False, "refus": []}


def test_reponse_libre_avec_gemini(copie, conn):  # noqa: F811
    faux = FauxGemini({"outil": [{"champ": "debut_ideal", "action": "definir", "valeur": "2027-06-15"},
                                 {"champ": "fin_au_plus_tard", "action": "definir", "valeur": "2027-10-31"},
                                 {"champ": "departements", "action": "definir", "valeur": "75"}]})   # hors question : ignoré
    r = _repondre(conn, copie, "quand", {}, texte="plutôt mi-juin, jusqu'à fin octobre", client=faux)
    assert r["compris"] and r["retenu"] == "Juin 2027 · 3 à 5 mois"
    v = r["valeurs"]
    assert v["debut_ideal"] == "2027-06-15" and v["debut_au_plus_tard"] == "2027-06-15"   # la borne suit le début idéal
    assert "departements" not in v and any("departements" in x for x in r["refus"])
    assert faux.appels[0]["forcer"] and faux.appels[0]["outils"] == ["modifier_profil", "pas_compris"]
    assert "Quand veux-tu commencer" in faux.appels[0]["systeme"]
    ligne = conn.execute("SELECT source, nb_requetes FROM runs").fetchone()
    assert tuple(ligne) == ("accueil", 1)                                   # l'appel est noté dans le Journal


def test_gemini_pas_compris_ou_valeurs_refusees(copie, conn):  # noqa: F811
    faux = FauxGemini({"pas_compris": "hors sujet"})
    r = _repondre(conn, copie, "ou", {}, texte="j'aime les chats", client=faux)
    assert not r["compris"] and r["valeurs"] == {} and r["retenu"] is None
    # deux fois une valeur impossible : rien de noté, et l'IA n'a aucun moyen de dire le contraire
    faux = FauxGemini({"outil": [{"champ": "departements", "action": "definir", "valeur": "69"}]},
                      {"outil": [{"champ": "departements", "action": "definir", "valeur": "Lyon"}]})
    r = _repondre(conn, copie, "ou", {}, texte="à Lyon", client=faux)
    assert not r["compris"] and r["valeurs"] == {} and len(faux.appels) == 2 and r["refus"]


def test_gemini_ajoute_des_entreprises_au_premier_entretien(neuve, conn):
    faux = FauxGemini({"outil": [{"champ": "entreprises", "action": "ajouter", "valeur": "Alan"}]})
    r = _repondre(conn, neuve, "entreprises", {}, texte="Alan", client=faux)
    assert [e["nom"] for e in r["valeurs"]["entreprises"]] == ["Alan"]     # pas la liste du modèle


# --------------------------------------------------------------------------- site

def test_api_et_redirection(client, neuve, monkeypatch):  # noqa: F811
    from stage_scraper.web import serveur
    monkeypatch.setattr(serveur, "CLIENT_IA", FauxGemini({"outil": [{"champ": "contrats", "action": "definir", "valeur": "stage"}]}))
    r = client.get("/a-trier", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/bienvenue"   # profil jamais configuré : l'entretien d'abord
    client.cookies.set("entretien", "plus_tard")
    assert client.get("/a-trier", follow_redirects=False).status_code == 200
    client.cookies.delete("entretien")
    assert "entretien.js" in client.get("/bienvenue").text

    d = client.get("/api/entretien").json()
    assert d["neuf"] and len(d["questions"]) == 6 and d["ia_prete"]
    q = client.post("/api/entretien/question", json={"id": "quand", "valeurs": {}}).json()
    mois = q["rangees"][0]["choix"][3]["id"]
    v = client.post("/api/entretien/repondre", json={"question": "quand", "choix": {"debut": [mois], "duree": ["3-4"]}}).json()["valeurs"]
    r = client.post("/api/entretien/repondre", json={"question": "contrats", "texte": "que des stages", "valeurs": v}).json()
    assert r["compris"] and r["valeurs"]["contrats"] == ["stage"] and r["valeurs"]["duree_max"] == 4
    assert client.post("/api/entretien/repondre", json={"question": "ou", "choix": {"zone": ["mars"]}}).status_code == 400
    assert client.post("/api/entretien/question", json={"id": "x"}).status_code == 400

    a = client.post("/api/entretien/apercu", json={"valeurs": r["valeurs"]}).json()
    assert a["erreur"] is None and a["segments"][1]["texte"] == "un stage"
    fin = client.post("/api/entretien/terminer", json={"valeurs": r["valeurs"]}).json()
    assert {c["champ"] for c in fin["changements"]} >= {"duree_max", "contrats", "recherche"} and fin["retriees"] is not None
    assert client.get("/a-trier", follow_redirects=False).status_code == 200   # c'est fait : plus de redirection
    assert not client.get("/api/entretien").json()["neuf"]
    assert "/bienvenue?depuis=profil" in client.get("/profil").text


def test_textes_traduits():
    textes = [t for q in entretien.QUESTIONS for t in entretien.TEXTES[q]] + list(entretien.LIBELLES_RANGEES.values())
    textes += [d[0] for d in entretien.DOMAINES if d[0] not in ("Data science", "Data analyst", "Data engineering", "Product")]
    textes += [v[0] for v in entretien.SECTEURS.values() if v[0] != "Biotech" and v[0] != "Pharma"]
    textes += [v[0] for v in (*entretien.ZONES.values(), *entretien.TELETRAVAIL.values(), *entretien.CONTRATS.values())]
    textes += ["Décembre 2026", "3 à 5 mois", "Remplir en 6 questions", "Entretien d'accueil", "C'est bon", "Voilà ce que j'ai compris"]
    oublies = [t for t in textes if langue.traduire(t) == t]
    assert not oublies, oublies
