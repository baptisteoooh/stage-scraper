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
    # BAP change son vrai profil (avec le bot, la page...) : la copie repart des critères de référence du cahier des charges
    donnees = reglages.lire(chemin)
    profil.appliquer(donnees, {
        "contrats": ["stage", "cdd"], "departements": list(profil.DEPARTEMENTS), "hybride": True, "full_remote": True,
        "debut_au_plus_tot": "2027-04-01", "debut_ideal": "2027-04-15", "debut_au_plus_tard": "2027-05-10",
        "fin_au_plus_tard": "2027-08-31", "duree_min": 3, "duree_max": 5, "six_mois": "a_negocier",
        "domaines": ["IA / machine learning", "Data science", "Data analyst", "Data engineering", "Logiciel embarqué",
                     "Bioinformatique", "Qualité / réglementaire", "Conseil santé", "Product"],
    })
    reglages.ecrire(donnees, chemin)
    return chemin


class FauxAgent:
    """Rend, dans l'ordre, des appels d'outils ({'outil': [changements]}) ou une réponse finale (dict)."""
    def __init__(self, *reponses):
        self.reponses, self.systemes, self.contents = list(reponses), [], []

    def appeler(self, modele, systeme, contents, schema=None, reflexion=None, outils=None, forcer_outil=False):
        self.forces = getattr(self, "forces", []) + [forcer_outil]
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
        with pytest.raises(agent_profil.AgentImpossible, match="clé Gemini absente"):
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
    donnees = reglages.lire(copie)   # ordre de départ connu (la vraie config peut déjà l'avoir en 4e)
    profil.appliquer(donnees, {"domaines": ["IA / machine learning", "Data science", "Data analyst", "Data engineering",
                                            "Logiciel embarqué", "Bioinformatique"]})
    reglages.ecrire(donnees, copie)
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
    assert faux.forces[:2] == [False, True]   # relancée : l'appel de l'outil est obligatoire


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


def test_garde_fou_refus_sans_essayer(copie, tmp_path):
    """Le cas réel : « change la zone juste au 92 » refusé sans appeler l'outil. Relancée, elle essaie et ça marche."""
    faux = FauxAgent(
        {"reponse": "Je ne peux garder que les départements d'Île-de-France, j'ai donc conservé l'ensemble.", "suggestions": []},
        {"outil": [{"champ": "departements", "action": "definir", "valeur": "92"}]},
        {"reponse": "Ta zone est maintenant limitée aux Hauts-de-Seine.", "suggestions": []},
    )
    r = _agent(copie, tmp_path, faux, "change la zone juste au 92")
    assert "Tu refuses sans avoir essayé" in faux.contents[1][-1]["parts"][0]["text"]
    assert r["profil"]["departements"] == ["92"] and r["erreur"] is False
    assert not any(faux.forces)   # un refus n'est jamais transformé de force en changement


def test_garde_fou_vrai_refus_apres_essai(copie, tmp_path):
    """Lyon : elle essaie, le code refuse, elle explique avec la vraie raison (pas d'erreur, rien de changé)."""
    faux = FauxAgent(
        {"outil": [{"champ": "departements", "action": "ajouter", "valeur": "69"}]},
        {"reponse": "Je ne peux pas : l'outil ne couvre que l'Île-de-France.", "suggestions": []},
    )
    r = _agent(copie, tmp_path, faux, "cherche aussi à Lyon")
    assert r["changements"] == [] and r["erreur"] is False and "Île-de-France" in r["refus"][0]
    assert len(faux.systemes) == 2   # pas de relance : elle a vraiment essayé


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


# --------------------------------------------------------------------------- le bot peut modifier TOUT le profil

CHANGEMENTS_COMPLETS = [   # dans un ordre qui garde les dates cohérentes à chaque étape
    {"champ": "recherche", "action": "definir", "valeur": "Un stage en robotique chirurgicale"},
    {"champ": "ecole", "action": "definir", "valeur": "Centrale"},
    {"champ": "annee", "action": "definir", "valeur": "3e année"},
    {"champ": "majeure", "action": "definir", "valeur": "Robotique"},
    {"champ": "competences", "action": "ajouter", "valeur": "ROS"},
    {"champ": "contrats", "action": "definir", "valeur": "stage"},
    {"champ": "fin_au_plus_tard", "action": "definir", "valeur": "2027-09-30"},
    {"champ": "debut_au_plus_tard", "action": "definir", "valeur": "2027-06-01"},
    {"champ": "debut_ideal", "action": "definir", "valeur": "2027-05-15"},
    {"champ": "debut_au_plus_tot", "action": "definir", "valeur": "2027-05-02"},
    {"champ": "duree_max", "action": "definir", "valeur": "6"},
    {"champ": "duree_min", "action": "definir", "valeur": "4"},
    {"champ": "six_mois", "action": "definir", "valeur": "Toujours exclues"},
    {"champ": "departements", "action": "definir", "valeur": "Paris; Hauts-de-Seine"},
    {"champ": "hybride", "action": "definir", "valeur": "non"},
    {"champ": "full_remote", "action": "definir", "valeur": "non"},
    {"champ": "domaines", "action": "ajouter", "valeur": "Robotique"},
    {"champ": "domaines", "action": "deplacer", "valeur": "Robotique", "position": 1},
    {"champ": "secteurs_cible", "action": "ajouter", "valeur": "robotique médicale"},
    {"champ": "secteurs_ok", "action": "retirer", "valeur": "biotechnologie"},
    {"champ": "secteurs_moins", "action": "definir", "valeur": "pharma; mutuelle"},
    {"champ": "autres_secteurs_domaines", "action": "definir", "valeur": "Robotique"},
    {"champ": "tailles", "action": "definir", "valeur": "PME"},
    {"champ": "entreprises", "action": "ajouter", "valeur": "Alan", "groupe": "scale_up"},
    {"champ": "entreprises", "action": "definir", "valeur": "Alan", "alias": "Alan Health", "outil": "ashby",
     "adresse_ou_id": "alan"},
    {"champ": "entreprises", "action": "definir", "valeur": "Doctolib", "nouveau_nom": "Doctolib SAS", "groupe": "grand_groupe"},
    {"champ": "postes_exclus", "action": "ajouter", "valeur": "growth"},
    {"champ": "contrats_exclus", "action": "retirer", "valeur": "alternance"},
    {"champ": "niveaux_exclus", "action": "ajouter", "valeur": "expert"},
    {"champ": "requetes", "action": "ajouter", "valeur": "stage robotique"},
    {"champ": "requetes", "action": "deplacer", "valeur": "stage robotique", "position": 1},
    {"champ": "anciennete_max_jours", "action": "definir", "valeur": "45"},
]


def test_le_bot_peut_modifier_tout_le_profil(copie):
    donnees = reglages.lire(copie)
    avant = profil.lire(donnees)
    refus = []
    taille = agent_profil.CHANGEMENTS_MAX   # au plus 20 changements par appel de l'outil : plusieurs appels
    for i in range(0, len(CHANGEMENTS_COMPLETS), taille):
        r = agent_profil._executer(donnees, {"name": "modifier_profil",
                                             "args": {"changements": CHANGEMENTS_COMPLETS[i:i + taille]}}, refus,
                                   "Alan est sur ashby, identifiant alan")
        assert all(x["applique"] for x in r["resultats"]), r
    assert refus == [], refus
    p = profil.lire(donnees)
    oublies = [c for c in profil.CHAMPS if p[c] == avant[c]]
    assert oublies == [], f"champs que le bot n'a pas pu changer : {oublies}"
    assert p["departements"] == ["75", "92"] and p["six_mois"] == "exclure" and p["domaines"][0] == "Robotique"
    alan = next(e for e in p["entreprises"] if e["nom"] == "Alan")
    assert alan == {"nom": "Alan", "groupe": "scale_up", "alias": "Alan Health", "outil": "ashby", "adresse_ou_id": "alan"}
    assert any(e["nom"] == "Doctolib SAS" and e["groupe"] == "grand_groupe" for e in p["entreprises"])
    assert "Alan (Scale-up, autres noms : Alan Health, collecte directe : ashby alan)" in profil.en_texte(p)
    reglages.ecrire(donnees, copie)                                   # et tout s'écrit dans config.yaml
    assert profil.lire(reglages.lire(copie)) == p


def test_bot_refus_clairs_entreprises(copie):
    donnees = reglages.lire(copie)
    refus = []
    agent_profil._executer(donnees, {"name": "modifier_profil", "args": {"changements": [
        {"champ": "entreprises", "action": "definir", "valeur": "Inconnue SA", "alias": "x"},
        {"champ": "entreprises", "action": "ajouter", "valeur": "Qonto", "groupe": "pirates"},
    ]}}, refus)
    assert "n'est pas dans tes entreprises suivies" in refus[0] and "groupe inconnu" in refus[1]


def test_bot_ne_devine_pas_l_outil(copie):
    donnees = reglages.lire(copie)
    refus = []
    agent_profil._executer(donnees, {"name": "modifier_profil", "args": {"changements": [
        {"champ": "entreprises", "action": "ajouter", "valeur": "Alan", "groupe": "scale_up", "outil": "ashby"}]}},
        refus, "suis aussi Alan, une scale-up")
    assert "ne devine pas" in refus[0]
    assert all(e["nom"] != "Alan" for e in profil.lire(donnees)["entreprises"])


def test_un_appel_est_verifie_d_un_bloc(copie):
    """Début idéal après le début au plus tard : possible si la borne bouge dans le même appel, dans n'importe quel ordre."""
    donnees = reglages.lire(copie)
    profil.appliquer(donnees, {"debut_au_plus_tot": "2027-05-01", "debut_ideal": "2027-05-01",
                               "debut_au_plus_tard": "2027-05-10", "fin_au_plus_tard": "2027-08-31"})
    refus = []
    r = agent_profil._executer(donnees, {"name": "modifier_profil", "args": {"changements": [
        {"champ": "debut_ideal", "action": "definir", "valeur": "2027-05-15"},
        {"champ": "debut_au_plus_tard", "action": "definir", "valeur": "2027-05-20"}]}}, refus)
    assert refus == [] and profil.lire(donnees)["debut_ideal"] == "2027-05-15"
    r = agent_profil._executer(donnees, {"name": "modifier_profil", "args": {"changements": [
        {"champ": "debut_ideal", "action": "definir", "valeur": "2027-09-15"},   # après la fin au plus tard
        {"champ": "competences", "action": "ajouter", "valeur": "Rust"}]}}, refus)
    assert not any(x["applique"] for x in r["resultats"]) and "rien appliqué" in r["resultats"][1]["raison"]
    assert "Rust" not in profil.lire(donnees)["competences"]


def test_debut_ideal_emmene_sa_borne(copie):
    donnees = reglages.lire(copie)
    profil.appliquer(donnees, {"debut_au_plus_tot": "2027-05-01", "debut_ideal": "2027-05-01",
                               "debut_au_plus_tard": "2027-05-10", "fin_au_plus_tard": "2027-08-31"})
    refus = []
    r = agent_profil._executer(donnees, {"name": "modifier_profil", "args": {"changements": [
        {"champ": "debut_ideal", "action": "definir", "valeur": "2027-05-15"}]}}, refus)
    p = profil.lire(donnees)
    assert refus == [] and (p["debut_ideal"], p["debut_au_plus_tard"]) == ("2027-05-15", "2027-05-15")
    assert "décalé automatiquement" in r["resultats"][1]["note"]
    agent_profil._executer(donnees, {"name": "modifier_profil", "args": {"changements": [
        {"champ": "debut_ideal", "action": "definir", "valeur": "2027-04-20"}]}}, refus)
    assert profil.lire(donnees)["debut_au_plus_tot"] == "2027-04-20"


@pytest.mark.parametrize("texte, codes", [
    ("Paris, Hauts-de-Seine", ["75", "92"]),
    ("Paris et les Hauts-de-Seine", ["75", "92"]),
    ("75 Paris; 92 Hauts-de-Seine", ["75", "92"]),
    ("Paris (75), Val-de-Marne (94)", ["75", "94"]),
    ("75 | 92", ["75", "92"]),     # ce que Gemini envoie vraiment
    ("75 / 92 / 94", ["75", "92", "94"]),
])
def test_departements_en_toutes_lettres(copie, texte, codes):
    donnees = reglages.lire(copie)
    refus = []
    agent_profil._executer(donnees, {"name": "modifier_profil", "args": {"changements": [
        {"champ": "departements", "action": "definir", "valeur": texte}]}}, refus)
    assert refus == [] and profil.lire(donnees)["departements"] == codes


def test_garde_fou_refus_tu(copie, tmp_path):
    """Le cas réel : le code refuse, mais la réponse annonce le changement avec une tournure non détectée."""
    faux = FauxAgent(
        {"outil": [{"champ": "contrats", "action": "definir", "valeur": "contrats courts"}]},
        {"reponse": "Je ne prends plus les stages mais uniquement les CDD.", "suggestions": []},
    )
    r = _agent(copie, tmp_path, faux, "only fixed-term contracts")
    assert r["erreur"] is True and r["reponse"].startswith("Je n'ai rien modifié")
