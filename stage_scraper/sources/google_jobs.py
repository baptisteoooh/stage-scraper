"""Collecte des offres de Google Jobs via l'API SerpApi.

Google Jobs regroupe les offres de nombreux sites (LinkedIn, Welcome to the Jungle,
HelloWork, Indeed, JobTeaser, pages carrières...). SerpApi interroge Google à notre
place et renvoie des données propres (JSON).

Quota de l'offre gratuite : 250 recherches par mois. Pour ne jamais le dépasser :
- la source ne tourne qu'au passage automatique du matin (réglable dans config.yaml) ;
- on fait au plus `recherches_par_passage` recherches, en faisant tourner la liste
  des requêtes d'un jour à l'autre ;
- on demande à SerpApi combien de recherches il reste (appel gratuit) avant de commencer.
"""
import base64
import hashlib
import json
import logging
import re
import time
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from ..config import secret
from ..offre import date_depuis_texte_relatif, nouvelle_offre
from . import Contexte, Resultat

NOM = "google_jobs"
URL_RECHERCHE = "https://serpapi.com/search.json"
URL_COMPTE = "https://serpapi.com/account.json"
AUCUN_RESULTAT = "hasn't returned any results"  # message SerpApi quand une recherche est vide
EN_TETES = {"User-Agent": "StageScraper/1.0 (outil personnel de recherche de stage)"}

log = logging.getLogger(__name__)


def collecter(config: dict, contexte: Contexte) -> Resultat:
    reglages = config["sources"][NOM]

    if reglages.get("seulement_en_auto") and not contexte.auto and not contexte.explicite:
        return Resultat(message="ignorée en passage manuel, pour préserver le quota (seulement_en_auto)")

    cle = secret("SERPAPI_API_KEY")
    if not cle:
        return Resultat(erreurs=["SERPAPI_API_KEY manquante dans .env"])

    resultat = Resultat()
    try:
        restantes = recherches_restantes(cle)
    except requests.RequestException as e:
        return Resultat(erreurs=[f"impossible de lire le quota SerpApi : {_masquer(e, cle)}"])

    budget = min(reglages.get("recherches_par_passage", 7), restantes - reglages.get("reserve", 0))
    if contexte.max_requetes is not None:
        budget = min(budget, contexte.max_requetes)
    if budget <= 0:
        return Resultat(message=f"quota SerpApi atteint ({restantes} recherche(s) restante(s)), source sautée")

    requetes = choisir_requetes(config["recherches"]["requetes"], budget, date.today())
    log.info("Google Jobs : %d recherche(s) sur %d restante(s) ce mois-ci", len(requetes), restantes)

    for i, requete in enumerate(requetes):
        if i > 0:
            time.sleep(reglages.get("delai_secondes", 1))
        try:
            offres = rechercher(cle, requete, reglages["lieu"])
        except ErreurSerpApi as e:
            resultat.erreurs.append(f"« {requete} » : {_masquer(e, cle)}")
            break  # quota épuisé, clé refusée... inutile de continuer
        except requests.RequestException as e:
            resultat.erreurs.append(f"« {requete} » : {_masquer(e, cle)}")
            continue
        finally:
            resultat.nb_requetes += 1
        log.info("  « %s » : %d offre(s)", requete, len(offres))
        resultat.offres.extend(offres)

    return resultat


class ErreurSerpApi(Exception):
    """Erreur renvoyée par SerpApi (quota épuisé, clé invalide...)."""


def recherches_restantes(cle: str) -> int:
    """Nombre de recherches encore disponibles ce mois-ci. Cet appel ne consomme pas de quota."""
    reponse = requests.get(URL_COMPTE, params={"api_key": cle}, headers=EN_TETES, timeout=20)
    reponse.raise_for_status()
    return int(reponse.json()["plan_searches_left"])


def rechercher(cle: str, requete: str, lieu: str) -> list[dict]:
    """Lance une recherche Google Jobs (1 page = 10 offres max) et renvoie les offres normalisées."""
    params = {"engine": "google_jobs", "q": requete, "location": lieu,
              "hl": "fr", "gl": "fr", "api_key": cle}
    reponse = requests.get(URL_RECHERCHE, params=params, headers=EN_TETES, timeout=60)
    if reponse.status_code == 429:
        raise ErreurSerpApi("trop de requêtes (erreur 429)")
    donnees = reponse.json()
    erreur = donnees.get("error")
    if erreur:
        if AUCUN_RESULTAT in erreur:
            return []
        raise ErreurSerpApi(erreur)
    reponse.raise_for_status()
    aujourd_hui = date.today()
    return [convertir(job, aujourd_hui) for job in donnees.get("jobs_results", [])]


def choisir_requetes(requetes: list[str], nombre: int, jour: date) -> list[str]:
    """Choisit `nombre` requêtes en décalant le point de départ chaque jour,
    pour que toutes les requêtes soient utilisées à tour de rôle."""
    if nombre >= len(requetes):
        return list(requetes)
    debut = (jour.toordinal() * nombre) % len(requetes)
    return [requetes[(debut + i) % len(requetes)] for i in range(nombre)]


def convertir(job: dict, aujourd_hui: date) -> dict:
    """Transforme une offre au format SerpApi en offre au format commun."""
    titre = job.get("title") or job.get("job_title") or ""
    date_publication = gratification = teletravail = type_contrat = None

    for ext in job.get("extensions") or []:
        texte = ext.replace("\xa0", " ")
        bas = texte.lower()
        date_trouvee = date_depuis_texte_relatif(texte, aujourd_hui)
        if date_trouvee and not date_publication:
            date_publication = date_trouvee
        elif "€" in texte or "$" in texte or "£" in texte:
            gratification = texte
        if "télétravail" in bas or "remote" in bas:
            teletravail = "télétravail"
        if re.search(r"\bstage\b|internship", bas):
            type_contrat = "stage"
        elif re.search(r"\bcdd\b", bas) and not type_contrat:
            type_contrat = "cdd"

    if not type_contrat:
        type_contrat = detecter_contrat(titre)

    return nouvelle_offre(
        source=NOM,
        source_id=identifiant(job),
        titre=titre,
        entreprise=job.get("company_name"),
        type_contrat=type_contrat,
        lieu=job.get("location"),
        teletravail=teletravail,
        date_publication=date_publication,
        gratification=gratification,
        lien=nettoyer_lien(lien_principal(job)),
        description=job.get("description"),
        site_origine=job.get("via"),
    )


def detecter_contrat(titre: str) -> str | None:
    bas = titre.lower()
    if re.search(r"\bstages?\b|\bstagiaires?\b|\binterns?\b|internship", bas):
        return "stage"
    if re.search(r"\bcdd\b", bas):
        return "cdd"
    return None


def identifiant(job: dict) -> str:
    """Identifiant stable de l'offre chez Google (htidocid, caché dans job_id)."""
    try:
        infos = json.loads(base64.b64decode(job["job_id"] + "=="))
        if infos.get("htidocid"):
            return infos["htidocid"]
    except (KeyError, ValueError, TypeError):
        pass
    # Repli : empreinte du titre + entreprise + lieu.
    brut = f"{job.get('title')}|{job.get('company_name')}|{job.get('location')}"
    return hashlib.sha1(brut.encode("utf-8")).hexdigest()


def lien_principal(job: dict) -> str | None:
    """Lien direct vers l'offre : le site d'origine, sinon le premier lien de candidature."""
    if job.get("source_link"):
        return job["source_link"]
    options = job.get("apply_options") or []
    if options:
        return options[0].get("link")
    return job.get("share_link")


def nettoyer_lien(lien: str | None) -> str | None:
    """Retire les paramètres de suivi (utm_...) d'une adresse."""
    if not lien:
        return None
    morceaux = urlsplit(lien)
    params = [(k, v) for k, v in parse_qsl(morceaux.query, keep_blank_values=True) if not k.startswith("utm_")]
    return urlunsplit(morceaux._replace(query=urlencode(params)))


def _masquer(erreur: Exception, cle: str) -> str:
    """Les messages d'erreur réseau peuvent contenir l'adresse appelée, donc la clé : on la masque."""
    return str(erreur).replace(cle, "***")
