"""Chargement des paramètres (config.yaml) et des secrets (.env).

Tous les chemins sont calculés à partir du dossier du projet : aucun chemin
en dur, pour que le code marche aussi ailleurs (autre PC, GitHub Actions).
"""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Dossier racine du projet (celui qui contient config.yaml).
RACINE = Path(__file__).resolve().parent.parent
CHEMIN_CONFIG = RACINE / "config.yaml"

# Secrets attendus dans .env, avec leur usage.
SECRETS_ATTENDUS = {
    "ANTHROPIC_API_KEY": "scoring IA",
    "FRANCE_TRAVAIL_CLIENT_ID": "API France Travail",
    "FRANCE_TRAVAIL_CLIENT_SECRET": "API France Travail",
    "ADZUNA_APP_ID": "API Adzuna",
    "ADZUNA_APP_KEY": "API Adzuna",
    "GMAIL_ADRESSE": "alertes Gmail et envoi des mails",
    "GMAIL_MOT_DE_PASSE_APPLI": "alertes Gmail et envoi des mails",
}

# Lit .env s'il existe. Les variables déjà définies dans l'environnement
# (par exemple sur GitHub Actions) restent prioritaires.
load_dotenv(RACINE / ".env")


def charger_config(chemin: Path | None = None) -> dict:
    """Lit config.yaml et le renvoie sous forme de dictionnaire."""
    chemin = Path(chemin) if chemin else CHEMIN_CONFIG
    with open(chemin, encoding="utf-8") as f:
        return yaml.safe_load(f)


def chemin_projet(relatif: str) -> Path:
    """Transforme un chemin relatif (tel qu'écrit dans config.yaml) en chemin complet."""
    chemin = Path(relatif)
    return chemin if chemin.is_absolute() else RACINE / chemin


def secret(nom: str) -> str | None:
    """Renvoie la valeur d'un secret, ou None s'il n'est pas renseigné."""
    return os.getenv(nom) or None


def secrets_manquants() -> list[str]:
    """Liste des secrets attendus qui ne sont pas encore renseignés."""
    return [nom for nom in SECRETS_ATTENDUS if not secret(nom)]
