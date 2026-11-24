"""Sauvegarde des données (lancée chaque nuit sur le serveur : python run.py --sauvegarder).

Chaque sauvegarde est un dossier daté, par exemple data/sauvegardes/auto/2026-11-24/, qui contient :
- les bases SQLite (celle de BAP, comptes.db, la base de chaque ami), copiées avec l'API « backup » de SQLite :
  une copie propre même si le site ou le passage de 8 h écrit au même moment (copier le fichier à la main
  pourrait donner une base abîmée en mode WAL) ;
- les petits fichiers personnels : config.yaml, .env, profil/, et le reste du dossier comptes/ (réglages, CV et
  clés des amis).
On garde les 14 derniers jours ; les plus anciens sont effacés. Les journaux (logs/) et les mails gardés pour les
tests (data/emails) ne sont pas sauvegardés.

Restaurer : arrêter le site, recopier le fichier voulu à sa place (en effaçant les fichiers -wal et -shm à côté
de la base remplacée), relancer le site.
"""
import logging
import os
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

from .comptes import dossier_comptes
from .config import RACINE, charger_config

JOURS_GARDES = 14
_DOSSIER_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_A_IGNORER = re.compile(r"\.db-(wal|shm|journal)$|\.bak$")   # fichiers de travail de SQLite, copies .bak

log = logging.getLogger(__name__)


def dossier_sauvegardes() -> Path:
    autre = os.getenv("STAGE_SCRAPER_SAUVEGARDES")
    return Path(autre) if autre else RACINE / "data" / "sauvegardes" / "auto"


def a_sauvegarder(projet: Path = RACINE) -> list[tuple[Path, Path]]:
    """(fichier d'origine, chemin dans la sauvegarde) pour tout ce qui doit être gardé."""
    fichiers = []
    base = Path(charger_config(projet / "config.yaml")["general"]["base_de_donnees"])
    base = base if base.is_absolute() else projet / base
    if base.exists():
        fichiers.append((base, Path("projet") / (base.relative_to(projet) if base.is_relative_to(projet) else base.name)))
    for nom in ("config.yaml", ".env"):
        if (projet / nom).exists():
            fichiers.append((projet / nom, Path("projet") / nom))
    for dossier, etiquette in ((projet / "profil", Path("projet") / "profil"), (dossier_comptes(), Path("comptes"))):
        if dossier.is_dir():
            for f in sorted(dossier.rglob("*")):
                if f.is_file() and not _A_IGNORER.search(f.name):
                    fichiers.append((f, etiquette / f.relative_to(dossier)))
    return fichiers


def copier_base(origine: Path, destination: Path) -> None:
    """Copie propre d'une base SQLite, vérifiée, en un seul fichier (sans -wal à côté)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(origine.resolve().as_uri() + "?mode=ro", uri=True, timeout=60)) as source, \
            closing(sqlite3.connect(destination)) as copie:
        source.backup(copie)
        copie.execute("PRAGMA journal_mode = DELETE")
        verdict = copie.execute("PRAGMA quick_check").fetchone()[0]
    if verdict != "ok":
        raise RuntimeError(f"copie de {origine.name} abîmée : {verdict}")


def sauvegarder(aujourd_hui: date | None = None, projet: Path = RACINE) -> dict:
    """Fait la sauvegarde du jour (la refait si elle existe déjà) puis efface les trop vieilles.
    Renvoie {"dossier", "fichiers", "erreurs", "effacees"}. Un fichier qui échoue n'arrête pas les autres."""
    racine = dossier_sauvegardes()
    jour = (aujourd_hui or date.today()).isoformat()
    final, en_cours = racine / jour, racine / f".{jour}.en-cours"
    shutil.rmtree(en_cours, ignore_errors=True)
    en_cours.mkdir(parents=True)
    copies, erreurs = 0, []
    for origine, relatif in a_sauvegarder(projet):
        destination = en_cours / relatif
        try:
            if origine.suffix == ".db":
                copier_base(origine, destination)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origine, destination)
            copies += 1
        except Exception as e:   # une base abîmée ne doit pas empêcher de sauver le reste
            log.exception("Sauvegarde de %s", origine)
            erreurs.append(f"{relatif.as_posix()} : {e}")
    shutil.rmtree(final, ignore_errors=True)
    en_cours.rename(final)   # la sauvegarde n'apparaît sous son vrai nom qu'une fois complète
    return {"dossier": final, "fichiers": copies, "erreurs": erreurs, "effacees": effacer_anciennes(racine)}


def effacer_anciennes(racine: Path, garder: int = JOURS_GARDES) -> list[str]:
    """Garde les `garder` sauvegardes les plus récentes (dossiers AAAA-MM-JJ seulement), efface les autres."""
    jours = sorted((d for d in racine.iterdir() if d.is_dir() and _DOSSIER_DATE.match(d.name)), key=lambda d: d.name)
    trop_vieilles = jours[:-garder] if garder else jours
    for d in trop_vieilles:
        shutil.rmtree(d)
    return [d.name for d in trop_vieilles]
