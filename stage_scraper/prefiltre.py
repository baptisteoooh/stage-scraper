"""Pré-filtre : écarte les offres hors critères avant tout appel à l'IA (pour économiser).

Règles (toutes réglables dans config.yaml) :
- contrat exclu dans le titre (alternance, CDI, VIE, PFE...). Une offre « stage ou
  alternance » est gardée, sauf pour les stages de fin d'études (toujours exclus) ;
- poste non technique dans le titre (marketing, commercial, sales...) ;
- lieu hors Île-de-France (les lieux vagues comme « France » ou « Remote » sont gardés) ;
- offre trop ancienne ;
- durée hors critères (6 mois sec : gardé seulement chez une entreprise suivie, « à négocier ») ;
- date de début hors de la fenêtre (ex. « janvier 2027 » dans le titre).

Une offre douteuse est gardée : c'est l'IA qui tranchera. On n'exclut que sur des
indices nets (le titre, ou une phrase explicite de la description).
"""
import calendar
import re
from datetime import date, datetime, timedelta

from .texte import contient, contient_un, normaliser, sans_accents

# Expressions qui désignent un stage de fin d'études : exclu même si le titre dit « stage ».
FIN_ETUDES = ("stage de fin d'études", "PFE", "projet de fin d'études", "end of studies internship",
              "fin d'études", "fin d'étude", "end of studies", "end-of-studies", "graduation internship",
              "final year internship", "final-year internship")
MOTS_STAGE = ("stage", "stages", "stagiaire", "intern", "internship", "interns")

MOIS = {
    "janvier": 1, "janv": 1, "jan": 1, "january": 1,
    "fevrier": 2, "fevr": 2, "fev": 2, "february": 2, "feb": 2,
    "mars": 3, "march": 3, "mar": 3,
    "avril": 4, "avr": 4, "april": 4, "apr": 4,
    "mai": 5, "may": 5,
    "juin": 6, "june": 6, "jun": 6,
    "juillet": 7, "juil": 7, "july": 7, "jul": 7,
    "aout": 8, "august": 8, "aug": 8,
    "septembre": 9, "sept": 9, "sep": 9, "september": 9,
    "octobre": 10, "oct": 10, "october": 10,
    "novembre": 11, "nov": 11, "november": 11,
    "decembre": 12, "dec": 12, "december": 12,
}
_MOIS = "|".join(sorted(MOIS, key=len, reverse=True))
RE_MOIS_ANNEE = re.compile(rf"\b({_MOIS})\b(?:\s+(?:{_MOIS})\b)?\s+(20\d\d)\b")
RE_DEBUT_DESCRIPTION = re.compile(
    rf"\b(?:a partir d[eu]?|des|debut(?: du stage)?|date de debut|demarrage|prise de poste|"
    rf"start(?:ing)?(?: date)?|beginning|available from|commencant)\s+(?:(?:en|le|in|of|mi|early|mid|"
    rf"debut)\s+)*({_MOIS})\b(?:\s+(20\d\d))?")

_NOMBRE = r"(\d{1,2}(?:[.,]5)?)"
RE_DUREE_PLAGE = re.compile(rf"{_NOMBRE}\s*(?:a|-|–|ou|to)\s*{_NOMBRE}\s*(?:mois|months?)\b")
RE_DUREE = re.compile(rf"{_NOMBRE}\s*-?\s*(?:mois|months?)\b")
# Dans la description, la durée doit suivre un mot qui l'annonce (pour ignorer « depuis 6 mois »).
RE_ANNONCE_DUREE = re.compile(r"(?:stage|internship|duree|duration|mission|contrat|cdd|periode|"
                              r"pour une duree|pendant|length)[^.\n]{0,30}?$")
RE_SAINT = re.compile(r"\b(?:St|Ste)[- ](?=[A-Z])")
RE_CODE_POSTAL = re.compile(r"(?<!\d)(\d{5})(?!\d)")
RE_DEPARTEMENT = re.compile(r"\((\d{2})\)|(?:^|\s|-)(\d{2})(?:\s|$)")
LIEUX_VAGUES = re.compile(r"^(?:france|remote|teletravail|full remote|hybride|anywhere|europe|emea|"
                          r"plusieurs lieux|multiple locations|\d+ locations?|\d+ lieux|"
                          r"france home based|remote france|france remote)$")


def verifier(offre: dict, config: dict, aujourd_hui: date | None = None) -> tuple[str | None, dict]:
    """Renvoie (raison de l'exclusion ou None si l'offre est gardée, champs détectés à enregistrer)."""
    aujourd_hui = aujourd_hui or date.today()
    criteres, exclusions = config["criteres"], config["exclusions"]
    titre = offre.get("titre") or ""
    detectes: dict = {}

    # 1. Contrat
    terme = contient_un(titre, exclusions.get("contrats")) or contient_un(offre.get("type_contrat"), exclusions.get("contrats"))
    if terme:
        if contient_un(terme, FIN_ETUDES) or not contient_un(titre, MOTS_STAGE):
            return f"contrat : {terme}", detectes
    if contient_un(titre, FIN_ETUDES):
        return f"contrat : {contient_un(titre, FIN_ETUDES)}", detectes

    # 2. Poste non technique, ou niveau trop élevé (sauf si le titre parle de stage)
    terme = contient_un(titre, exclusions.get("postes"))
    if terme:
        return f"poste : {terme}", detectes
    terme = contient_un(titre, exclusions.get("niveaux"))
    if terme and not contient_un(titre, MOTS_STAGE):
        return f"niveau : {terme}", detectes

    # 3. Lieu
    statut, departement = analyser_lieu(offre, criteres["lieu"])
    if departement and not offre.get("departement"):
        detectes["departement"] = departement
    if statut == "hors" and not est_full_remote(offre):
        return f"lieu : {offre.get('lieu')} (hors Île-de-France)", detectes

    # 4. Ancienneté
    publication = _date(offre.get("date_publication"))
    limite = aujourd_hui - timedelta(days=config["general"].get("anciennete_max_jours", 90))
    if publication and publication < limite:
        return f"trop ancienne (publiée le {publication.isoformat()})", detectes

    # 5. Durée
    duree = analyser_duree(titre, offre.get("description"))
    if duree:
        texte, minimum, maximum = duree
        if not offre.get("duree"):
            detectes["duree"] = texte
        if not offre.get("duree_mois"):
            detectes["duree_mois"] = maximum
        raison = juger_duree(minimum, maximum, criteres["duree"], entreprise_suivie(offre.get("entreprise"), config))
        if raison:
            return raison, detectes

    # 6. Date de début
    debut = analyser_debut(titre, offre.get("description"), aujourd_hui)
    if debut:
        if not offre.get("date_debut"):
            detectes["date_debut"] = debut.isoformat()
        dates = criteres["dates"]
        dernier_jour = debut.replace(day=calendar.monthrange(debut.year, debut.month)[1])
        if debut > _date(dates["debut_au_plus_tard"]) or dernier_jour < _date(dates["debut_au_plus_tot"]):
            return f"début : {_nom_mois(debut)} (hors de la fenêtre avril-mai)", detectes

    return None, detectes


# --------------------------------------------------------------------------- lieu

def analyser_lieu(offre: dict, reglages_lieu: dict) -> tuple[str, str | None]:
    """('idf' | 'hors' | 'vague', département détecté)."""
    departements = [str(d) for d in reglages_lieu["departements"]]
    departement = offre.get("departement")
    lieu = RE_SAINT.sub("Saint-", offre.get("lieu") or "")  # « St-Ouen » -> « Saint-Ouen »
    if not departement:
        code = RE_CODE_POSTAL.search(lieu)
        if code and not code.group(1).startswith(("97", "98")):
            departement = code.group(1)[:2]
    if departement:
        return ("idf" if departement in departements else "hors"), departement
    # Ville connue avant les numéros : « Paris 13 » est un arrondissement, pas le département 13.
    if contient_un(lieu, reglages_lieu.get("villes")):
        return "idf", None
    numero = RE_DEPARTEMENT.search(lieu)
    if numero:
        departement = numero.group(1) or numero.group(2)
        return ("idf" if departement in departements else "hors"), departement
    if not lieu.strip() or LIEUX_VAGUES.match(normaliser(lieu)):
        return "vague", None
    return "hors", None


def est_full_remote(offre: dict) -> bool:
    return contient_un(" ".join(filter(None, [offre.get("teletravail"), offre.get("lieu")])),
                       ["full remote", "télétravail complet", "100% télétravail", "fully remote"]) is not None


# --------------------------------------------------------------------------- durée

def analyser_duree(titre: str, description: str | None) -> tuple[str, float, float] | None:
    """('3 à 6 mois', 3, 6) d'après le titre, sinon d'après une phrase explicite de la description."""
    trouve = _duree_dans(titre, annonce_obligatoire=False)
    if trouve is None and description:
        trouve = _duree_dans(description, annonce_obligatoire=True)
    return trouve


def _duree_dans(texte: str, annonce_obligatoire: bool):
    bas = sans_accents(texte).lower()
    for motif in (RE_DUREE_PLAGE, RE_DUREE):
        for resultat in motif.finditer(bas):
            if annonce_obligatoire and not RE_ANNONCE_DUREE.search(bas[max(0, resultat.start() - 40):resultat.start()]):
                continue
            nombres = [float(n.replace(",", ".")) for n in resultat.groups()]
            if not all(0 < n <= 12 for n in nombres):
                continue
            minimum, maximum = min(nombres), max(nombres)
            texte_duree = resultat.group(0).strip()
            return texte_duree, minimum, maximum
    return None


def juger_duree(minimum: float, maximum: float, reglages: dict, suivie: dict | None) -> str | None:
    """Raison de l'exclusion, ou None si la durée convient (ou est à négocier)."""
    min_mois, max_mois = reglages["min_mois"], reglages["max_mois"]
    if maximum < min_mois:
        return f"durée : {_mois(maximum)} (trop court)"
    if maximum <= max_mois:
        return None
    if minimum < maximum:  # une plage, ex. « 3 à 6 mois » ou « 4 à 6 mois »
        return None if minimum <= max_mois and maximum <= 6 else f"durée : {_mois(minimum)} à {_mois(maximum)}"
    # durée fixe trop longue
    if maximum <= 6 and suivie and reglages.get("six_mois_entreprise_suivie") == "a_negocier":
        return None  # « à négocier » : l'IA la rangera dans cette section
    return f"durée : {_mois(maximum)}"


def _mois(n: float) -> str:
    return f"{n:g} mois"


# --------------------------------------------------------------------------- date de début

def analyser_debut(titre: str, description: str | None, aujourd_hui: date) -> date | None:
    """1er jour du mois de début : un « mois année » du titre, ou une phrase explicite de la description."""
    trouve = RE_MOIS_ANNEE.search(normaliser(titre))
    if trouve:
        return date(int(trouve.group(2)), MOIS[trouve.group(1)], 1)
    if description:
        trouve = RE_DEBUT_DESCRIPTION.search(normaliser(description))
        if trouve:
            mois = MOIS[trouve.group(1)]
            annee = int(trouve.group(2)) if trouve.group(2) else (
                aujourd_hui.year if mois >= aujourd_hui.month else aujourd_hui.year + 1)
            return date(annee, mois, 1)
    return None


def _nom_mois(jour: date) -> str:
    noms = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
            "septembre", "octobre", "novembre", "décembre"]
    return f"{noms[jour.month - 1]} {jour.year}"


# --------------------------------------------------------------------------- entreprises suivies

def entreprise_suivie(nom: str | None, config: dict) -> dict | None:
    """L'entrée de `entreprises_suivies` correspondant à ce nom (ou à un de ses alias), sinon None."""
    cle = normaliser(nom)
    if not cle:
        return None
    for entreprise in config.get("entreprises_suivies", []):
        for variante in [entreprise["nom"], *entreprise.get("alias", [])]:
            v = normaliser(variante)
            if cle == v or cle.startswith(v + " "):
                return entreprise
    return None


def _date(valeur) -> date | None:
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    try:
        return date.fromisoformat(str(valeur)[:10]) if valeur else None
    except ValueError:
        return None
