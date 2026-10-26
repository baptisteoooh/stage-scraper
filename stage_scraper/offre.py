"""Format commun d'une offre, partagé par toutes les sources.

Chaque module de collecte transforme les données de son site en un dictionnaire
avec exactement ces champs, grâce à `nouvelle_offre(...)`.
"""
import re
from datetime import date, timedelta

CHAMPS = (
    "source",            # nom de la source : google_jobs, gmail_linkedin, ...
    "source_id",         # identifiant de l'offre chez la source (sert à ne pas l'enregistrer deux fois)
    "titre",
    "entreprise",
    "type_contrat",      # stage, cdd, ou None si inconnu
    "lieu",
    "departement",
    "teletravail",
    "date_publication",  # format AAAA-MM-JJ
    "duree",
    "duree_mois",
    "date_debut",
    "gratification",
    "lien",
    "description",
    "contact",
    "site_origine",      # site qui publie l'offre (HelloWork, LinkedIn, ...), quand la source est un agrégateur
)


def nouvelle_offre(**champs) -> dict:
    """Crée une offre au format commun. Les champs non fournis valent None."""
    inconnus = set(champs) - set(CHAMPS)
    if inconnus:
        raise ValueError(f"Champs inconnus : {sorted(inconnus)}")
    for obligatoire in ("source", "source_id", "titre"):
        if not champs.get(obligatoire):
            raise ValueError(f"Champ obligatoire manquant : {obligatoire}")
    return {nom: champs.get(nom) for nom in CHAMPS}


# --- Dates relatives : "il y a 3 jours", "2 weeks ago", "hier"... ---------------

_JOURS_PAR_UNITE = {
    "minute": 0, "heure": 0, "hour": 0,
    "jour": 1, "day": 1,
    "semaine": 7, "week": 7,
    "mois": 30, "month": 30,
}
_RE_FR = re.compile(r"il y a\s+(?:plus de\s+)?(\d+|une?)\s*\+?\s*(minute|heure|jour|semaine|mois)", re.I)
_RE_EN = re.compile(r"(\d+|an?)\s*\+?\s*(minute|hour|day|week|month)s?\s+ago", re.I)


def date_depuis_texte_relatif(texte: str, aujourd_hui: date | None = None) -> str | None:
    """Convertit "il y a 3 jours" en date (AAAA-MM-JJ). Renvoie None si le texte n'est pas une date."""
    aujourd_hui = aujourd_hui or date.today()
    t = texte.lower().strip()
    if t in ("aujourd'hui", "today", "just posted", "à l'instant"):
        return aujourd_hui.isoformat()
    if t in ("hier", "yesterday"):
        return (aujourd_hui - timedelta(days=1)).isoformat()
    trouve = _RE_FR.search(t) or _RE_EN.search(t)
    if not trouve:
        return None
    nombre, unite = trouve.groups()
    nombre = 1 if nombre in ("un", "une", "a", "an") else int(nombre)
    return (aujourd_hui - timedelta(days=nombre * _JOURS_PAR_UNITE[unite])).isoformat()
