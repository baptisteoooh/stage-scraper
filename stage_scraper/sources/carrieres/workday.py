"""Offres publiées avec Workday (Medtronic, Abbott, Philips, ...).

Les pages carrières Workday (https://<groupe>.wdN.myworkdayjobs.com/<site>) chargent
leurs offres depuis un JSON public. On interroge ce même JSON, comme le fait la page :
- POST .../wday/cxs/<groupe>/<site>/jobs   liste des offres (20 par page), avec filtres ;
- GET  .../wday/cxs/<groupe>/<site><chemin> fiche détaillée d'une offre.

Chaque groupe nomme ses filtres différemment (locationCountry, Location_Country,
locationHierarchy1...). On les découvre automatiquement :
- France : la valeur « France » d'un filtre pays. Sans filtre pays, on combine les lieux
  contenant « France » et une recherche du mot « France » (certains groupes écrivent
  leurs lieux sans le pays : « Buc », « Toulouse ») ;
- type de contrat : les valeurs du filtre workerSubType qui ressemblent à stage ou CDD.

Dans config.yaml : carrieres: {outil: workday, url: https://abbott.wd5.myworkdayjobs.com/abbottcareers}
"""
import logging
import re
import time
from urllib.parse import urlparse

import requests

from ...offre import nouvelle_offre
from ..careerjet import html_en_texte
from ..google_jobs import detecter_contrat

USER_AGENT = "StageScraper/1.0 (outil personnel de recherche de stage)"
PAR_PAGE = 20          # maximum accepté par Workday
PAGES_MAX = 10         # au plus 200 offres par recherche
DELAI_SECONDES = 1
RE_FRANCE = re.compile(r"\bfrance\b|\(fr\)|^fra\d", re.IGNORECASE)

log = logging.getLogger(__name__)


class ErreurWorkday(ValueError):
    """Adresse mal formée, trop de requêtes..."""


def collecter(entreprise: dict) -> list[dict]:
    api = adresse_api(entreprise["carrieres"]["url"])
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    filtres = rechercher(session, api, {}, limite=1)["facets"]
    recherches_france = recherches_en_france(filtres)

    # Offres stage / CDD selon le filtre « type de contrat », quand il existe.
    contrat_par_offre = {}
    for type_contrat, valeurs in filtres_contrat(filtres).items():
        for filtre_france, mot_cle in recherches_france:
            for job in toutes_les_offres(session, api, {**filtre_france, **valeurs}, mot_cle):
                contrat_par_offre.setdefault(job["externalPath"], type_contrat)

    # Toutes les offres en France, pour rattraper les stages mal classés (repérés par leur titre).
    retenues = {}
    for filtre_france, mot_cle in recherches_france:
        for job in toutes_les_offres(session, api, filtre_france, mot_cle):
            type_contrat = contrat_par_offre.get(job["externalPath"]) or detecter_contrat(job["title"])
            if type_contrat:
                retenues.setdefault(job["externalPath"], (job, type_contrat))

    offres = []
    for job, type_contrat in retenues.values():
        time.sleep(DELAI_SECONDES)
        try:
            detail = session.get(api + job["externalPath"], timeout=30)
            detail.raise_for_status()
            info = detail.json()["jobPostingInfo"]
        except (requests.RequestException, ValueError, KeyError) as e:
            log.info("    fiche détaillée illisible (%s), offre gardée avec les infos de la liste", e)
            info = {}
        offres.append(convertir(job, info, type_contrat, entreprise["nom"], api))
    return offres


def adresse_api(url: str) -> str:
    """'https://abbott.wd5.myworkdayjobs.com/fr-FR/abbottcareers' -> '.../wday/cxs/abbott/abbottcareers'."""
    morceaux = urlparse(url)
    hote = morceaux.hostname or ""
    chemin = [p for p in morceaux.path.split("/") if p and not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", p)]
    if not hote.endswith("myworkdayjobs.com") or not chemin:
        raise ErreurWorkday(f"adresse Workday non reconnue : {url}")
    return f"https://{hote}/wday/cxs/{hote.split('.')[0]}/{chemin[0]}"


def rechercher(session, api: str, filtres: dict, limite: int = PAR_PAGE, decalage: int = 0,
               mot_cle: str = "") -> dict:
    reponse = session.post(api + "/jobs", timeout=30, json={
        "appliedFacets": filtres, "limit": limite, "offset": decalage, "searchText": mot_cle,
    })
    if reponse.status_code == 429:
        raise ErreurWorkday("trop de requêtes (erreur 429)")
    reponse.raise_for_status()
    return reponse.json()


def toutes_les_offres(session, api: str, filtres: dict, mot_cle: str = "") -> list[dict]:
    offres = []
    for page in range(PAGES_MAX):
        time.sleep(DELAI_SECONDES)
        donnees = rechercher(session, api, filtres, decalage=page * PAR_PAGE, mot_cle=mot_cle)
        offres.extend(donnees.get("jobPostings", []))
        if len(offres) >= (donnees.get("total") or 0) or not donnees.get("jobPostings"):
            break
    return offres


def _parcourir(filtres: list[dict]):
    """Renvoie (nom du filtre, valeurs) pour chaque filtre, y compris ceux rangés dans un groupe."""
    for filtre in filtres:
        valeurs = filtre.get("values") or []
        if valeurs and "facetParameter" in valeurs[0]:
            yield from _parcourir(valeurs)
        else:
            yield filtre.get("facetParameter"), valeurs


def recherches_en_france(filtres: list[dict]) -> list[tuple[dict, str]]:
    """Liste de (filtres, mot-clé) qui, ensemble, couvrent les offres en France."""
    trouve = trouver_filtre_france(filtres)
    if "pays" in trouve:
        return [(trouve["pays"], "")]
    recherches = [(trouve["lieux"], "")] if "lieux" in trouve else []
    return recherches + [({}, "France")]


def trouver_filtre_france(filtres: list[dict]) -> dict:
    """{'pays': {filtre: [id]}} si un filtre pays existe, sinon {'lieux': {...}} (lieux contenant « France »)."""
    lieux_en_france = {}
    for nom, valeurs in _parcourir(filtres):
        for valeur in valeurs:
            libelle = (valeur.get("descriptor") or "").strip()
            if libelle.casefold() == "france":
                return {"pays": {nom: [valeur["id"]]}}  # filtre pays : le plus simple
            if nom == "locations" and RE_FRANCE.search(libelle):
                lieux_en_france.setdefault(nom, []).append(valeur["id"])
    return {"lieux": lieux_en_france} if lieux_en_france else {}


def filtres_contrat(filtres: list[dict]) -> dict[str, dict]:
    """{'stage': {'workerSubType': [ids]}, 'cdd': {...}} d'après les libellés du filtre type de contrat."""
    resultat: dict[str, list] = {}
    for nom, valeurs in _parcourir(filtres):
        if nom != "workerSubType":
            continue
        for valeur in valeurs:
            type_contrat = contrat_depuis_libelle(valeur.get("descriptor") or "")
            if type_contrat:
                resultat.setdefault(type_contrat, []).append(valeur["id"])
    return {type_contrat: {"workerSubType": ids} for type_contrat, ids in resultat.items()}


def contrat_depuis_libelle(libelle: str) -> str | None:
    """'Intern (Fixed Term)' -> stage ; 'Temporary (Fixed Term)' -> cdd ; 'Apprentice' -> None."""
    bas = libelle.lower()
    if "apprenti" in bas:
        return None  # alternance : exclue
    if re.search(r"\bintern\b|trainee|stagi|co-op|student|\bstage\b", bas) and "non-intern" not in bas:
        return "stage"
    if re.search(r"temporary|fixed term|limited term|\bcdd\b", bas) and "agency" not in bas:
        return "cdd"
    return None


def convertir(job: dict, info: dict, type_contrat: str, entreprise: str, api: str) -> dict:
    """Assemble une offre à partir de la ligne de la liste et de la fiche détaillée."""
    groupe = api.split("/wday/cxs/")[1].split("/")[0]
    identifiant = info.get("jobReqId") or (job.get("bulletFields") or [job["externalPath"]])[0]
    site = api.split("/wday/cxs/")[0] + "/" + api.rsplit("/", 1)[1]
    return nouvelle_offre(
        source="carrieres",
        source_id=f"workday:{groupe}:{identifiant}",
        titre=(info.get("title") or job["title"]).strip(),
        entreprise=entreprise,
        type_contrat=type_contrat,
        lieu=info.get("location") or job.get("locationsText"),
        teletravail=info.get("remoteType"),
        date_publication=info.get("startDate"),
        lien=info.get("externalUrl") or site + job["externalPath"],
        description=html_en_texte(info.get("jobDescription")),
        site_origine="Workday",
    )
