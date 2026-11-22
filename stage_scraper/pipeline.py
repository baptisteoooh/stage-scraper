"""Un passage complet : collecte, tri (pré-filtre + doublons), scoring IA, mails.

Utilisé à l'identique par la ligne de commande (run.py) et par l'appli Streamlit.
"""
import logging

from . import collecte, expiration, notifications, scoring, traitement

log = logging.getLogger(__name__)


def passage_complet(conn, config: dict, auto: bool = False, sources: list[str] | None = None,
                    max_requetes: int | None = None, client_ia=None, commune=None) -> dict:
    """Un passage : collecte, tri, notation, mails. Avec `commune` (compte d'un ami) : les offres viennent de la base
    de BAP au lieu des sites, et aucun mail ne part (ils partiraient de la boîte Gmail de BAP)."""
    if commune is not None:
        passage_id, bilan_sources = collecte.importer_commune(conn, commune, auto=auto)
        # puis ses recherches à lui, sur Careerjet (clé de BAP, plafond par ami) : ses offres vont dans SA base
        if config["sources"].get("careerjet", {}).get("actif", False):
            _, bilan_careerjet = collecte.lancer_passage(conn, config, auto=auto, sources_demandees=["careerjet"],
                                                         max_requetes=max_requetes, passage_id=passage_id)
            bilan_sources += bilan_careerjet
    else:
        passage_id, bilan_sources = collecte.lancer_passage(conn, config, auto=auto, sources_demandees=sources,
                                                            max_requetes=max_requetes)
    bilan_tri = traitement.traiter(conn, config)
    bilan_tri["anciennes"] = expiration.trop_anciennes(conn, config)
    bilan_scoring = scoring.noter_nouvelles(conn, config, passage_id, auto, client=client_ia)
    try:
        bilan_mails = [] if commune is not None else notifications.apres_passage(conn, config, passage_id, auto)
    except Exception as e:  # un souci de mail ne doit pas faire échouer le passage
        log.exception("Les mails ont planté")
        bilan_mails = [{"type": "alerte", "nb": 1, "envoye": False, "apercu": None, "erreur": type(e).__name__}]
    return {"passage_id": passage_id, "auto": auto, "sources": bilan_sources,
            "tri": bilan_tri, "scoring": bilan_scoring, "mails": bilan_mails}


def retrier(conn, config: dict) -> dict:
    """Refait le tri de toutes les offres (après un changement de réglages), ancienneté comprise."""
    bilan = traitement.traiter(conn, config, tout=True)
    bilan["anciennes"] = expiration.trop_anciennes(conn, config)
    return bilan


def resume_texte(bilan: dict) -> list[str]:
    """Le bilan d'un passage en quelques lignes lisibles (pour le terminal et l'appli)."""
    mode = "automatique" if bilan["auto"] else "manuel"
    lignes = [f"Passage n°{bilan['passage_id']} ({mode})"]
    if not bilan["sources"]:
        lignes.append("  Aucune source active.")
    for ligne in bilan["sources"]:
        lignes.append(f"  - {ligne['source']} : {ligne['nb_offres']} offre(s) dont {ligne['nb_nouvelles']} "
                      f"nouvelle(s), {ligne['nb_requetes']} requête(s)")
        if ligne.get("nb_expirees") or ligne.get("nb_retablies"):
            lignes.append(f"      {ligne.get('nb_expirees', 0)} offre(s) retirée(s) du site, marquée(s) expirée(s)"
                          + (f" ; {ligne['nb_retablies']} revenue(s) en ligne" if ligne.get("nb_retablies") else ""))
        if ligne["message"]:
            lignes.append(f"      {ligne['message']}")
        lignes.extend(f"      ERREUR : {erreur}" for erreur in ligne["erreurs"])
    lignes.append(resume_tri(bilan["tri"]))
    lignes.extend(resume_scoring(bilan["scoring"]))
    lignes.extend(notifications.resume(bilan.get("mails", [])))
    return lignes


def resume_tri(bilan: dict) -> str:
    texte = (f"  Tri des {bilan['traitees']} offre(s) à traiter : {bilan['gardees']} gardée(s), "
             f"{bilan['exclues']} exclue(s) par le pré-filtre, {bilan['doublons']} doublon(s)")
    if bilan.get("anciennes"):
        texte += f"\n  {bilan['anciennes']} offre(s) trop ancienne(s), marquée(s) expirée(s)"
    return texte


def resume_scoring(bilan: dict) -> list[str]:
    lignes = [f"  Scoring IA : {bilan['notees']} offre(s) notée(s), coût {bilan['cout_usd']:.4f} $ "
              f"({bilan['tokens_entree']} tokens en entrée, {bilan['tokens_sortie']} en sortie)"]
    if bilan.get("message"):
        lignes.append(f"      {bilan['message']}")
    lignes.extend(f"      ERREUR : {erreur}" for erreur in bilan["erreurs"])
    return lignes
