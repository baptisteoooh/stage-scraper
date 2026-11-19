"""Le CV et le modèle de lettre de BAP, en texte anonymisé : c'est tout ce que reçoivent les IA.

- profil/cv.pdf : le texte est extrait avec pypdf. Les accents des PDF faits en LaTeX
  (« sup´erieure ») sont réparés.
- profil/modele_lettre.txt : une lettre écrite par BAP, qui sert de modèle de style.
- Anonymisation : la ligne de coordonnées (téléphone, e-mail, LinkedIn, ville) est retirée,
  ainsi que tout e-mail, numéro de téléphone ou lien restant, et le nom (première ligne du CV)
  est remplacé par [Prénom Nom]. Le PDF lui-même n'est jamais envoyé.

Le dossier profil/ est ignoré par Git.
"""
import hashlib
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from .config import chemin_projet

NOM_MASQUE = "[Prénom Nom]"
COORDONNEES_MASQUEES = "[coordonnées retirées]"

# Accents « détachés » produits par LaTeX : le signe précède la lettre.
ACCENTS = {"´": "́", "`": "̀", "ˆ": "̂", "¨": "̈", "˜": "̃", "¸": "̧"}
_ACCENT_DETACHE = re.compile("([" + "".join(ACCENTS) + "])\\s?([A-Za-zıȷ])")

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
TELEPHONE = re.compile(r"(?<!\d)(\+\d{1,3}[\s.-]?)?\(?0?\d([\s.-]?\d{2}){4}(?!\d)")
LIEN = re.compile(r"(https?://\S+|www\.\S+|(linkedin|github)\.com/\S*)", re.IGNORECASE)


def reparer_accents(texte: str) -> str:
    """« sup´erieure » → « supérieure », « Fran¸cais » → « Français »."""
    def remplacer(m):
        lettre = {"ı": "i", "ȷ": "j"}.get(m.group(2), m.group(2))
        return lettre + ACCENTS[m.group(1)]
    return unicodedata.normalize("NFC", _ACCENT_DETACHE.sub(remplacer, texte))


def nom_du_cv(texte: str) -> str | None:
    """Le nom en tête du CV : première ligne de 2 à 4 mots, sans chiffre."""
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        mots = ligne.split()
        if 2 <= len(mots) <= 4 and not any(c.isdigit() for c in ligne) and all(m[0].isupper() for m in mots):
            return ligne
        return None
    return None


def anonymiser(texte: str, nom: str | None = None) -> str:
    """Retire les coordonnées (ligne entière) et le nom."""
    lignes = []
    for ligne in texte.splitlines():
        if EMAIL.search(ligne) or TELEPHONE.search(ligne) or LIEN.search(ligne):
            if not lignes or lignes[-1] != COORDONNEES_MASQUEES:
                lignes.append(COORDONNEES_MASQUEES)
            continue
        lignes.append(ligne)
    texte = "\n".join(lignes)
    if nom:
        texte = re.sub(re.escape(nom), NOM_MASQUE, texte, flags=re.IGNORECASE)
        # le prénom seul (signature « Jeanne ») ou le nom de famille seul
        for morceau in nom.split():
            if len(morceau) > 2:
                texte = re.sub(rf"\b{re.escape(morceau)}\b", NOM_MASQUE, texte, flags=re.IGNORECASE)
        texte = re.sub(r"\[Prénom Nom\](?:[ \t]+\[Prénom Nom\])+", NOM_MASQUE, texte)   # « Prénom Nom » → un seul masque
    return texte.strip()


def chemin_cv(config: dict) -> Path:
    return chemin_projet(config["profil"].get("cv", "profil/cv.pdf"))


def chemin_modele_lettre(config: dict) -> Path:
    return chemin_projet(config["profil"].get("modele_lettre", "profil/modele_lettre.txt"))


def texte_cv(config: dict) -> str | None:
    """Le CV en texte anonymisé, ou None s'il n'y a pas encore de profil/cv.pdf."""
    chemin = chemin_cv(config)
    if not chemin.exists():
        return None
    return _lire_cv(str(chemin), chemin.stat().st_mtime)[0]


def modele_lettre(config: dict) -> str | None:
    """Le modèle de lettre anonymisé (avec le nom tiré du CV), ou None s'il n'existe pas."""
    chemin = chemin_modele_lettre(config)
    if not chemin.exists():
        return None
    nom = None
    if chemin_cv(config).exists():
        nom = _lire_cv(str(chemin_cv(config)), chemin_cv(config).stat().st_mtime)[1]
    return anonymiser(chemin.read_text(encoding="utf-8", errors="replace"), nom)


def empreinte(texte: str | None) -> str | None:
    """Empreinte courte du CV : un diagnostic est à refaire quand elle change."""
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()[:16] if texte else None


@lru_cache(maxsize=4)
def _lire_cv(chemin: str, _date_modif: float) -> tuple[str, str | None]:
    """(texte anonymisé, nom trouvé). Relu seulement quand le fichier change."""
    from pypdf import PdfReader
    brut = "\n".join(page.extract_text() or "" for page in PdfReader(chemin).pages)
    brut = reparer_accents(brut)
    nom = nom_du_cv(brut)
    return anonymiser(brut, nom), nom
