"""Un passage complet : collecte, tri (pré-filtre + doublons), scoring IA.

Utilisé à l'identique par la ligne de commande (run.py) et par l'appli Streamlit.
"""
from . import collecte, scoring, traitement


def passage_complet(conn, config: dict, auto: bool = False, sources: list[str] | None = None,
                    max_requetes: int | None = None, client_ia=None) -> dict:
    passage_id, bilan_sources = collecte.lancer_passage(conn, config, auto=auto, sources_demandees=sources,
                                                        max_requetes=max_requetes)
    bilan_tri = traitement.traiter(conn, config)
    bilan_scoring = scoring.noter_nouvelles(conn, config, passage_id, auto, client=client_ia)
    return {"passage_id": passage_id, "auto": auto, "sources": bilan_sources,
            "tri": bilan_tri, "scoring": bilan_scoring}


def resume_texte(bilan: dict) -> list[str]:
    """Le bilan d'un passage en quelques lignes lisibles (pour le terminal et l'appli)."""
    mode = "automatique" if bilan["auto"] else "manuel"
    lignes = [f"Passage n°{bilan['passage_id']} ({mode})"]
    if not bilan["sources"]:
        lignes.append("  Aucune source active.")
    for ligne in bilan["sources"]:
        lignes.append(f"  - {ligne['source']} : {ligne['nb_offres']} offre(s) dont {ligne['nb_nouvelles']} "
                      f"nouvelle(s), {ligne['nb_requetes']} requête(s)")
        if ligne["message"]:
            lignes.append(f"      {ligne['message']}")
        lignes.extend(f"      ERREUR : {erreur}" for erreur in ligne["erreurs"])
    lignes.append(resume_tri(bilan["tri"]))
    lignes.extend(resume_scoring(bilan["scoring"]))
    return lignes


def resume_tri(bilan: dict) -> str:
    return (f"  Tri des {bilan['traitees']} offre(s) à traiter : {bilan['gardees']} gardée(s), "
            f"{bilan['exclues']} exclue(s) par le pré-filtre, {bilan['doublons']} doublon(s)")


def resume_scoring(bilan: dict) -> list[str]:
    lignes = [f"  Scoring IA : {bilan['notees']} offre(s) notée(s), coût {bilan['cout_usd']:.4f} $ "
              f"({bilan['tokens_entree']} tokens en entrée, {bilan['tokens_sortie']} en sortie)"]
    if bilan.get("message"):
        lignes.append(f"      {bilan['message']}")
    lignes.extend(f"      ERREUR : {erreur}" for erreur in bilan["erreurs"])
    return lignes
