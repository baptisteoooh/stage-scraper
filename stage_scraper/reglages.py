"""Modification de config.yaml depuis l'appli, en gardant les commentaires et la mise en forme du fichier.

Seules les valeurs réellement changées sont touchées : les listes sont modifiées sur place pour que
les commentaires qui les suivent (titres de section) ne disparaissent pas.
"""
import shutil
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .config import CHEMIN_CONFIG


def _yaml() -> YAML:
    yaml = YAML()  # mode « aller-retour » : commentaires et mise en forme conservés
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)  # même retrait que le fichier écrit à la main
    yaml.width = 4096  # ne jamais couper une ligne au milieu d'un mot-clé
    return yaml


def lire(chemin: Path = CHEMIN_CONFIG):
    with open(chemin, encoding="utf-8") as f:
        return _yaml().load(f)


def ecrire(donnees, chemin: Path = CHEMIN_CONFIG) -> None:
    """Écrit config.yaml, après en avoir gardé une copie (config.yaml.bak) en cas de souci."""
    chemin = Path(chemin)
    if chemin.exists():
        shutil.copyfile(chemin, chemin.with_name(chemin.name + ".bak"))
    with open(chemin, "w", encoding="utf-8") as f:
        _yaml().dump(donnees, f)


def texte_en_liste(texte: str, separateur: str = "\n") -> list[str]:
    """'a, b,, c' -> ['a', 'b', 'c'] (éléments vides ignorés, doublons retirés)."""
    vus, resultat = set(), []
    for morceau in (texte or "").replace("\r", "").split(separateur):
        morceau = morceau.strip()
        if morceau and morceau.lower() not in vus:
            vus.add(morceau.lower())
            resultat.append(morceau)
    return resultat


def remplacer_liste(seq: CommentedSeq, valeurs: list) -> bool:
    """Remplace le contenu d'une liste sur place, en gardant le commentaire placé après elle."""
    if list(seq) == list(valeurs):
        return False
    commentaire_final = seq.ca.items.get(len(seq) - 1) if len(seq) else None
    seq.ca.items.clear()
    del seq[:]
    seq.extend(valeurs)
    if commentaire_final and len(seq):
        seq.ca.items[len(seq) - 1] = commentaire_final
    return True


def appliquer(donnees, modifications: dict) -> list[str]:
    """Applique les champs modifiés dans l'appli et renvoie la liste de ce qui a changé.

    modifications : {'anciennete_max_jours': 90, 'alerte_seuil_score': 8,
                     'contrats': [...], 'postes': [...], 'niveaux': [...],
                     'mots_cles': {nom du domaine: [...]}, 'entreprises_suivies': [dict, ...]}
    """
    changements = []
    for cle, section in (("anciennete_max_jours", "general"), ("alerte_seuil_score", "notifications")):
        if cle in modifications and donnees[section][cle] != int(modifications[cle]):
            donnees[section][cle] = int(modifications[cle])
            changements.append(cle)
    for cle in ("contrats", "postes", "niveaux"):
        if cle in modifications and remplacer_liste(donnees["exclusions"][cle], modifications[cle]):
            changements.append(f"exclusions {cle}")
    for domaine in donnees["domaines"]:
        nouveaux = modifications.get("mots_cles", {}).get(domaine["nom"])
        if nouveaux is not None and remplacer_liste(domaine["mots_cles"], nouveaux):
            changements.append(f"mots-clés {domaine['nom']}")
    if "entreprises_suivies" in modifications:
        anciennes = {e["nom"]: e for e in donnees["entreprises_suivies"]}
        nouvelles = [_entreprise(e, anciennes.get((e.get("nom") or "").strip()))
                     for e in modifications["entreprises_suivies"] if (e.get("nom") or "").strip()]
        if remplacer_liste(donnees["entreprises_suivies"], nouvelles):
            changements.append("entreprises suivies")
    return changements


def _entreprise(ligne: dict, ancienne=None) -> CommentedMap:
    """Une ligne du tableau -> {nom, groupe, alias, carrieres}, écrite sur une ligne.

    Les autres champs éventuels de l'entreprise (ajoutés à la main dans le fichier) sont conservés.
    """
    m = CommentedMap()
    m["nom"] = ligne["nom"].strip()
    m["groupe"] = (ligne.get("groupe") or "scale_up").strip()
    alias = texte_en_liste(ligne.get("alias") or "", ",")
    if alias:
        m["alias"] = _en_ligne(CommentedSeq(alias))
    outil, identifiant = (ligne.get("outil") or "").strip(), (ligne.get("adresse_ou_id") or "").strip()
    if outil and identifiant:
        carrieres = CommentedMap()
        for cle, valeur in ((ancienne or {}).get("carrieres") or {}).items():
            if cle not in ("outil", "url", "id"):
                carrieres[cle] = valeur
        carrieres.insert(0, "outil", outil)
        carrieres.insert(1, "url" if outil == "workday" else "id", identifiant)
        m["carrieres"] = _en_ligne(carrieres)
    for cle, valeur in (ancienne or {}).items():
        if cle not in ("nom", "groupe", "alias", "carrieres"):
            m[cle] = valeur
    if ancienne is not None and _simple(ancienne) == _simple(m):
        return ancienne  # rien n'a changé : on garde l'objet d'origine tel quel
    return _en_ligne(m)


def _en_ligne(objet):
    objet.fa.set_flow_style()
    return objet


def _simple(objet):
    """Version en dict/list Python pur, pour comparer sans tenir compte de la mise en forme."""
    if isinstance(objet, dict):
        return {k: _simple(v) for k, v in objet.items()}
    if isinstance(objet, list):
        return [_simple(v) for v in objet]
    return objet


def entreprises_en_lignes(donnees) -> list[dict]:
    """Pour le tableau de l'appli : une ligne simple par entreprise suivie."""
    lignes = []
    for e in donnees.get("entreprises_suivies", []):
        carrieres = e.get("carrieres") or {}
        lignes.append({
            "nom": e["nom"], "groupe": e.get("groupe", ""), "alias": ", ".join(e.get("alias", [])),
            "outil": carrieres.get("outil", ""), "adresse_ou_id": carrieres.get("url") or carrieres.get("id") or "",
        })
    return lignes
