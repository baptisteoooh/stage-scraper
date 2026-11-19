"""Version anglaise du site : le français reste la référence, un dictionnaire donne l'anglais.

statique/i18n/en.json :
- "textes" : phrase française exacte -> anglais ;
- "motifs" : phrase avec des trous {} -> anglais avec {1}, {2}… (chaque morceau est traduit à son tour :
  « Dernier scrap hier à 8 h 02 » -> « Last scrape yesterday at 8:02 »).

Le serveur traduit les pages HTML avant de les envoyer ; dans le navigateur, js/langue.js traduit de la même
façon ce que les scripts ajoutent (cartes, messages, fiches). Les offres et les textes de l'IA ne sont pas
touchés : ils ne figurent pas dans le dictionnaire (et les zones marquées translate="no" sont sautées).
La langue est un cookie « langue » (fr par défaut).
"""
import html as module_html
import json
import re
from functools import lru_cache
from pathlib import Path

FICHIER = Path(__file__).parent / "statique" / "i18n" / "en.json"
LANGUES = ("fr", "en")
ATTRIBUTS = ("placeholder", "aria-label", "title", "alt")
PROFONDEUR = 3


def langue_de(request) -> str:
    lang = request.cookies.get("langue", "fr") if request is not None else "fr"
    return lang if lang in LANGUES else "fr"


def _source(fr: str) -> str:
    """« Version {n}/{n} · écrite par {} » -> expression régulière (même syntaxe en Python et en JavaScript).

    {} : n'importe quel morceau ; {n} : un nombre seulement (« 1 sur {n} » ne prend pas « Paris sur Seine »).
    """
    morceaux = re.split(r"(\{n?\})", fr)
    sortie = []
    for m in morceaux:
        if m == "{}":
            sortie.append("(.+?)")
        elif m == "{n}":
            sortie.append(r"(\d[\d\u202f\u00a0 ,.]*)")
        else:
            sortie.append(re.sub(r"([.*+?^${}()|\[\]\\/])", r"\\\1", m))
    return "^" + "".join(sortie) + "$"


@lru_cache(maxsize=1)
def dictionnaire() -> dict:
    brut = json.loads(FICHIER.read_text(encoding="utf-8"))
    motifs = [[_source(fr), en] for fr, en in brut["motifs"].items()]
    return {"textes": brut["textes"], "motifs": motifs}


@lru_cache(maxsize=1)
def _motifs_compiles() -> list:
    return [(re.compile(s, re.S), en) for s, en in dictionnaire()["motifs"]]


def _nombre(t: str) -> str | None:
    if re.fullmatch(r"-?\d+(,\d+)?", t.strip()):
        return t.replace(",", ".")
    return None


def traduire(texte: str, profondeur: int = 0) -> str:
    """Traduit un texte entier (les espaces autour sont gardés) ; inchangé s'il n'est pas connu."""
    coeur = texte.strip()
    if not coeur or profondeur > PROFONDEUR:
        return texte
    d = dictionnaire()
    trouve = d["textes"].get(coeur)
    if trouve is None and profondeur:
        trouve = _nombre(coeur)
    if trouve is None:
        for motif, en in _motifs_compiles():
            m = motif.match(coeur)
            if m:
                trouve = en
                for i, morceau in enumerate(m.groups(), 1):
                    trouve = trouve.replace("{%d}" % i, traduire(morceau, profondeur + 1))
                break
    if trouve is None:
        return texte
    debut = texte[:len(texte) - len(texte.lstrip())]
    fin = texte[len(texte.rstrip()):]
    return debut + trouve + fin


def traduire_html(page: str) -> str:
    """Traduit le texte et les attributs lisibles d'une page (pas les scripts ni les styles)."""
    def texte(m):
        brut = m.group(1)
        if not brut.strip():
            return m.group(0)
        clair = module_html.unescape(brut)
        traduit = traduire(clair)
        return ">" + (brut if traduit == clair else module_html.escape(traduit, quote=False)) + "<"

    def attribut(m):
        clair = module_html.unescape(m.group(2))
        traduit = traduire(clair)
        return m.group(0) if traduit == clair else f'{m.group(1)}="{module_html.escape(traduit)}"'

    morceaux = re.split(r"(<script\b.*?</script>|<style\b.*?</style>)", page, flags=re.S | re.I)
    for i in range(0, len(morceaux), 2):
        m = re.sub(r">([^<>]+)<", texte, morceaux[i])
        morceaux[i] = re.sub(r'\b(%s)="([^"]*)"' % "|".join(ATTRIBUTS), attribut, m)
    page = "".join(morceaux)
    return page.replace('<html lang="fr">', '<html lang="en">', 1)


def preparer_page(page: str, langue: str) -> str:
    """Page envoyée au navigateur : traduite, avec le dictionnaire pour js/langue.js (anglais seulement)."""
    if langue != "en":
        return page
    donnees = json.dumps(dictionnaire(), ensure_ascii=False).replace("</", "<\\/")
    script = f'<script>window.TRADUCTION = {donnees};</script>\n<script src="/statique/js/langue.js"></script>\n'
    return traduire_html(page).replace("</head>", script + "</head>", 1)
