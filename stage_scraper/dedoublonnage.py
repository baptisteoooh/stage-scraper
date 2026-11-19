"""Dédoublonnage : repère la même offre vue plusieurs fois (même site ou sites différents).

Deux offres sont considérées comme identiques si :
- même entreprise (après nettoyage : « Johnson & Johnson » = « J&J » grâce aux alias) ;
- titres très proches (une fois retirés « stage », « (H/F) », les dates...) ;
- lieux compatibles (pas deux départements différents).

La première offre vue reste l'originale ; les suivantes pointent vers elle (`doublon_de`)
et ne sont ni notées par l'IA ni affichées en double.
"""
from difflib import SequenceMatcher

from .prefiltre import MOIS, analyser_lieu, entreprise_suivie
from .texte import normaliser

SEUIL_SIMILARITE = 0.85   # ressemblance des titres, lettre à lettre
SEUIL_MOTS_COMMUNS = 0.75  # part de mots en commun (« AI Data Analyst » ≠ « Data Analyst »)

# Mots qui ne changent pas le poste : on les retire avant de comparer les titres.
MOTS_NEUTRES = {
    "stage", "stages", "stagiaire", "stagiaires", "intern", "internship", "interns", "cdd",
    "h", "f", "x", "m", "nb", "hf", "fh", "mf", "fm", "e", "le", "la", "les", "de", "du", "des",
    "d", "l", "en", "et", "a", "au", "the", "of", "and", "in", "for", "mois", "months", "month",
    "paris", "france", "idf", "junior", "jr",
} | set(MOIS)
MOTS_SOCIETE = {"sas", "sa", "sarl", "inc", "ltd", "gmbh", "france", "group", "groupe", "co", "llc"}


def cle_entreprise(nom: str | None, config: dict) -> str:
    """Nom d'entreprise comparable : nom officiel si c'est une entreprise suivie, sinon nom nettoyé."""
    suivie = entreprise_suivie(nom, config)
    if suivie:
        return normaliser(suivie["nom"])
    return " ".join(m for m in normaliser(nom).split() if m not in MOTS_SOCIETE)


def cle_titre(titre: str | None) -> str:
    """'Stage - Data Scientist (H/F) - janvier 2027' -> 'data scientist'."""
    mots = [m for m in normaliser(titre).split() if m not in MOTS_NEUTRES and not m.isdigit()]
    return " ".join(_singulier(m) for m in mots)


def _singulier(mot: str) -> str:
    """'engineers' -> 'engineer' (approximatif, suffit pour comparer deux titres)."""
    return mot[:-1] if len(mot) > 3 and mot.endswith("s") and not mot.endswith("ss") else mot


def empreinte(offre: dict, config: dict) -> str:
    return f"{cle_entreprise(offre.get('entreprise'), config)}|{cle_titre(offre.get('titre'))}"


def titres_proches(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    mots_a, mots_b = set(a.split()), set(b.split())
    if len(mots_a & mots_b) / len(mots_a | mots_b) < SEUIL_MOTS_COMMUNS:
        return False
    return SequenceMatcher(None, " ".join(sorted(mots_a)), " ".join(sorted(mots_b))).ratio() >= SEUIL_SIMILARITE


def trouver_original(conn, offre: dict, cle: str, config: dict) -> int | None:
    """Identifiant de l'offre originale dont `offre` est un doublon, ou None."""
    entreprise, titre = cle.split("|", 1)
    if not entreprise or not titre:
        return None  # sans entreprise ni titre exploitable, on ne prend pas de risque
    candidates = conn.execute(
        "SELECT id, empreinte, departement, lieu FROM offres "
        # une offre expirée ne sert pas d'original : si elle réapparaît ailleurs, c'est une nouvelle annonce
        "WHERE empreinte LIKE ? ESCAPE '\\' AND doublon_de IS NULL AND expiration IS NULL AND id < ? ORDER BY id",
        (_echapper_like(entreprise) + "|%", offre["id"]),
    ).fetchall()
    lieu_offre = analyser_lieu(offre, config["criteres"]["lieu"])
    for candidate in candidates:
        if not titres_proches(titre, candidate["empreinte"].split("|", 1)[1]):
            continue
        if not lieux_compatibles(lieu_offre, analyser_lieu(dict(candidate), config["criteres"]["lieu"])):
            continue  # même poste dans deux villes différentes : deux offres distinctes
        return candidate["id"]
    return None


def lieux_compatibles(a: tuple, b: tuple) -> bool:
    """a et b : (statut, département) renvoyés par analyser_lieu."""
    (statut_a, dep_a), (statut_b, dep_b) = a, b
    if dep_a and dep_b:
        return dep_a == dep_b
    return "vague" in (statut_a, statut_b) or statut_a == statut_b


def _echapper_like(texte: str) -> str:
    antislash = chr(92)
    return texte.replace(antislash, antislash * 2).replace("%", antislash + "%").replace("_", antislash + "_")
