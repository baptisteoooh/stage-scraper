"""Tests de la base de données (base temporaire, ta vraie base n'est pas touchée)."""
import sqlite3

import pytest

from stage_scraper import collecte, db
from stage_scraper.offre import nouvelle_offre
from stage_scraper.sources import Resultat


@pytest.fixture
def conn(tmp_path):
    connexion = db.connecter(tmp_path / "test.db")
    db.initialiser(connexion)
    yield connexion
    connexion.close()


def offre(source_id, titre="Stage data"):
    return nouvelle_offre(source="test", source_id=source_id, titre=titre)


def test_une_offre_deja_connue_n_est_pas_ajoutee_deux_fois(conn):
    assert db.enregistrer_offres(conn, [offre("a"), offre("b")], passage_id=1) == 2
    assert db.enregistrer_offres(conn, [offre("b"), offre("c")], passage_id=2) == 1
    assert conn.execute("SELECT COUNT(*) FROM offres").fetchone()[0] == 3


def test_statut_de_candidature_invalide_refuse(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO candidatures (entreprise, statut) VALUES ('X', 'n importe quoi')")


def test_migration_depuis_la_version_1(tmp_path):
    # Simule une base créée à l'étape 1 : le schéma actuel, sans les colonnes ajoutées en version 2.
    schema_v1 = "\n".join(
        ligne for ligne in db.SCHEMA.splitlines()
        if not ligne.strip().startswith(("site_origine", "nb_requetes", "poste_ia_data"))
    )
    ancienne = sqlite3.connect(tmp_path / "v1.db")
    ancienne.executescript(schema_v1 + "\nPRAGMA user_version = 1;")
    ancienne.close()
    connexion = db.connecter(tmp_path / "v1.db")
    db.initialiser(connexion)
    colonnes = {ligne["name"] for ligne in connexion.execute("PRAGMA table_info(offres)")}
    assert "site_origine" in colonnes
    assert connexion.execute("PRAGMA user_version").fetchone()[0] == db.VERSION_SCHEMA
    connexion.close()


def test_une_source_qui_plante_ne_bloque_pas_les_autres(conn, monkeypatch):
    def plante(config, contexte):
        raise RuntimeError("site en panne")

    def marche(config, contexte):
        return Resultat(offres=[offre("x")], nb_requetes=1)

    monkeypatch.setattr(collecte, "SOURCES", {"plante": plante, "marche": marche})
    config = {"sources": {"plante": {"actif": True}, "marche": {"actif": True}}}
    passage_id, bilan = collecte.lancer_passage(conn, config)

    assert passage_id == 1
    assert bilan[0]["erreurs"] and "site en panne" in bilan[0]["erreurs"][0]
    assert bilan[1]["nb_nouvelles"] == 1
    journal = conn.execute("SELECT source, erreurs FROM runs ORDER BY id").fetchall()
    assert [ligne["source"] for ligne in journal] == ["plante", "marche"]
