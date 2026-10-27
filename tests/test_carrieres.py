"""Tests des pages carrières (Ashby), sur une vraie réponse enregistrée (aucun appel réseau)."""
import json
from pathlib import Path

import requests

from stage_scraper.offre import CHAMPS
from stage_scraper.sources import Contexte, carrieres
from stage_scraper.sources.carrieres import ashby

EXEMPLE = Path(__file__).parent / "donnees" / "ashby_doctolib_exemple.json"
DOCTOLIB = {"nom": "Doctolib", "groupe": "priorite_absolue", "carrieres": {"outil": "ashby", "id": "doctolib"}}


def jobs():
    return json.loads(EXEMPLE.read_text(encoding="utf-8"))["jobs"]


class FausseReponse:
    def __init__(self, donnees):
        self.donnees = donnees

    def raise_for_status(self):
        pass

    def json(self):
        return self.donnees


def test_seuls_stages_et_cdd_sont_gardes(monkeypatch):
    monkeypatch.setattr(ashby.requests, "get", lambda *a, **k: FausseReponse({"jobs": jobs()}))
    offres = ashby.collecter(DOCTOLIB)
    assert [o["titre"] for o in offres] == [
        "Machine Learning Engineer Intern (x/f/m)",
        "Medical Data Intern (x/f/m)",
        "Stage - Assistant Commercial (x/f/m) - janvier 2027",
    ]  # le CDI (FullTime) et le Contract sont écartés
    for offre in offres:
        assert set(offre) == set(CHAMPS)
        assert offre["entreprise"] == "Doctolib" and offre["type_contrat"] == "stage"


def test_offre_ile_de_france():
    offre = ashby.convertir(jobs()[0], "Doctolib", "doctolib")
    assert offre["source"] == "carrieres"
    assert offre["source_id"] == f"ashby:doctolib:{jobs()[0]['id']}"
    assert offre["lieu"] == "Levallois-Perret, Ile-de-France, France"
    assert offre["departement"] == "92"
    assert offre["teletravail"] == "hybride"
    assert offre["date_publication"] == "2026-10-26"
    assert offre["lien"].startswith("https://jobs.ashbyhq.com/doctolib/")


def test_offre_hors_france_et_sans_adresse():
    berlin = ashby.convertir(jobs()[1], "Doctolib", "doctolib")
    assert berlin["departement"] is None and "Germany" in berlin["lieu"]
    sans_adresse = ashby.convertir(jobs()[2], "Doctolib", "doctolib")
    assert sans_adresse["lieu"] == "Strasbourg" and sans_adresse["departement"] is None


def test_cdd_et_titre():
    job = dict(jobs()[3], employmentType="Temporary")
    assert ashby.convertir(job, "Doctolib", "doctolib")["type_contrat"] == "cdd"
    job = dict(jobs()[3], employmentType="FullTime", title="Stagiaire data")
    assert ashby.convertir(job, "Doctolib", "doctolib")["type_contrat"] == "stage"


def test_une_entreprise_en_panne_ne_bloque_pas_les_autres(monkeypatch):
    def collecter(entreprise):
        if entreprise["nom"] == "Panne":
            raise requests.ConnectionError("serveur injoignable")
        return [{"titre": "ok"}]
    monkeypatch.setattr(ashby, "collecter", collecter)
    monkeypatch.setattr(carrieres.time, "sleep", lambda s: None)
    config = {"sources": {"carrieres": {}}, "entreprises_suivies": [
        {"nom": "Panne", "carrieres": {"outil": "ashby", "id": "x"}},
        {"nom": "Inconnu", "carrieres": {"outil": "outil_inconnu", "id": "y"}},
        {"nom": "Sans bloc"},
        DOCTOLIB,
    ]}
    resultat = carrieres.collecter(config, Contexte())
    assert resultat.offres == [{"titre": "ok"}]
    assert resultat.nb_requetes == 2
    assert len(resultat.erreurs) == 2
