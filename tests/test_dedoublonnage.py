"""Tests du dédoublonnage et du traitement complet, sur une base temporaire."""
from contextlib import closing
from datetime import date

from stage_scraper import db, dedoublonnage, traitement
from stage_scraper.config import charger_config
from stage_scraper.offre import nouvelle_offre

CONFIG = charger_config()


def test_cle_titre():
    assert dedoublonnage.cle_titre("Stage - Data Scientist (H/F) - janvier 2027") == "data scientist"
    assert dedoublonnage.cle_titre("Data Scientist Intern (x/f/m)") == "data scientist"


def test_cle_entreprise_alias():
    assert dedoublonnage.cle_entreprise("J&J", CONFIG) == dedoublonnage.cle_entreprise("Johnson & Johnson", CONFIG)
    assert dedoublonnage.cle_entreprise("Coface SA", CONFIG) == "coface"


def proches(a, b):
    return dedoublonnage.titres_proches(dedoublonnage.cle_titre(a), dedoublonnage.cle_titre(b))


def test_titres_proches():
    assert proches("Stage - Data Science, IA & Machine Learning H/F", "Stage Data Science IA & Machine Learning")
    assert proches("Data Scientist / ML Engineer", "Data Scientists / ML Engineers")
    assert not proches("Stage - AI Data Analyst H/F", "Data Analyst H/F")
    assert not proches("Stage Data Analyst", "Stage Data Engineer")


def offre(source, source_id, titre, entreprise="Coface", lieu="Paris", **autres):
    return nouvelle_offre(source=source, source_id=source_id, titre=titre, entreprise=entreprise,
                          lieu=lieu, date_publication="2026-10-20", **autres)


def test_traitement_complet(tmp_path):
    with closing(db.connecter(tmp_path / "test.db")) as conn:
        db.initialiser(conn)
        db.enregistrer_offres(conn, [
            offre("careerjet", "1", "Stage - Data Scientist / ML Engineer (H/F)"),
            offre("google_jobs", "2", "Stage Data Scientist / ML Engineer"),           # doublon entre sites
            offre("careerjet", "3", "Stage Data Scientist / ML Engineer", lieu="Lyon"),  # autre ville : distincte
            offre("careerjet", "4", "Stage Marketing Digital"),                         # exclue
            offre("careerjet", "5", "Stage Data Analyst", entreprise=None),              # sans entreprise : gardée
        ], passage_id=1)

        bilan = traitement.traiter(conn, CONFIG, aujourd_hui=date(2026, 10, 28))
        assert bilan == {"traitees": 5, "exclues": 2, "doublons": 1, "gardees": 2}

        lignes = {r["source_id"]: r for r in conn.execute("SELECT * FROM offres")}
        assert lignes["2"]["doublon_de"] == lignes["1"]["id"]
        assert lignes["3"]["doublon_de"] is None and lignes["3"]["exclusion_prefiltre"].startswith("lieu")
        assert lignes["4"]["exclusion_prefiltre"] == "poste : marketing"

        # Un second traitement ne refait rien ; --retraiter refait tout à l'identique.
        assert traitement.traiter(conn, CONFIG)["traitees"] == 0
        assert traitement.traiter(conn, CONFIG, tout=True, aujourd_hui=date(2026, 10, 28)) == bilan
