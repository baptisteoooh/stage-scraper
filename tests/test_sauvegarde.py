"""Mode WAL et sauvegarde nocturne : toujours sur un faux projet dans un dossier temporaire."""
import shutil
import sqlite3
from contextlib import closing
from datetime import date

import pytest

from stage_scraper import comptes, db, sauvegarde
from stage_scraper.config import CHEMIN_CONFIG
from stage_scraper.offre import nouvelle_offre


@pytest.fixture
def projet(tmp_path, monkeypatch):
    """Faux projet : config.yaml, .env, profil/, data/stages.db, un compte d'ami."""
    racine = tmp_path / "projet"
    (racine / "profil").mkdir(parents=True)
    shutil.copyfile(CHEMIN_CONFIG, racine / "config.yaml")
    (racine / ".env").write_text("GEMINI_API_KEY=fausse\n", encoding="utf-8")
    (racine / "profil" / "cv.pdf").write_bytes(b"%PDF faux")
    with closing(db.connecter(racine / "data" / "stages.db")) as conn:
        db.initialiser(conn)
        db.enregistrer_offres(conn, [nouvelle_offre(source="test", source_id="1", titre="Stage IA", entreprise="Doctolib",
                                                    lieu="Paris")], passage_id=1)
        conn.commit()
    monkeypatch.setenv("STAGE_SCRAPER_COMPTES_DOSSIER", str(racine / "comptes"))
    monkeypatch.setenv("STAGE_SCRAPER_CONFIG", str(racine / "config.yaml"))
    monkeypatch.setenv("STAGE_SCRAPER_SAUVEGARDES", str(tmp_path / "sauvegardes"))
    comptes.creer_admin("bap", "un-bon-mot-de-passe")
    comptes.creer_avec_invitation(comptes.inviter(), "ami", "un-bon-mot-de-passe")
    return racine


def test_les_bases_sont_en_mode_wal(projet):
    with closing(db.connecter(projet / "data" / "stages.db")) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    with closing(comptes._connecter()) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_lecture_pendant_une_ecriture(projet):
    """Le site lit pendant que le passage de 8 h écrit (transaction en cours) : pas de « database is locked »."""
    chemin = projet / "data" / "stages.db"
    with closing(db.connecter(chemin)) as ecrivain, closing(db.connecter(chemin)) as lecteur:
        ecrivain.execute("BEGIN IMMEDIATE")
        ecrivain.execute("UPDATE offres SET score = 9")
        lecteur.execute("PRAGMA busy_timeout = 100")          # échouerait vite si la lecture était bloquée
        assert lecteur.execute("SELECT score FROM offres").fetchone()[0] is None   # voit l'état d'avant
        ecrivain.commit()
        assert lecteur.execute("SELECT score FROM offres").fetchone()[0] == 9


def test_sauvegarde_complete(projet):
    with closing(db.connecter(projet / "data" / "stages.db")) as ouverte:   # le site a la base ouverte
        ouverte.execute("UPDATE offres SET score = 7")
        ouverte.commit()                                                   # encore dans le fichier -wal
        bilan = sauvegarde.sauvegarder(date(2026, 11, 24), projet=projet)
    jour = bilan["dossier"]
    assert jour.name == "2026-11-24" and bilan["erreurs"] == []
    attendus = {"projet/data/stages.db", "projet/config.yaml", "projet/.env", "projet/profil/cv.pdf",
                "comptes/comptes.db", "comptes/ami/stages.db", "comptes/ami/config.yaml"}
    trouves = {f.relative_to(jour).as_posix() for f in jour.rglob("*") if f.is_file()}
    assert attendus <= trouves
    assert not [f for f in trouves if f.endswith(("-wal", "-shm"))]        # chaque base tient en un seul fichier
    with closing(sqlite3.connect(jour / "projet" / "data" / "stages.db")) as copie:
        assert copie.execute("SELECT score FROM offres").fetchone()[0] == 7  # le contenu du -wal est bien dedans
        assert copie.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    with closing(sqlite3.connect(jour / "comptes" / "comptes.db")) as copie:
        assert {l[0] for l in copie.execute("SELECT nom FROM comptes")} == {"bap", "ami"}


def test_on_garde_14_jours(projet):
    for jour in range(1, 21):
        sauvegarde.sauvegarder(date(2026, 11, jour), projet=projet)
    restants = sorted(d.name for d in sauvegarde.dossier_sauvegardes().iterdir())
    assert restants == [f"2026-11-{j:02d}" for j in range(7, 21)]


def test_refaire_la_sauvegarde_du_jour_la_remplace(projet):
    sauvegarde.sauvegarder(date(2026, 11, 24), projet=projet)
    (projet / "profil" / "cv.pdf").unlink()
    bilan = sauvegarde.sauvegarder(date(2026, 11, 24), projet=projet)
    assert not (bilan["dossier"] / "projet" / "profil" / "cv.pdf").exists()
    assert [d.name for d in sauvegarde.dossier_sauvegardes().iterdir()] == ["2026-11-24"]


def test_une_base_abimee_n_empeche_pas_le_reste(projet):
    abimee = projet / "comptes" / "ami" / "stages.db"
    abimee.write_bytes(b"ceci n'est pas une base SQLite" * 100)
    bilan = sauvegarde.sauvegarder(date(2026, 11, 24), projet=projet)
    assert len(bilan["erreurs"]) == 1 and "comptes/ami/stages.db" in bilan["erreurs"][0]
    assert (bilan["dossier"] / "projet" / "data" / "stages.db").exists()
    assert (bilan["dossier"] / "comptes" / "comptes.db").exists()
