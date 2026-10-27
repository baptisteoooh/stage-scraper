"""Offres publiées avec Ashby (Doctolib, ...).

Ashby fournit une API publique et documentée pour afficher les offres sur le site
de l'entreprise : https://api.ashbyhq.com/posting-api/job-board/<id>
Une seule requête renvoie toutes les offres, avec leur description complète.

On ne garde que les stages et les CDD : le reste (CDI, freelance...) est écarté ici.
"""
import requests

from ...offre import nouvelle_offre
from ..google_jobs import detecter_contrat

URL = "https://api.ashbyhq.com/posting-api/job-board/{id}"
USER_AGENT = "StageScraper/1.0 (outil personnel de recherche de stage)"

# employmentType d'Ashby -> notre type de contrat
CONTRATS = {"Intern": "stage", "Temporary": "cdd"}
TELETRAVAIL = {"Hybrid": "hybride", "Remote": "télétravail complet"}


def collecter(entreprise: dict) -> list[dict]:
    identifiant = entreprise["carrieres"]["id"]
    reponse = requests.get(URL.format(id=identifiant), params={"includeCompensation": "true"},
                           headers={"User-Agent": USER_AGENT}, timeout=30)
    reponse.raise_for_status()
    offres = []
    for job in reponse.json().get("jobs", []):
        if job.get("isListed") is False:
            continue
        offre = convertir(job, entreprise["nom"], identifiant)
        if offre["type_contrat"]:
            offres.append(offre)
    return offres


def convertir(job: dict, entreprise: str, identifiant: str) -> dict:
    """Transforme une offre Ashby en offre au format commun."""
    titre = job["title"].strip()
    adresse = (job.get("address") or {}).get("postalAddress") or {}
    code_postal = adresse.get("postalCode") or ""
    return nouvelle_offre(
        source="carrieres",
        source_id=f"ashby:{identifiant}:{job['id']}",
        titre=titre,
        entreprise=entreprise,
        type_contrat=CONTRATS.get(job.get("employmentType")) or detecter_contrat(titre),
        lieu=lieu(job, adresse),
        departement=code_postal[:2] if adresse.get("addressCountry") == "France" and code_postal else None,
        teletravail=TELETRAVAIL.get(job.get("workplaceType")),
        date_publication=(job.get("publishedAt") or "")[:10] or None,
        gratification=gratification(job),
        lien=job.get("jobUrl"),
        description=(job.get("descriptionPlain") or "").strip() or None,
        site_origine="Ashby",
    )


def lieu(job: dict, adresse: dict) -> str | None:
    """'Levallois-Perret, Ile-de-France, France', ou à défaut le lieu affiché par Ashby."""
    morceaux = [adresse.get(cle) for cle in ("addressLocality", "addressRegion", "addressCountry")]
    texte = ", ".join(m for m in morceaux if m) or job.get("location")
    autres = [s.get("location") for s in job.get("secondaryLocations") or [] if s.get("location")]
    if autres:
        texte = f"{texte} (aussi : {', '.join(autres)})"
    return texte or None


def gratification(job: dict) -> str | None:
    """Résumé de la rémunération, quand l'entreprise choisit de l'afficher."""
    compensation = job.get("compensation") or {}
    return (compensation.get("compensationTierSummary")
            or compensation.get("scrapeableCompensationSalarySummary") or None)
