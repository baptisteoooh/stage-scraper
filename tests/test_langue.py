"""Version anglaise du site : dictionnaire, motifs à trous, pages traduites par le serveur."""
import re

from stage_scraper.web import langue
from test_site_web import base, client  # noqa: F401  (base de test et client du site)


def test_textes_et_motifs():
    t = langue.traduire
    assert t("À trier") == "To sort"
    assert t("  Je candidate ") == "  I'll apply "                      # espaces autour gardés
    assert t("Dernier scrap hier à 8 h 02") == "Last scrape yesterday at 8:02"
    assert t("Dernier scrap le 18/11 à 21 h 05") == "Last scrape on 18/11 at 21:05"
    assert t("Version 3/4 · écrite par l'IA ·") == "Version 3/4 · written by the AI ·"
    assert t("Claude Haiku · 0,08 centime") == "Claude Haiku · 0.08 cent"
    assert t("Mi-avril 2027") == "Mid-April 2027"


def test_les_donnees_ne_sont_pas_touchees():
    t = langue.traduire
    for donnee in ("Paris sur Seine", "Stage Data Scientist H/F", "début : janvier 2027 (hors de la fenêtre avril-mai)",
                   "Python : bon niveau", "Doctolib"):
        assert t(donnee) == donnee
    assert t("1 sur 120") == "1 of 120" and t("1 sur Paris") == "1 sur Paris"   # {n} : un nombre seulement


def test_dictionnaire_coherent():
    d = langue.dictionnaire()
    for source, en in d["motifs"]:
        trous = re.compile(source).groups
        assert trous and all(int(i) <= trous for i in re.findall(r"\{(\d)\}", en)), (source, en)
    assert all(v.strip() for v in d["textes"].values())


def test_traduire_html():
    page = ('<html lang="fr"><head><title>À trier · Stage Scraper</title><script>const x = "À trier";</script></head>'
            '<body><button aria-label="Pas pour moi">Pas pour moi</button><input placeholder="Rechercher"> Doctolib </body></html>')
    en = langue.traduire_html(page)
    assert '<html lang="en">' in en and "<title>To sort · Stage Scraper</title>" in en
    assert 'aria-label="Not for me">Not for me<' in en and 'placeholder="Search"' in en
    assert 'const x = "À trier";' in en and "> Doctolib <" in en                 # scripts et données intacts


def test_pages_selon_le_cookie(client):
    fr = client.get("/a-trier").text
    assert '<html lang="fr">' in fr and "TRADUCTION" not in fr and "Intéressé" in fr
    client.cookies.set("langue", "en")
    en = client.get("/a-trier").text
    assert '<html lang="en">' in en and "window.TRADUCTION" in en and "Interested" in en
    assert "/statique/js/langue.js" in en and "To sort" in en
    assert '<html lang="en">' in client.get("/").text
    client.cookies.set("langue", "xx")                                              # langue inconnue : français
    assert '<html lang="fr">' in client.get("/journal").text
