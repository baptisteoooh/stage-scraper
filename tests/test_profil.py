"""Profil de recherche (« Mon profil ») : lecture et écriture de config.yaml, vérifications, agent en conversation.

Toujours sur une copie de config.yaml ; l'IA est remplacée par un faux client (aucun appel réseau)."""
import json
import shutil

import pytest

from stage_scraper import agent_profil, profil, reglages
from stage_scraper.config import CHEMIN_CONFIG
from test_site_web import base, client  # noqa: F401  (fixtures)


@pytest.fixture
def copie(tmp_path, monkeypatch):
    chemin = tmp_path / "config.yaml"
    shutil.copyfile(CHEMIN_CONFIG, chemin)
    monkeypatch.setenv("STAGE_SCRAPER_CONFIG", str(chemin))   # jamais le vrai config.yaml
    return chemin


class FauxAgent:
    """Rend, dans l'ordre, des appels d'outils ({'outil': [changements]}) ou une réponse finale (dict)."""
    def __init__(self, *reponses):
        self.reponses, self.systemes, self.contents = list(reponses), [], []

    def appeler(self, modele, systeme, contents, schema=None, reflexion=None, outils=None):
        self.systemes.append(systeme)
        self.contents.append(list(contents))
        r = self.reponses.pop(0)
        if "outil" in r:
            assert outils, "l'outil n'est plus proposé au dernier tour"
            return {"role": "model", "parts": [{"functionCall": {"name": "modifier_profil",
                                                                  "args": {"changements": r["outil"]}}}]}, {}
        return {"role": "model", "parts": [{"text": json.dumps(r, ensure_ascii=False)}]}, {}


def test_lire_profil_de_bap(copie):
    p = profil.lire(reglages.lire(copie))
    assert p["domaines"][0] == "IA / machine learning" and "domaines_phares" not in p
    assert p["duree_min"] <= p["duree_max"] and p["debut_au_plus_tot"] <= p["debut_ideal"] <= p["debut_au_plus_tard"]
    assert set(p["departements"]) == set(profil.DEPARTEMENTS) and p["contrats"] == ["stage", "cdd"]
    assert p["entreprises"][0]["nom"] == "Doctolib" and p["entreprises"][0]["groupe"] == "priorite_absolue"
    assert p["recherche"] and profil.alertes(p) == []
    assert profil.zone(p).startswith("Île-de-France")


def test_appliquer_garde_les_commentaires(copie):
    texte_avant = copie.read_text(encoding="utf-8")
    donnees = reglages.lire(copie)
    ch = profil.appliquer(donnees, {"duree_max": "6", "domaines": ["Data science", "IA / machine learning", "Robotique"],
                                    "departements": ["75", "92"], "postes_exclus": ["marketing", "growth"]})
    assert {c["champ"] for c in ch} == {"duree_max", "departements", "domaines", "postes_exclus"}
    assert next(c for c in ch if c["champ"] == "duree_max")["avant"] == 5
    reglages.ecrire(donnees, copie)
    texte = copie.read_text(encoding="utf-8")
    assert "# Secteurs" in texte and "# Entreprises suivies" in texte and texte != texte_avant
    p = profil.lire(reglages.lire(copie))
    assert p["domaines"] == ["Data science", "IA / machine learning", "Robotique"]
    texte = copie.read_text(encoding="utf-8")                  # le premier domaine devient le très intéressant
    debut = texte.index("domaines:\n")
    assert texte.index("tres_interessant: true", debut) < texte.index("- nom: IA / machine learning", debut)
    assert p["duree_max"] == 6 and p["departements"] == ["75", "92"]
    # un domaine retiré disparaît des listes qui en dépendent
    donnees = reglages.lire(copie)
    profil.appliquer(donnees, {"domaines": ["Robotique"]})
    assert profil.lire(donnees)["autres_secteurs_domaines"] == []


@pytest.mark.parametrize("valeurs, message", [
    ({"duree_min": 7}, "durée minimale"),
    ({"debut_ideal": "2027-06-01"}, "début idéal"),
    ({"fin_au_plus_tard": "2027-04-30"}, "fin au plus tard"),
    ({"debut_au_plus_tot": "31/04/2027"}, "AAAA-MM-JJ"),
    ({"departements": ["69"]}, "Île-de-France"),
    ({"contrats": []}, "au moins un type de contrat"),
    ({"contrats": ["cdi"]}, "stage"),
    ({"autres_secteurs_domaines": ["Cuisine"]}, "n'est pas dans tes domaines"),
    ({"entreprises": [{"nom": "X", "groupe": "pirate"}]}, "groupe inconnu"),
    ({"inconnu": 1}, "champ inconnu"),
])
def test_valeurs_refusees(copie, valeurs, message):
    donnees = reglages.lire(copie)
    with pytest.raises(profil.ProfilInvalide, match=message):
        profil.appliquer(donnees, valeurs)
    assert profil.lire(donnees) == profil.lire(reglages.lire(copie))   # rien n'a bougé


def test_alertes():
    p = profil.lire(reglages.lire(CHEMIN_CONFIG))
    assert "que" in profil.alertes({**p, "duree_min": 6, "duree_max": 6})[0]
    assert any("6 mois" in a for a in profil.alertes({**p, "duree_max": 6, "six_mois": "exclure"}))


def test_prompts_suivent_le_profil(copie):
    from contextlib import closing
    import sqlite3
    from stage_scraper import chat_offres, db, scoring
    from stage_scraper.config import charger_config
    donnees = reglages.lire(copie)
    profil.appliquer(donnees, {"recherche": "Un stage en robotique chirurgicale", "secteurs_cible": ["robotique"],
                               "departements": ["75"]})
    reglages.ecrire(donnees, copie)
    config = charger_config(copie)
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.row_factory = sqlite3.Row
        db.initialiser(conn)
        systeme = scoring.prompt_systeme(conn, config)[0]["text"]
    assert "robotique chirurgicale" in systeme and "Secteurs visés (cible principale) : robotique." in systeme
    assert "Lieu : Paris (75)" in systeme and "Doctolib en priorité absolue" in systeme
    assert "robotique chirurgicale" in chat_offres.consignes(config, [], None)


def test_agent_modifie_et_annule(client, copie, monkeypatch):  # noqa: F811
    from stage_scraper.web import serveur
    faux = FauxAgent(
        {"outil": [{"champ": "duree_max", "action": "definir", "valeur": "6"},
                   {"champ": "six_mois", "action": "definir", "valeur": "n'importe quoi"},
                   {"champ": "entreprises", "action": "ajouter", "valeur": "Alan : scale-up"},
                   {"champ": "domaines", "action": "ajouter", "valeur": "Robotique"},
                   {"champ": "departements", "action": "retirer", "valeur": "Val-d'Oise"}]},
        {"reponse": "Je garde maintenant les stages jusqu'à 6 mois, et je suis Alan.", "suggestions": ["Merci"]},
    )
    monkeypatch.setattr(serveur, "CLIENT_IA", faux)
    d = client.get("/api/profil").json()
    assert d["profil"]["duree_max"] == 5 and d["messages"] == [] and d["champs"]["duree_max"]["type"] == "nombre"

    r = client.post("/api/profil/message", json={"texte": "Accepte les stages de 6 mois et suis Alan"}).json()
    champs = {c["champ"]: c for c in r["changements"]}
    assert set(champs) == {"duree_max", "entreprises", "domaines", "departements"}
    assert champs["duree_max"]["avant"] == 5 and champs["duree_max"]["apres"] == 6
    assert r["profil"]["entreprises"][-1] == {"nom": "Alan", "groupe": "scale_up", "alias": "", "outil": "", "adresse_ou_id": ""}
    assert "95" not in r["profil"]["departements"] and r["profil"]["domaines"][-1] == "Robotique"
    assert len(r["messages"]) == 2 and r["messages"][1]["suggestions"] == ["Merci"]
    assert "Offres de 6 mois" in r["messages"][1]["refus"][0]           # la valeur invalide a été refusée
    assert "duree_max — Durée maximale : 5" in faux.systemes[0]          # l'agent voit le profil...
    assert "duree_max — Durée maximale : 6" in faux.systemes[1]          # ... à jour après ses changements
    assert profil.lire(reglages.lire(copie))["duree_max"] == 6           # écrit dans la copie

    # Annuler : la page renvoie les anciennes valeurs
    r = client.post("/api/profil", json={"valeurs": {c["champ"]: c["avant"] for c in r["changements"]}}).json()
    assert r["profil"]["duree_max"] == 5 and "Alan" not in [e["nom"] for e in r["profil"]["entreprises"]]
    assert len(r["changements"]) == 4

    # Le message suivant reçoit l'historique, avec ce qui avait été changé
    faux.reponses.append({"reponse": "Pour quelle date ?", "suggestions": ["1er mai", "15 mai"]})
    r = client.post("/api/profil/message", json={"texte": "Je veux commencer plus tard"}).json()
    assert r["changements"] == [] and r["messages"][-1]["suggestions"] == ["1er mai", "15 mai"]
    assert "changements appliqués : Durée maximale : 6" in faux.contents[-1][1]["parts"][0]["text"]
    assert client.post("/api/profil/effacer").json() == {"messages": []}


def test_api_profil_refus_et_vide(client, copie, monkeypatch):  # noqa: F811
    from stage_scraper.web import serveur
    monkeypatch.setattr(serveur, "CLIENT_IA", FauxAgent())
    r = client.post("/api/profil", json={"valeurs": {"duree_min": 9}})
    assert r.status_code == 400 and "durée minimale" in r.json()["detail"]
    assert client.post("/api/profil/message", json={"texte": "  "}).status_code == 400
    r = client.post("/api/profil", json={"valeurs": {"hybride": False, "anciennete_max_jours": 60}}).json()
    assert {c["champ"] for c in r["changements"]} == {"hybride", "anciennete_max_jours"}
    assert client.post("/api/profil", json={"valeurs": {"hybride": False}}).json()["changements"] == []


def test_agent_sans_cle(copie, monkeypatch, tmp_path):
    from contextlib import closing
    from stage_scraper import db
    monkeypatch.setattr(agent_profil, "secret", lambda nom: None)
    with closing(db.connecter(tmp_path / "x.db")) as conn:
        db.initialiser(conn)
        with pytest.raises(agent_profil.AgentImpossible, match="GEMINI_API_KEY"):
            agent_profil.demander(conn, copie, {}, "bonjour")


# --------------------------------------------------------------------------- garde-fou : jamais « c'est fait » à tort

def _agent(copie, tmp_path, faux, message):
    from contextlib import closing
    from stage_scraper import db
    with closing(db.connecter(tmp_path / "x.db")) as conn:
        db.initialiser(conn)
        return agent_profil.demander(conn, copie, {}, message, client=faux)


def test_garde_fou_relance_puis_deplace(copie, tmp_path):
    """Le cas réel : l'IA dit « J'ai remonté la bioinformatique » sans rien faire. Relancée, elle le fait."""
    faux = FauxAgent(
        {"reponse": "J'ai remonté la bioinformatique à la quatrième place.", "suggestions": [], "annonce_modification": True},
        {"outil": [{"champ": "domaines", "action": "deplacer", "valeur": "bioinformatique", "position": 4}]},
        {"reponse": "La bioinformatique est maintenant en 4e position.", "suggestions": [], "annonce_modification": True},
    )
    r = _agent(copie, tmp_path, faux, "je préfère bioinformatique en 4")
    assert "[Contrôle automatique]" in faux.contents[1][-1]["parts"][0]["text"]   # la relance
    assert r["profil"]["domaines"][3] == "Bioinformatique" and r["erreur"] is False
    assert [c["champ"] for c in r["changements"]] == ["domaines"]
    assert profil.lire(reglages.lire(copie))["domaines"][3] == "Bioinformatique"


def test_garde_fou_remplace_le_mensonge(copie, tmp_path):
    """Elle ment deux fois : sa réponse est remplacée par une erreur honnête, rien n'est écrit."""
    texte_avant = copie.read_text(encoding="utf-8")
    faux = FauxAgent(
        {"reponse": "C'est fait, j'ai déplacé la bioinformatique.", "suggestions": ["Merci"], "annonce_modification": False},
        {"reponse": "J'ai bien déplacé la bioinformatique.", "suggestions": [], "annonce_modification": True},
    )
    r = _agent(copie, tmp_path, faux, "bioinformatique en 4")
    assert r["erreur"] is True and r["changements"] == [] and r["suggestions"] == []
    assert r["reponse"].startswith("Je n'ai rien modifié")
    assert copie.read_text(encoding="utf-8") == texte_avant


def test_garde_fou_refus_explique(copie, tmp_path):
    """Un changement refusé puis annoncé quand même : l'erreur donne la raison du refus."""
    faux = FauxAgent(
        {"outil": [{"champ": "domaines", "action": "deplacer", "valeur": "Bioinformatique", "position": 40}]},
        {"reponse": "J'ai mis la bioinformatique en 40e place.", "suggestions": []},
        {"reponse": "C'est fait.", "suggestions": []},
    )
    r = _agent(copie, tmp_path, faux, "bioinformatique en 40")
    assert r["erreur"] is True and "position 40 impossible" in r["reponse"]


def test_garde_fou_laisse_passer_les_questions(copie, tmp_path):
    faux = FauxAgent({"reponse": "Pour quelle date de début, plutôt ?", "suggestions": ["1er mai"], "annonce_modification": False})
    r = _agent(copie, tmp_path, faux, "je veux commencer plus tard")
    assert r["erreur"] is False and r["reponse"] == "Pour quelle date de début, plutôt ?" and len(faux.systemes) == 1


@pytest.mark.parametrize("texte, annonce", [
    ("J'ai remonté la bioinformatique à la quatrième place dans tes domaines de préférence.", True),
    ("Je garde maintenant les stages jusqu'à 6 mois.", True),
    ("C'est fait !", True),
    ("I've moved bioinformatics to 4th place.", True),
    ("Pour quelle date de début, plutôt ?", False),
    ("Tu as déjà la bioinformatique en 4e position : rien à changer.", False),
    ("Je n'ai rien modifié : dis-moi quelle date.", False),
])
def test_detecteur_d_annonces(texte, annonce):
    from stage_scraper import garde_fou
    assert garde_fou.annonce_action(texte) is annonce
