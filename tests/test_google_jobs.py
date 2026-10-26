"""Tests de la source Google Jobs, sur une vraie réponse SerpApi enregistrée (aucun appel réseau)."""
import json
from datetime import date
from pathlib import Path

from stage_scraper.offre import CHAMPS, date_depuis_texte_relatif
from stage_scraper.sources import google_jobs

EXEMPLE = Path(__file__).parent / "donnees" / "google_jobs_exemple.json"
JOUR = date(2026, 10, 26)


def charger_offres():
    jobs = json.loads(EXEMPLE.read_text(encoding="utf-8"))["jobs_results"]
    return [google_jobs.convertir(job, JOUR) for job in jobs]


def test_toutes_les_offres_sont_converties():
    offres = charger_offres()
    assert len(offres) == 10
    for offre in offres:
        assert set(offre) == set(CHAMPS)
        assert offre["source"] == "google_jobs"
        assert offre["titre"] and offre["source_id"] and offre["lien"]


def test_premiere_offre():
    offre = charger_offres()[0]
    assert offre["titre"] == "Stage Data Science IA & Machine Learning H/F"
    assert offre["entreprise"] == "Elis"
    assert offre["lieu"] == "Puteaux"
    assert offre["site_origine"] == "Hellowork"
    assert offre["type_contrat"] == "stage"
    assert offre["date_publication"] == "2026-10-23"           # "il y a 3 jours"
    assert offre["gratification"] == "10 k € à 15 k € par an"
    assert offre["source_id"] == "_B8zQ5NY6vXPU0t4AAAAAA=="    # htidocid de Google
    assert "utm_" not in offre["lien"]


def test_stage_detecte_par_le_titre():
    # Offre Thales : extensions "À plein temps" seulement, mais "STAGE" dans le titre.
    thales = [o for o in charger_offres() if o["entreprise"] == "Thales"][0]
    assert thales["type_contrat"] == "stage"


def test_detecter_contrat():
    assert google_jobs.detecter_contrat("Stages - Ingénieur Application clinique H/F") == "stage"
    assert google_jobs.detecter_contrat("Stagiaire Ingénierie d'Affaires") == "stage"
    assert google_jobs.detecter_contrat("Machine Learning Intern") == "stage"
    assert google_jobs.detecter_contrat("Ingénieur data - CDD 4 mois") == "cdd"
    assert google_jobs.detecter_contrat("Internal Audit Manager") is None


def test_identifiants_uniques():
    ids = [o["source_id"] for o in charger_offres()]
    assert len(ids) == len(set(ids))


def test_dates_relatives():
    assert date_depuis_texte_relatif("il y a 3 jours", JOUR) == "2026-10-23"
    assert date_depuis_texte_relatif("il y a 2 semaines", JOUR) == "2026-10-12"
    assert date_depuis_texte_relatif("il y a 5 heures", JOUR) == "2026-10-26"
    assert date_depuis_texte_relatif("il y a un mois", JOUR) == "2026-09-26"
    assert date_depuis_texte_relatif("il y a plus de 30 jours", JOUR) == "2026-09-26"
    assert date_depuis_texte_relatif("3 days ago", JOUR) == "2026-10-23"
    assert date_depuis_texte_relatif("30+ days ago", JOUR) == "2026-09-26"
    assert date_depuis_texte_relatif("hier", JOUR) == "2026-10-25"
    # Une durée n'est pas une date de publication.
    assert date_depuis_texte_relatif("Stage 6 mois", JOUR) is None
    assert date_depuis_texte_relatif("À plein temps", JOUR) is None


def test_rotation_des_requetes():
    requetes = [f"r{i}" for i in range(13)]
    jour1 = google_jobs.choisir_requetes(requetes, 7, JOUR)
    jour2 = google_jobs.choisir_requetes(requetes, 7, date(2026, 10, 27))
    assert len(jour1) == 7 and len(set(jour1)) == 7
    assert set(jour1) | set(jour2) == set(requetes)   # en 2 jours, toutes les requêtes passent
    assert google_jobs.choisir_requetes(requetes, 20, JOUR) == requetes


def test_nettoyer_lien():
    lien = "https://www.hellowork.com/fr-fr/emplois/1.html?utm_source=google&id=5"
    assert google_jobs.nettoyer_lien(lien) == "https://www.hellowork.com/fr-fr/emplois/1.html?id=5"


def test_cle_masquee_dans_les_erreurs():
    erreur = Exception("Max retries exceeded with url: /search.json?q=x&api_key=SECRET123")
    assert "SECRET123" not in google_jobs._masquer(erreur, "SECRET123")
