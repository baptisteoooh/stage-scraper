"""Décisions sur une offre à trier, sans interface : Je candidate, Pas pour moi, Plus tard (et leur annulation).

Utilisé par l'appli Streamlit et par le site (stage_scraper/web). Chaque décision renvoie un petit
dictionnaire qui suffit à l'annuler.
"""
from . import requetes

ACTIONS = ("candidate", "ecarte", "plus_tard", "remettre")
TEXTES = {"candidate": "ajoutée à Ma sélection", "ecarte": "écartée",
          "plus_tard": "rangée dans « Plus tard »", "remettre": "remise dans les offres à trier"}
RAISONS = ["Trop long (6 mois)", "Commercial / pas technique", "Pas mon domaine", "Dates incompatibles",
           "Hors Île-de-France", "Entreprise"]


def appliquer(conn, offre_id: int, action: str) -> dict:
    """Applique la décision et renvoie de quoi l'annuler. Lève ValueError si l'offre ou l'action est inconnue."""
    if action not in ACTIONS:
        raise ValueError(f"action inconnue : {action}")
    o = requetes.offre(conn, offre_id)
    if o is None:
        raise ValueError(f"offre inconnue : {offre_id}")
    candidature_id = None
    if action == "candidate":
        candidature_id = requetes.creer_candidature(conn, offre_id=offre_id)
    elif action == "ecarte":
        requetes.marquer_pas_interesse(conn, offre_id)
    elif action == "plus_tard" and not o["favori"] or action == "remettre" and o["favori"]:
        requetes.basculer_favori(conn, offre_id)
    requetes.marquer_vue(conn, offre_id)
    return {"action": action, "offre_id": offre_id, "titre": o["titre"], "entreprise": o["entreprise"],
            "candidature_id": candidature_id}


def annuler(conn, d: dict) -> None:
    """Défait une décision renvoyée par appliquer()."""
    if d["action"] == "candidate" and d.get("candidature_id"):
        requetes.supprimer_candidature(conn, d["candidature_id"])
    elif d["action"] == "ecarte":
        requetes.annuler_pas_interesse(conn, d["offre_id"])
    elif d["action"] in ("plus_tard", "remettre"):
        requetes.basculer_favori(conn, d["offre_id"])
