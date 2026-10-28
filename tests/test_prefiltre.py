"""Tests du pré-filtre, avec les vrais réglages de config.yaml."""
from datetime import date

import pytest

from stage_scraper import prefiltre
from stage_scraper.config import charger_config
from stage_scraper.texte import contient

CONFIG = charger_config()
AUJOURD_HUI = date(2026, 10, 28)


def raison(**champs):
    offre = {"titre": "Stage Data Scientist", "entreprise": "Startup", "lieu": "Paris",
             "date_publication": "2026-10-20", **champs}
    return prefiltre.verifier(offre, CONFIG, AUJOURD_HUI)[0]


def test_contient_sigles_et_accents():
    assert contient("Stage qualité de vie au travail", "VIE") is False   # sigle : majuscules exigées
    assert contient("Mission VIE à Boston", "VIE") is True
    assert contient("Stage en Île-de-France", "ile de france") is True
    assert contient("Stage marketing", "market") is False                 # mot entier seulement


@pytest.mark.parametrize("titre, attendu", [
    ("Stage Data Scientist", None),
    ("Alternance - Data Analyst", "contrat : alternance"),
    ("Stage ou alternance - Data Analyst", None),               # stage possible : gardée
    ("Stage de fin d'études - Data Engineer", "contrat"),
    ("Stage de fin d'étude Data Scientist", "contrat"),
    ("Final year internship - Data Scientist", "contrat"),
    ("Stage Marketing Digital", "poste : marketing"),
    ("Intern Sales Operations", "poste : sales"),
    ("Senior Data Engineer", "niveau : senior"),
    ("Stage qualité de vie au travail - data", None),            # « vie » n'est pas un VIE
])
def test_titres(titre, attendu):
    resultat = raison(titre=titre)
    if attendu is None:
        assert resultat is None
    else:
        assert resultat and resultat.startswith(attendu)


@pytest.mark.parametrize("lieu, departement, garde", [
    ("Paris", None, True),
    ("Levallois-Perret, Ile-de-France, France", None, True),
    ("Limours, Essonne", None, True),
    ("St-Ouen, Seine-St-Denis", None, True),
    ("Paris 13", None, True),                     # arrondissement, pas le département 13
    ("92300 Levallois", None, True),
    ("France", None, True),                       # lieu vague : gardé
    ("3 Locations", None, True),
    ("", None, True),
    ("Lyon", None, False),
    ("Berlin, Berlin, Germany", None, False),
    ("69003 Lyon", None, False),
    ("Quelque part", "92", True),                 # le département fourni par la source prime
])
def test_lieux(lieu, departement, garde):
    assert (raison(lieu=lieu, departement=departement) is None) is garde


def test_full_remote_garde_meme_hors_idf():
    assert raison(lieu="Lyon", teletravail="télétravail complet") is None


def test_anciennete():
    assert raison(date_publication="2026-06-01").startswith("trop ancienne")
    assert raison(date_publication="2026-09-01") is None


@pytest.mark.parametrize("texte, attendu", [
    ("Stage 4 mois", ("4 mois", 4, 4)),
    ("Stage (3 à 6 mois)", ("3 a 6 mois", 3, 6)),
    ("Internship (6-month)", ("6-month", 6, 6)),
    ("Stage 4,5 mois", ("4,5 mois", 4.5, 4.5)),
    ("Stage Data", None),
])
def test_analyser_duree_titre(texte, attendu):
    assert prefiltre.analyser_duree(texte, None) == attendu


def test_duree_description_seulement_si_annoncee():
    assert prefiltre.analyser_duree("Stage", "Créée il y a 6 mois, notre startup...") is None
    assert prefiltre.analyser_duree("Stage", "Stage d'une durée de 4 mois à Paris.")[2] == 4


@pytest.mark.parametrize("titre, entreprise, garde", [
    ("Stage Data 4 mois", "Startup", True),
    ("Stage Data 3 à 6 mois", "Startup", True),
    ("Stage Data 4 à 6 mois", "Startup", True),
    ("Stage Data 6 mois", "Startup", False),       # 6 mois sec : exclu...
    ("Stage Data 6 mois", "Doctolib", True),       # ... sauf entreprise suivie (à négocier)
    ("Stage Data 6 mois", "J&J", True),            # alias d'une entreprise suivie
    ("Stage Data 2 mois", "Startup", False),
    ("CDD 12 mois", "Doctolib", False),
    ("Stage 6 à 12 mois", "Startup", False),
])
def test_durees(titre, entreprise, garde):
    assert (raison(titre=titre, entreprise=entreprise) is None) is garde


@pytest.mark.parametrize("titre, description, garde", [
    ("Stage Data - janvier 2027", None, False),
    ("Stage Data - avril 2027", None, True),
    ("Stage Data - mai 2027", None, True),
    ("Stage Data - Jan/Fév 2027", None, False),
    ("Stage Data (March 2027)", None, False),
    ("Stage Data", "Stage à partir de septembre 2027.", False),
    ("Stage Data", "Début du stage : avril.", True),
    ("Stage Data", "Nous existons depuis janvier 2020.", True),   # pas une date de début
])
def test_dates_de_debut(titre, description, garde):
    assert (raison(titre=titre, description=description) is None) is garde


def test_champs_detectes():
    offre = {"titre": "Stage Data 4 mois - avril 2027", "lieu": "92100 Boulogne", "entreprise": "X"}
    _, detectes = prefiltre.verifier(offre, CONFIG, AUJOURD_HUI)
    assert detectes == {"departement": "92", "duree": "4 mois", "duree_mois": 4, "date_debut": "2027-04-01"}


def test_entreprise_suivie():
    assert prefiltre.entreprise_suivie("Johnson & Johnson MedTech France", CONFIG)["nom"] == "Johnson & Johnson MedTech"
    assert prefiltre.entreprise_suivie("GE Healthcare", CONFIG)["nom"] == "GE HealthCare"
    assert prefiltre.entreprise_suivie("Doctolibre", CONFIG) is None
    assert prefiltre.entreprise_suivie(None, CONFIG) is None
