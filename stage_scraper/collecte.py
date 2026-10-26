"""Lance la collecte de toutes les sources actives, enregistre les offres et tient le journal."""
import logging
from datetime import datetime

from . import db
from .sources import Contexte, Resultat, google_jobs

# Sources disponibles. Pour en ajouter une : créer son module dans sources/ et l'ajouter ici.
SOURCES = {
    "google_jobs": google_jobs.collecter,
}

log = logging.getLogger(__name__)


def lancer_passage(conn, config: dict, auto: bool = False,
                   sources_demandees: list[str] | None = None,
                   max_requetes: int | None = None) -> tuple[int, list[dict]]:
    """Collecte chaque source l'une après l'autre. Renvoie (n° du passage, bilan par source)."""
    passage_id = db.nouveau_passage_id(conn)
    bilan = []

    for nom, collecter in SOURCES.items():
        if sources_demandees:
            if nom not in sources_demandees:
                continue
        elif not config["sources"].get(nom, {}).get("actif", False):
            continue

        debut = _maintenant()
        contexte = Contexte(auto=auto, explicite=bool(sources_demandees), max_requetes=max_requetes)
        try:
            resultat = collecter(config, contexte)
        except Exception as e:  # une source qui plante ne bloque pas les autres
            log.exception("La source %s a planté", nom)
            resultat = Resultat(erreurs=[f"{type(e).__name__} : {e}"])

        nb_nouvelles = db.enregistrer_offres(conn, resultat.offres, passage_id)
        db.journaliser_run(
            conn,
            passage_id=passage_id,
            date_debut=debut,
            date_fin=_maintenant(),
            declenchement="auto" if auto else "manuel",
            source=nom,
            nb_offres=len(resultat.offres),
            nb_nouvelles=nb_nouvelles,
            nb_requetes=resultat.nb_requetes,
            erreurs="\n".join(resultat.erreurs) or None,
        )
        bilan.append({
            "source": nom,
            "nb_offres": len(resultat.offres),
            "nb_nouvelles": nb_nouvelles,
            "nb_requetes": resultat.nb_requetes,
            "erreurs": resultat.erreurs,
            "message": resultat.message,
        })

    return passage_id, bilan


def _maintenant() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")
