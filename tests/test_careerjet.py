"""Tests de la source Careerjet, sur une vraie réponse enregistrée (aucun appel réseau)."""
import json
from pathlib import Path

from stage_scraper.offre import CHAMPS
from stage_scraper.sources import careerjet

EXEMPLE = Path(__file__).parent / "donnees" / "careerjet_exemple.json"


def charger_offres():
    jobs = json.loads(EXEMPLE.read_text(encoding="utf-8"))["jobs"]
    return [careerjet.convertir(job) for job in jobs]


def test_toutes_les_offres_sont_converties():
    offres = charger_offres()
    assert len(offres) == 20
    for offre in offres:
        assert set(offre) == set(CHAMPS)
        assert offre["source"] == "careerjet"
        assert offre["type_contrat"] == "stage"
        assert offre["titre"] and offre["lien"] and offre["date_publication"]


def test_premiere_offre():
    offre = charger_offres()[0]
    assert offre["titre"] == "Data Scientist Assistant - Stage (6 mois) Mars 2027 (F/H/NB)"
    assert offre["entreprise"] == "Ubisoft"
    assert offre["lieu"] == "Paris"
    assert offre["date_publication"] == "2026-10-24"
    assert "<b>" not in offre["description"]
    assert offre["gratification"] is None


def test_gratification():
    vusion = [o for o in charger_offres() if o["entreprise"] == "Vusion"][0]
    assert vusion["gratification"] == "€14400 - 18000 per year"


def test_identifiant_stable():
    job = {"title": "Stage IA", "company": "X", "locations": "Paris", "date": "Sat, 24 Oct 2026 22:55:18 GMT"}
    assert careerjet.identifiant(job) == careerjet.identifiant(dict(job))
    autre = dict(job, company="Y")
    assert careerjet.identifiant(job) != careerjet.identifiant(autre)


def test_nettoyer_html():
    assert careerjet.nettoyer_html(" un projet <b>data</b>   <b>science</b> &amp; IA ") == "un projet data science & IA"
    assert careerjet.nettoyer_html(None) is None


def test_html_en_texte_garde_les_paragraphes():
    page = ("<p><b>Job Description</b></p><p>En tant que   stagiaire&nbsp;:</p>"
            "<ul><li>Python</li><li>Deep learning</li></ul><p>Bac +5<br>Anglais</p>")
    assert careerjet.html_en_texte(page) == (
        "Job Description\n\nEn tant que stagiaire :\n\n• Python\n• Deep learning\n\nBac +5\nAnglais")
    assert careerjet.html_en_texte("<p></p>") is None


def test_convertir_date():
    assert careerjet.convertir_date("Fri, 23 Oct 2026 22:45:57 GMT") == "2026-10-23"
    assert careerjet.convertir_date("n'importe quoi") is None
    assert careerjet.convertir_date(None) is None
