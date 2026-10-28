"""Après la collecte : pré-filtre puis dédoublonnage des nouvelles offres."""
import logging
from datetime import date

from . import dedoublonnage, prefiltre

log = logging.getLogger(__name__)

CHAMPS_DETECTES = ("departement", "duree", "duree_mois", "date_debut")


def traiter(conn, config: dict, tout: bool = False, aujourd_hui: date | None = None) -> dict:
    """Traite les offres pas encore traitées (ou toutes si `tout`, après un changement de réglages).

    Renvoie {'traitees': n, 'exclues': n, 'doublons': n, 'gardees': n}.
    """
    if tout:
        conn.execute("UPDATE offres SET empreinte = NULL, doublon_de = NULL, exclusion_prefiltre = NULL")
    offres = conn.execute("SELECT * FROM offres WHERE empreinte IS NULL ORDER BY id").fetchall()

    bilan = {"traitees": 0, "exclues": 0, "doublons": 0, "gardees": 0}
    for ligne in offres:
        offre = dict(ligne)
        raison, detectes = prefiltre.verifier(offre, config, aujourd_hui)
        offre.update(detectes)
        cle = dedoublonnage.empreinte(offre, config)
        original = dedoublonnage.trouver_original(conn, offre, cle, config)

        valeurs = {"empreinte": cle, "doublon_de": original, "exclusion_prefiltre": raison,
                   **{c: offre[c] for c in CHAMPS_DETECTES if c in detectes}}
        conn.execute(f"UPDATE offres SET {', '.join(f'{c} = ?' for c in valeurs)} WHERE id = ?",
                     [*valeurs.values(), offre["id"]])

        bilan["traitees"] += 1
        if original:
            bilan["doublons"] += 1
        elif raison:
            bilan["exclues"] += 1
        else:
            bilan["gardees"] += 1
    conn.commit()
    return bilan
