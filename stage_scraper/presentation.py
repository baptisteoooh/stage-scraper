"""Mise en forme des offres, commune à l'appli Streamlit et au site : lieu court, date de début lisible,
ancienneté de l'annonce, extrait de la description, niveau de la note."""
import re
from datetime import date

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]


def niveau_note(score) -> str:
    if score is None:
        return "attente"
    return "haute" if score >= 8 else "moyenne" if score >= 5 else "basse"


def lieu_court(lieu: str | None) -> str | None:
    """« Levallois-Perret, Ile-de-France, France » -> « Levallois-Perret »."""
    if not lieu:
        return None
    return lieu.split(",")[0].strip() or lieu


def debut_lisible(o: dict) -> str | None:
    """Date de début : « 2027-04-01 » -> « avril 2027 » ; sinon le texte trouvé par l'IA."""
    brut = o["date_debut"] or o["date_debut_ia"]
    if not brut:
        return None
    trouve = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", brut.strip())
    if trouve and 1 <= int(trouve[2]) <= 12:
        return f"{MOIS[int(trouve[2]) - 1]} {trouve[1]}"
    return brut


def anciennete(date_publication: str | None, aujourd_hui: date | None = None) -> str | None:
    if not date_publication:
        return None
    try:
        jours = ((aujourd_hui or date.today()) - date.fromisoformat(date_publication[:10])).days
    except ValueError:
        return None
    if jours <= 0:
        return "publiée aujourd'hui"
    if jours == 1:
        return "publiée hier"
    return f"publiée il y a {jours} j"


def _court(texte: str | None, longueur: int = 32) -> str | None:
    if not texte:
        return None
    texte = " ".join(texte.split())
    return texte if len(texte) <= longueur else texte[:longueur - 1].rstrip() + "…"


def extrait(description: str | None, longueur: int = 480) -> str | None:
    """Début de la description, coupé proprement entre deux mots."""
    if not description:
        return None
    texte = " ".join(description.split())
    if len(texte) <= longueur:
        return texte
    coupe = texte[:longueur].rsplit(" ", 1)[0]
    return coupe.rstrip(" ,;:.-") + "…"


# Sources dont l'API ne donne qu'un extrait de la description (pas le texte complet).
SOURCES_EXTRAIT = {"careerjet"}

SECTIONS_COURTES = {"Hors santé mais intéressant": "Hors santé"}
