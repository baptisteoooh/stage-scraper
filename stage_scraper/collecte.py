"""Lance la collecte de toutes les sources actives, enregistre les offres et tient le journal."""
import logging
from datetime import datetime

from . import db, expiration
from .sources import Contexte, Resultat, careerjet, carrieres, gmail, google_jobs

# Sources disponibles. Pour en ajouter une : créer son module dans sources/ et l'ajouter ici.
SOURCES = {
    "google_jobs": google_jobs.collecter,
    "careerjet": careerjet.collecter,
    "gmail": gmail.collecter,
    "carrieres": carrieres.collecter,
}

log = logging.getLogger(__name__)


def lancer_passage(conn, config: dict, auto: bool = False,
                   sources_demandees: list[str] | None = None,
                   max_requetes: int | None = None, passage_id: int | None = None) -> tuple[int, list[dict]]:
    """Collecte chaque source l'une après l'autre. Renvoie (n° du passage, bilan par source)."""
    passage_id = passage_id or db.nouveau_passage_id(conn)
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
        retraits = expiration.retirees_du_site(conn, nom, resultat.listes_completes)
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
            "nb_expirees": retraits["expirees"],
            "nb_retablies": retraits["retablies"],
        })

    return passage_id, bilan


def _maintenant() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


# --------------------------------------------------------------------------- collecte commune (mode comptes)

# Ce qu'un ami reçoit d'une offre : ses données brutes. Jamais la note, les décisions ni les indicateurs de BAP.
COLONNES_PARTAGEES = ("source", "source_id", "titre", "entreprise", "type_contrat", "lieu", "departement", "teletravail",
                      "date_publication", "duree", "duree_mois", "date_debut", "gratification", "lien", "description",
                      "contact", "site_origine")


def importer_commune(conn, base_commune, auto: bool = False) -> tuple[int, list[dict]]:
    """Pour le compte d'un ami : reprend les offres collectées par BAP (sa base, ouverte en lecture seule) au lieu
    d'interroger les sites. Les offres retirées du site chez BAP le sont aussi chez l'ami.
    Renvoie (n° du passage, bilan) comme lancer_passage."""
    import sqlite3
    from pathlib import Path

    passage_id = db.nouveau_passage_id(conn)
    debut = _maintenant()
    erreurs, offres, retirees = [], [], []
    try:
        source = sqlite3.connect(Path(base_commune).resolve().as_uri() + "?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        try:
            for ligne in source.execute(f"SELECT {', '.join(COLONNES_PARTAGEES)}, expiration FROM offres"):
                if ligne["expiration"] == "retiree":
                    retirees.append((ligne["source"], ligne["source_id"]))
                elif not ligne["expiration"]:
                    offres.append({c: ligne[c] for c in COLONNES_PARTAGEES})
        finally:
            source.close()
    except sqlite3.Error as e:
        log.exception("Lecture des offres communes impossible")
        erreurs.append(f"offres communes illisibles ({type(e).__name__})")
    nb_nouvelles = db.enregistrer_offres(conn, offres, passage_id)
    nb_retirees = 0
    for src, src_id in retirees:
        nb_retirees += conn.execute(
            "UPDATE offres SET expiration = 'retiree', date_expiration = datetime('now', 'localtime') "
            "WHERE source = ? AND source_id = ? AND expiration IS NULL", (src, src_id)).rowcount
    conn.commit()
    db.journaliser_run(conn, passage_id=passage_id, date_debut=debut, date_fin=_maintenant(),
                       declenchement="auto" if auto else "manuel", source="commune", nb_offres=len(offres),
                       nb_nouvelles=nb_nouvelles, nb_requetes=0, erreurs=" / ".join(erreurs) or None)
    return passage_id, [{"source": "commune", "nb_offres": len(offres), "nb_nouvelles": nb_nouvelles, "nb_requetes": 0,
                         "erreurs": erreurs, "message": "", "nb_expirees": nb_retirees, "nb_retablies": 0}]

