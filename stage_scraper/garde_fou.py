"""Garde-fou commun aux bots : une IA ne doit jamais annoncer une action qu'elle n'a pas faite.

Le code ne fait pas confiance à la réponse de l'IA : il compare ce qu'elle annonce avec ce qui a réellement changé
(profil, lettre). `annonce_action` repère les phrases du type « J'ai remonté… », « C'est fait », « I've added… ».
Quand une réponse annonce une action alors que rien n'a changé, l'appelant la corrige (relance, puis message
d'erreur honnête) au lieu de la montrer telle quelle.
"""
import re

# Verbes d'action au passé composé, en français et en anglais (« j'ai bien ajouté », « I've now moved »).
_PARTICIPES_FR = (r"ajout|rajout|retir|supprim|enlev|chang|modifi|remont|redescend|descend|d[ée]plac|mis\b|pass[ée]|"
                  r"avanc|recul|repouss|d[ée]cal|remplac|fix|r[ée]gl|actualis|corrig|r[ée][ée]?cri|raccourc|allong|"
                  r"r[ée]dui|reformul|int[ée]gr|retouch|[ée]crit|inclu|exclu|[ée]larg|restrein|class|r[ée]ordonn|"
                  r"plac|mont|baiss|augment|ramen|envoy|marqu|postul|archiv|enregistr|mis[e]? [àa] jour")
_ANNONCES = [
    re.compile(rf"\bj['’]\s?ai\s+(?:\w+\s+){{0,2}}?(?:{_PARTICIPES_FR})", re.I),
    re.compile(r"\bje\s+(?:t['’]\s?ai\s+)?(?:\w+\s+)?(?:garde|suis|prends|retiens|accepte|exclus|ignore|vise)s?\s+"
               r"(?:maintenant|d[ée]sormais|dor[ée]navant|aussi|[ée]galement)\b", re.I),
    re.compile(r"\bc['’]\s?est\s+(?:bien\s+)?(?:fait|not[ée]|chang[ée]|modifi[ée]|r[ée]gl[ée]|corrig[ée])\b", re.I),
    re.compile(r"\b(?:est|sont)\s+(?:maintenant|d[ée]sormais|dor[ée]navant)\b", re.I),
    re.compile(r"\bi(?:['’]ve|\s+have)\s+(?:\w+\s+)?(?:added|removed|deleted|changed|moved|updated|set|replaced|"
               r"rewritten|rewrote|edited|adjusted|shortened|lengthened|reordered|put|made|swapped|excluded|included|"
               r"followed|sent|marked|saved)\b", re.I),
    re.compile(r"\b(?:is|are)\s+now\b|\bdone\b|\bi\s+(?:now\s+)?(?:keep|follow|accept)\s+(?:now|also)\b", re.I),
]


def annonce_action(texte: str | None) -> bool:
    """Vrai si le texte dit qu'une action vient d'être faite (« J'ai remonté la bioinformatique… »)."""
    return bool(texte) and any(m.search(texte) for m in _ANNONCES)


# Ce que l'Assistant (lecture seule) pourrait prétendre avoir changé.
_OBJETS_MODIFIABLES = re.compile(
    r"\b(?:profil|candidature|statut|s[ée]lection|corbeille|relance|mail|e-mail|courriel|crit[èe]res?|domaines?|"
    r"entreprises? suivies?|r[ée]glages?|lettre|cv|profile|application|status|selection|settings|letter|email)\b", re.I)

AVERTISSEMENT_LECTURE_SEULE = ("\n\n*Attention : l'Assistant ne peut rien modifier (profil, candidatures, lettre…). "
                               "Rien n'a été changé : fais-le dans la page concernée.*")


def annonce_modification_impossible(texte: str | None) -> bool:
    """Vrai si un bot en lecture seule dit avoir modifié le profil, une candidature, une lettre…"""
    return annonce_action(texte) and bool(_OBJETS_MODIFIABLES.search(texte or ""))
