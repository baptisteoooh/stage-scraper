"""L'agent de « Mon profil » face au VRAI Gemini (gratuit) : ce que l'étudiant écrit change-t-il vraiment le profil ?

Ces tests ne tournent que sur demande, car ils passent par Internet et le quota gratuit de Gemini :
    PowerShell : $env:GEMINI_REEL="1"; python -m pytest tests/test_gemini_reel.py -v
    CMD        : set GEMINI_REEL=1 && python -m pytest tests/test_gemini_reel.py -v
Toujours sur une copie de config.yaml et une base temporaire : rien de réel n'est modifié.
Gemini ne répond pas toujours pareil : un échec isolé peut se relancer, des échecs répétés montrent un vrai défaut.
"""
import os
import shutil
import time
from contextlib import closing

import pytest

from stage_scraper import agent_profil, db, garde_fou, gemini, profil, reglages
from stage_scraper.config import CHEMIN_CONFIG, charger_config, secret

pytestmark = [pytest.mark.reseau,
              pytest.mark.skipif(os.environ.get("GEMINI_REEL") != "1" or not secret("GEMINI_API_KEY"),
                                 reason="vrais appels Gemini : mettre GEMINI_REEL=1 (et GEMINI_API_KEY dans .env)")]

PAUSE_S = 4   # entre deux tests : l'offre gratuite limite le nombre de requêtes par minute


@pytest.fixture
def agent(tmp_path, monkeypatch):
    """Renvoie demander(message, historique) -> réponse de l'agent, sur une copie de config.yaml."""
    copie = tmp_path / "config.yaml"
    shutil.copyfile(CHEMIN_CONFIG, copie)
    monkeypatch.setenv("STAGE_SCRAPER_CONFIG", str(copie))
    config = charger_config(copie)
    client = gemini.ClientGemini(delai_entre_appels=1)
    conn = db.connecter(tmp_path / "essai.db")
    db.initialiser(conn)

    def demander(message, historique=None):
        r = agent_profil.demander(conn, copie, config, message, historique, client=client)
        r["avant"] = profil.lire(reglages.lire(CHEMIN_CONFIG))   # le profil de départ (la vraie config, lue seulement)
        r["ecrit"] = profil.lire(reglages.lire(copie))           # ce qui a été écrit dans la copie
        _jamais_de_mensonge(r)
        return r

    with closing(conn):
        yield demander
    time.sleep(PAUSE_S)


def _jamais_de_mensonge(r):
    """Le garde-fou : soit il y a de vrais changements, soit la réponse n'annonce rien (ou c'est une erreur honnête)."""
    if not r["changements"]:
        assert r["erreur"] or not garde_fou.annonce_action(r["reponse"]), f"annonce sans changement : {r['reponse']}"
    assert r["ecrit"] == r["profil"], "la réponse ne correspond pas à ce qui est écrit dans config.yaml"


def _champs(r):
    return {c["champ"] for c in r["changements"]}


# --------------------------------------------------------------------------- demandes claires : le profil change

def test_deplacer_un_domaine(agent):
    r = agent("mets la bioinformatique en 4 dans mes domaines")
    assert r["profil"]["domaines"][3] == "Bioinformatique", r["reponse"]
    assert sorted(r["profil"]["domaines"]) == sorted(r["avant"]["domaines"])   # rien d'ajouté ni de perdu


def test_mettre_un_domaine_en_tete(agent):
    r = agent("Data science devient mon domaine préféré")
    assert r["profil"]["domaines"][0] == "Data science", r["reponse"]


def test_duree_six_mois(agent):
    r = agent("accepte aussi les stages de 6 mois")
    assert r["profil"]["duree_max"] == 6, r["reponse"]


def test_date_de_debut_ideale(agent):
    r = agent("idéalement je voudrais commencer le 15 mai 2027")
    p = r["profil"]
    assert p["debut_ideal"] == "2027-05-15", r["reponse"]
    assert p["debut_au_plus_tot"] <= p["debut_ideal"] <= p["debut_au_plus_tard"] < p["fin_au_plus_tard"]


def test_suivre_une_entreprise(agent):
    r = agent("suis aussi Alan, c'est une scale-up de la santé")
    alan = next((e for e in r["profil"]["entreprises"] if e["nom"].lower() == "alan"), None)
    assert alan is not None and alan["groupe"] == "scale_up", r["reponse"]
    assert alan["outil"] == ""   # il ne devine jamais l'outil de recrutement


def test_ne_plus_suivre(agent):
    r = agent("ne suis plus Medtronic")
    assert all(e["nom"] != "Medtronic" for e in r["profil"]["entreprises"]), r["reponse"]


def test_collecte_directe_donnee_par_l_etudiant(agent):
    r = agent("Withings utilise Ashby pour ses offres, l'identifiant est withings")
    w = next(e for e in r["profil"]["entreprises"] if e["nom"] == "Withings")
    assert (w["outil"], w["adresse_ou_id"]) == ("ashby", "withings"), r["reponse"]


def test_departements_par_leur_nom(agent):
    r = agent("je ne veux plus que Paris et les Hauts-de-Seine")
    assert sorted(r["profil"]["departements"]) == ["75", "92"], r["reponse"]


def test_zone_juste_un_departement(agent):
    """Le cas réel du 21/11 : il refusait en disant que le 92 n'était pas possible."""
    r = agent("change la zone juste au 92")
    assert r["profil"]["departements"] == ["92"], r["reponse"]


def test_teletravail(agent):
    r = agent("je ne veux pas de télétravail complet")
    assert r["profil"]["full_remote"] is False, r["reponse"]


def test_six_mois_toujours_exclus(agent):
    r = agent("exclus toujours les offres de 6 mois, même chez mes entreprises suivies")
    assert r["profil"]["six_mois"] == "exclure", r["reponse"]


def test_anciennete(agent):
    r = agent("ignore les offres publiées il y a plus de 60 jours")
    assert r["profil"]["anciennete_max_jours"] == 60, r["reponse"]


def test_plusieurs_changements_d_un_coup(agent):
    r = agent("ajoute la robotique à mes domaines et exclus les postes de growth")
    assert any("robot" in d.lower() for d in r["profil"]["domaines"]), r["reponse"]
    assert any("growth" in x.lower() for x in r["profil"]["postes_exclus"]), r["reponse"]


def test_en_anglais(agent):
    r = agent("from now on I only want fixed-term contracts, no more internships")
    assert r["profil"]["contrats"] == ["cdd"], r["reponse"]


# --------------------------------------------------------------------------- pas de changement : il le dit honnêtement

def test_demande_ambigue_une_question(agent):
    r = agent("je veux commencer plus tard")
    assert r["changements"] == [] and not r["erreur"], r["reponse"]
    assert "?" in r["reponse"]


def test_hors_ile_de_france(agent):
    r = agent("cherche aussi des stages à Lyon")
    assert r["profil"]["departements"] == r["avant"]["departements"], r["reponse"]
    assert "departements" not in _champs(r)


def test_retirer_ce_qui_n_existe_pas(agent):
    r = agent("retire le domaine cuisine")
    assert r["changements"] == [], r["reponse"]   # rien à retirer : et surtout pas de « c'est fait » (vérifié par la fixture)


def test_suite_de_conversation(agent):
    r1 = agent("je veux commencer plus tard")
    assert r1["changements"] == [], r1["reponse"]
    historique = [{"role": "user", "texte": "je veux commencer plus tard", "changements": []},
                  {"role": "assistant", "texte": r1["reponse"], "changements": []}]
    time.sleep(PAUSE_S)
    r2 = agent("plutôt le 1er juin 2027 comme début idéal", historique)
    p = r2["profil"]
    assert p["debut_ideal"] == "2027-06-01", r2["reponse"]
    assert p["debut_au_plus_tot"] <= p["debut_ideal"] <= p["debut_au_plus_tard"]
