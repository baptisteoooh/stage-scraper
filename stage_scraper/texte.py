"""Petits outils pour comparer des textes sans tenir compte des accents ni des majuscules."""
import re
import unicodedata


def sans_accents(texte: str) -> str:
    """'Île-de-France' -> 'Ile-de-France'."""
    decompose = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in decompose if not unicodedata.combining(c))


def normaliser(texte: str | None) -> str:
    """Minuscules, sans accents, ponctuation remplacée par des espaces : 'Stage - Data (H/F)' -> 'stage data h f'."""
    bas = sans_accents(texte or "").lower().replace("’", "'")
    return re.sub(r"[^a-z0-9]+", " ", bas).strip()


def contient(texte: str | None, expression: str) -> bool:
    """Vrai si `expression` apparaît dans `texte` comme mot(s) entier(s).

    Sans tenir compte des accents ni des majuscules, sauf pour les sigles écrits en
    majuscules dans la config (CDI, VIE, PFE) : 'VIE' ne doit pas attraper 'qualité de vie'.
    """
    if not texte or not expression:
        return False
    if expression.replace(".", "").isupper():
        motif = r"(?<![A-Za-z0-9])" + re.escape(sans_accents(expression)) + r"(?![A-Za-z0-9])"
        return re.search(motif, sans_accents(texte)) is not None
    return re.search(r"(?<![a-z0-9])" + re.escape(normaliser(expression)) + r"(?![a-z0-9])",
                     normaliser(texte)) is not None


def contient_un(texte: str | None, expressions) -> str | None:
    """Renvoie la première expression trouvée dans le texte, ou None."""
    for expression in expressions or []:
        if contient(texte, str(expression)):
            return str(expression)
    return None
