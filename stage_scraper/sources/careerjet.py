"""Collecte des offres de stage via l'API Careerjet (v4).

Careerjet est un moteur de recherche d'offres qui regroupe de nombreux sites.
Son API est prévue pour des sites partenaires ; chaque requête doit contenir :
- la clé API (authentification Basic : clé en nom d'utilisateur, mot de passe vide) ;
- l'adresse IP et le "user agent" de l'utilisateur (ici, BAP) ;
- un en-tête Referer égal au site déclaré chez Careerjet (réglage `referer` de config.yaml).
L'adresse IP de la box doit aussi être autorisée dans l'espace partenaire Careerjet.
"""
import hashlib
import html
import logging
import re
import time
from email.utils import parsedate_to_datetime

import requests

from ..config import secret
from ..offre import nouvelle_offre
from . import Contexte, Resultat

NOM = "careerjet"
URL_RECHERCHE = "https://search.api.careerjet.net/v4/query"
URL_IP = "https://api.ipify.org"
USER_AGENT = "StageScraper/1.0 (outil personnel de recherche de stage)"

log = logging.getLogger(__name__)


class ErreurCareerjet(Exception):
    """Erreur renvoyée par Careerjet (IP non autorisée, clé refusée...)."""


def collecter(config: dict, contexte: Contexte) -> Resultat:
    reglages = config["sources"][NOM]
    cle = secret("CAREERJET_API_KEY")
    if not cle:
        return Resultat(erreurs=["CAREERJET_API_KEY manquante dans .env"])

    try:
        ip = reglages.get("ip_utilisateur") or adresse_ip_publique()
    except requests.RequestException as e:
        return Resultat(erreurs=[f"impossible de connaître l'adresse IP publique : {e}"])

    requetes = list(config["recherches"]["requetes"])
    if contexte.max_requetes is not None:
        requetes = requetes[:contexte.max_requetes]

    resultat = Resultat()
    for i, requete in enumerate(requetes):
        if i > 0:
            time.sleep(reglages.get("delai_secondes", 1))
        resultat.nb_requetes += 1
        try:
            offres = rechercher(cle, requete, reglages, ip)
        except ErreurCareerjet as e:
            resultat.erreurs.append(f"« {requete} » : {e}")
            break  # accès refusé : inutile d'insister
        except requests.RequestException as e:
            resultat.erreurs.append(f"« {requete} » : {e}")
            continue
        log.info("  « %s » : %d offre(s)", requete, len(offres))
        resultat.offres.extend(offres)

    return resultat


def adresse_ip_publique() -> str:
    """Adresse IP publique de la connexion (celle de la box)."""
    return requests.get(URL_IP, timeout=10).text.strip()


def rechercher(cle: str, requete: str, reglages: dict, ip: str) -> list[dict]:
    """Lance une recherche (1 page) et renvoie les offres normalisées."""
    params = {
        "locale_code": "fr_FR",
        "keywords": requete,
        "location": reglages.get("lieu", "Île-de-France"),
        "contract_type": reglages.get("type_contrat", "i"),  # i = stage (internship)
        "sort": "date",
        "page_size": reglages.get("offres_par_requete", 50),
        "fragment_size": 500,  # longueur de l'extrait de description
        "user_ip": ip,
        "user_agent": USER_AGENT,
    }
    reponse = requests.get(URL_RECHERCHE, params=params, auth=(cle, ""),
                           headers={"Referer": reglages["referer"], "User-Agent": USER_AGENT},
                           timeout=30)
    if reponse.status_code == 429:
        raise ErreurCareerjet("trop de requêtes (erreur 429)")
    try:
        donnees = reponse.json()
    except ValueError:
        reponse.raise_for_status()
        raise ErreurCareerjet(f"réponse illisible (HTTP {reponse.status_code})")

    if donnees.get("type") == "ERROR" or reponse.status_code >= 400:
        message = donnees.get("error") or f"HTTP {reponse.status_code}"
        if "Unauthorized access from IP" in message:
            message += " : ajoute cette adresse IP dans ton espace partenaire Careerjet"
        raise ErreurCareerjet(message)
    if donnees.get("type") != "JOBS":
        # type LOCATIONS : lieu ambigu ou inconnu, Careerjet propose des lieux au lieu de chercher
        raise ErreurCareerjet(f"lieu « {params['location']} » non reconnu par Careerjet")

    return [convertir(job) for job in donnees.get("jobs", [])]


def convertir(job: dict) -> dict:
    """Transforme une offre au format Careerjet en offre au format commun."""
    titre = (job.get("title") or "").strip()
    return nouvelle_offre(
        source=NOM,
        source_id=identifiant(job),
        titre=titre,
        entreprise=(job.get("company") or "").strip() or None,
        type_contrat="stage",  # on ne demande que des stages (contract_type = i)
        lieu=job.get("locations") or None,
        date_publication=convertir_date(job.get("date")),
        gratification=(job.get("salary") or "").strip() or None,
        lien=job.get("url"),
        description=nettoyer_html(job.get("description")),
        site_origine=(job.get("site") or "").strip() or None,
    )


def identifiant(job: dict) -> str:
    """Careerjet ne donne pas d'identifiant : on en fabrique un stable à partir de l'offre."""
    brut = "|".join(str(job.get(champ) or "").strip().lower()
                    for champ in ("title", "company", "locations", "date"))
    return hashlib.sha1(brut.encode("utf-8")).hexdigest()


def convertir_date(texte: str | None) -> str | None:
    """'Sat, 24 Oct 2026 22:55:18 GMT' -> '2026-10-24'."""
    if not texte:
        return None
    try:
        return parsedate_to_datetime(texte).date().isoformat()
    except (TypeError, ValueError):
        return None


def nettoyer_html(texte: str | None) -> str | None:
    """Retire les balises (<b>...</b>) et les espaces en trop d'un extrait."""
    if not texte:
        return None
    sans_balises = re.sub(r"<[^>]+>", "", texte)
    return re.sub(r"\s+", " ", html.unescape(sans_balises)).strip()
