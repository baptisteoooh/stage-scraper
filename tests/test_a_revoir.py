"""« À revoir » : des propositions tirées des offres écartées, jamais appliquées sans « Oui », un « Non » retenu."""
import itertools
from contextlib import closing

import pytest

from stage_scraper import a_revoir, db, profil

_ids = itertools.count(1)

PROFIL = {
    "duree_max": 5, "six_mois": "a_negocier", "departements": list(profil.DEPARTEMENTS),
    "postes_exclus": ["marketing"],
    "entreprises": [{"nom": "Doctolib", "groupe": "priorite_absolue", "alias": "", "outil": "", "adresse_ou_id": ""},
                    {"nom": "Medtronic", "groupe": "grand_groupe", "alias": "Medtronic France", "outil": "", "adresse_ou_id": ""}],
}


@pytest.fixture
def conn(tmp_path):
    with closing(db.connecter(tmp_path / "essai.db")) as c:
        db.initialiser(c)
        yield c


def ecarter(conn, raison, titre="Stage data", entreprise="Une boîte", date="2026-11-20 10:00:00"):
    i = next(_ids)
    conn.execute("INSERT INTO offres (id, source, source_id, titre, entreprise, pas_interesse) VALUES (?, 'test', ?, ?, ?, 1)",
                 (i, str(i), titre, entreprise))
    conn.execute("INSERT INTO feedback (offre_id, raison, date) VALUES (?, ?, ?)", (i, raison, date))


def hors_zone(conn, departement, date="2026-11-20 10:00:00"):
    i = next(_ids)
    conn.execute("INSERT INTO offres (id, source, source_id, titre, departement, exclusion_prefiltre, date_collecte) "
                 "VALUES (?, 'test', ?, 'Stage IA', ?, 'lieu : Paris (hors Île-de-France)', ?)", (i, str(i), departement, date))


def props(conn, **p):
    return a_revoir.propositions(conn, {**PROFIL, **p}, maintenant=__import__("datetime").datetime(2026, 11, 21))


def test_rien_a_revoir(conn):
    ecarter(conn, "Trop long (6 mois)")
    ecarter(conn, "Pas mon domaine")
    assert props(conn) == []


def test_six_mois_revient_souvent(conn):
    for _ in range(3):
        ecarter(conn, "Trop long (6 mois)")
    (prop,) = props(conn)
    assert prop["valeurs"] == {"six_mois": "exclure"} and "3 offres" in prop["constat"]
    assert props(conn, six_mois="exclure") == []                     # déjà fait : plus rien à proposer
    assert props(conn, duree_max=6)[0]["valeurs"] == {"duree_max": 5}


def test_vieilles_decisions_ignorees(conn):
    for _ in range(5):
        ecarter(conn, "Trop long (6 mois)", date="2026-09-01 10:00:00")
    assert props(conn) == []


def test_entreprise_suivie_ecartee(conn):
    ecarter(conn, "Entreprise", entreprise="Medtronic")
    ecarter(conn, "Entreprise", entreprise="medtronic france")   # par son autre nom
    (prop,) = props(conn)
    assert prop["question"] == "Ne plus suivre Medtronic ?" and "«\u00a0Entreprise\u00a0»" in prop["constat"]
    assert [e["nom"] for e in prop["valeurs"]["entreprises"]] == ["Doctolib"]


def test_poste_pas_technique(conn):
    for titre in ["Stage Sales Ops", "Business developer - stage", "Stage sales France", "Stage Sales EMEA"]:
        ecarter(conn, "Commercial / pas technique", titre=titre)
    (prop,) = props(conn)
    assert prop["cle"] == "poste:sales" and prop["valeurs"] == {"postes_exclus": ["marketing", "sales"]}


def test_zone_reduite(conn):
    for _ in range(5):
        hors_zone(conn, "75")
    assert props(conn) == []                                         # toute l'IDF : rien perdu
    (prop,) = props(conn, departements=["92"])
    assert prop["valeurs"] == {"departements": list(profil.DEPARTEMENTS)} and "5 offres" in prop["constat"]


def test_non_est_retenu_et_au_plus_trois(conn):
    for _ in range(4):
        ecarter(conn, "Trop long (6 mois)")
    for _ in range(2):
        ecarter(conn, "Entreprise", entreprise="Doctolib")
    for _ in range(5):
        hors_zone(conn, "75")
    for titre in ["Stage sales", "Sales stage", "Stage sales B2B"]:
        ecarter(conn, "Commercial / pas technique", titre=titre)
    toutes = props(conn, departements=["92"])
    assert len(toutes) == 3 and toutes[0]["cle"] == "zone:92"       # les plus marquées d'abord (5 offres)
    a_revoir.ignorer(conn, "zone:92")
    assert "zone:92" not in [x["cle"] for x in props(conn, departements=["92"])]
    assert props(conn, departements=["92", "94"])[0]["cle"] == "zone:92,94"   # autre zone : la question revient


def test_en_anglais(conn):
    for _ in range(3):
        ecarter(conn, "Trop long (6 mois)")
    prop = a_revoir.propositions(conn, PROFIL, "en", maintenant=__import__("datetime").datetime(2026, 11, 21))[0]
    assert prop["question"].startswith("Stop keeping 6-month offers")


def test_api(tmp_path, monkeypatch):
    """GET /api/profil renvoie les propositions ; « Non » les fait disparaître."""
    import shutil
    from fastapi.testclient import TestClient
    from stage_scraper.config import CHEMIN_CONFIG
    copie = tmp_path / "config.yaml"
    shutil.copyfile(CHEMIN_CONFIG, copie)
    monkeypatch.setenv("STAGE_SCRAPER_CONFIG", str(copie))
    monkeypatch.setenv("STAGE_SCRAPER_BASE", str(tmp_path / "essai.db"))
    from stage_scraper.web import serveur
    with TestClient(serveur.app) as client, closing(db.connecter(tmp_path / "essai.db")) as c:
        db.initialiser(c)
        client.post("/api/profil", json={"valeurs": {"duree_max": 5, "six_mois": "a_negocier"}})
        for _ in range(3):
            ecarter(c, "Trop long (6 mois)", date=__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        c.commit()
        (prop,) = client.get("/api/profil").json()["a_revoir"]
        assert client.post("/api/profil/a-revoir/ignorer", json={"cle": prop["cle"]}).json()["a_revoir"] == []
