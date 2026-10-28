"""Tests du module Workday, avec de fausses réponses (aucun appel réseau)."""
import pytest

from stage_scraper.offre import CHAMPS
from stage_scraper.sources.carrieres import workday

API = "https://abbott.wd5.myworkdayjobs.com/wday/cxs/abbott/abbottcareers"

FILTRES_AVEC_PAYS = [
    {"facetParameter": "workerSubType", "values": [
        {"descriptor": "Regular", "id": "reg"},
        {"descriptor": "Intern/Student (Fixed Term) (Trainee)", "id": "int"},
        {"descriptor": "Temporary/Seasonal (Seasonal)", "id": "tmp"},
        {"descriptor": "Apprentice (Fixed Term)", "id": "app"},
    ]},
    {"facetParameter": "locationMainGroup", "values": [
        {"facetParameter": "locationCountry", "values": [
            {"descriptor": "Germany", "id": "de"}, {"descriptor": "France", "id": "fr"}]},
    ]},
]
FILTRES_SANS_PAYS = [
    {"facetParameter": "locationMainGroup", "values": [
        {"facetParameter": "locations", "values": [
            {"descriptor": "Lyon, Auvergne-Rhône-Alpes, France", "id": "lyon"},
            {"descriptor": "San Francisco", "id": "sf"},
            {"descriptor": "Buc", "id": "buc"},
        ]},
    ]},
]


def test_adresse_api():
    assert workday.adresse_api("https://abbott.wd5.myworkdayjobs.com/fr-FR/abbottcareers") == API
    assert workday.adresse_api("https://abbott.wd5.myworkdayjobs.com/abbottcareers/") == API
    with pytest.raises(workday.ErreurWorkday):
        workday.adresse_api("https://www.abbott.com/careers")


def test_filtre_pays_france():
    assert workday.recherches_en_france(FILTRES_AVEC_PAYS) == [({"locationCountry": ["fr"]}, "")]


def test_sans_filtre_pays_on_combine_lieux_et_mot_cle():
    assert workday.recherches_en_france(FILTRES_SANS_PAYS) == [
        ({"locations": ["lyon"]}, ""),   # San Francisco n'est pas pris
        ({}, "France"),                  # pour rattraper « Buc »
    ]


@pytest.mark.parametrize("libelle, attendu", [
    ("Intern (Fixed Term)", "stage"),
    ("Co-op/Intern (Fixed Term)", "stage"),
    ("Intern/Student (Fixed Term) (Trainee)", "stage"),
    ("Temporary (Fixed Term)", "cdd"),
    ("Fixed Term Employee (Non-Intern) (Fixed Term)", "cdd"),
    ("Apprentice (Fixed Term)", None),
    ("Professional apprentice (Fixed Term)", None),
    ("Temporary Agency Worker", None),
    ("Regular", None),
])
def test_contrat_depuis_libelle(libelle, attendu):
    assert workday.contrat_depuis_libelle(libelle) == attendu


def test_filtres_contrat():
    assert workday.filtres_contrat(FILTRES_AVEC_PAYS) == {
        "stage": {"workerSubType": ["int"]},
        "cdd": {"workerSubType": ["tmp"]},
    }


class FausseSession:
    """Imite Workday : 3 offres en France, dont un stage classé Intern et un repéré par son titre."""
    headers: dict = {}

    def __init__(self):
        self.headers = {}

    def post(self, url, json, timeout):
        facets = json["appliedFacets"]
        if json["limit"] == 1:
            return Reponse({"total": 3, "facets": FILTRES_AVEC_PAYS, "jobPostings": []})
        jobs = [
            {"title": "Data Analyst Intern", "externalPath": "/job/a", "bulletFields": ["R1"]},
            {"title": "Stage IA santé", "externalPath": "/job/b", "bulletFields": ["R2"]},
            {"title": "Senior Manager", "externalPath": "/job/c", "bulletFields": ["R3"]},
        ]
        if facets.get("workerSubType") == ["int"]:
            jobs = jobs[:1]
        elif facets.get("workerSubType"):
            jobs = []
        return Reponse({"total": len(jobs), "jobPostings": jobs})

    def get(self, url, timeout):
        chemin = url.rsplit("/", 1)[1]
        return Reponse({"jobPostingInfo": {
            "title": f"Titre {chemin}", "jobReqId": f"REQ-{chemin}", "location": "France - Issy les Moulineaux",
            "startDate": "2026-10-27", "jobDescription": "<p>Une <b>super</b> mission</p>",
            "externalUrl": f"https://abbott.wd5.myworkdayjobs.com/abbottcareers/job/{chemin}",
        }})


class Reponse:
    status_code = 200

    def __init__(self, donnees):
        self.donnees = donnees

    def raise_for_status(self):
        pass

    def json(self):
        return self.donnees


def test_collecter(monkeypatch):
    monkeypatch.setattr(workday.requests, "Session", FausseSession)
    monkeypatch.setattr(workday.time, "sleep", lambda s: None)
    entreprise = {"nom": "Abbott", "carrieres": {"outil": "workday", "url": "https://abbott.wd5.myworkdayjobs.com/abbottcareers"}}
    offres = workday.collecter(entreprise)
    assert [o["source_id"] for o in offres] == ["workday:abbott:REQ-a", "workday:abbott:REQ-b"]  # le CDI est écarté
    assert [o["type_contrat"] for o in offres] == ["stage", "stage"]
    offre = offres[0]
    assert set(offre) == set(CHAMPS)
    assert offre["entreprise"] == "Abbott" and offre["site_origine"] == "Workday"
    assert offre["description"] == "Une super mission"
    assert offre["date_publication"] == "2026-10-27"
