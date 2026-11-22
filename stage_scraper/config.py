"""Chargement des paramètres (config.yaml) et des secrets (.env).

Tous les chemins sont calculés à partir du dossier du projet : aucun chemin
en dur, pour que le code marche aussi ailleurs (autre PC, GitHub Actions).
"""
import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Dossier racine du projet (celui qui contient config.yaml).
RACINE = Path(__file__).resolve().parent.parent
CHEMIN_CONFIG = RACINE / "config.yaml"

# Secrets attendus dans .env, avec leur usage.
SECRETS_ATTENDUS = {
    "GEMINI_API_KEY": "scoring IA (Gemini)",
    "ANTHROPIC_API_KEY": "fiches de Ma sélection : analyse et lettre (Claude, crédit prépayé)",
    "FRANCE_TRAVAIL_CLIENT_ID": "API France Travail",
    "FRANCE_TRAVAIL_CLIENT_SECRET": "API France Travail",
    "SERPAPI_API_KEY": "Google Jobs via SerpApi",
    "CAREERJET_API_KEY": "API Careerjet",
    "GMAIL_ADRESSE": "alertes Gmail et envoi des mails",
    "GMAIL_MOT_DE_PASSE_APPLI": "alertes Gmail et envoi des mails",
}

# Secrets propres à chaque compte (site en mode comptes) : chacun a sa clé, jamais celle de BAP.
SECRETS_PERSONNELS = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY")
# Secrets de BAP prêtés aux amis : la clé partenaire Careerjet (prévue pour un site qui sert ses visiteurs),
# avec un plafond par ami et par jour (voir comptes.py).
SECRETS_PARTAGES = ("CAREERJET_API_KEY",)


@dataclass(frozen=True)
class Compte:
    """La personne pour qui le code travaille. `dossier` None = le compte de BAP (fichiers du projet)."""
    nom: str
    admin: bool = False
    dossier: Path | None = None

    @property
    def config(self) -> Path:
        return self.dossier / "config.yaml" if self.dossier else CHEMIN_CONFIG

    @property
    def cles(self) -> Path | None:
        return self.dossier / "cles.env" if self.dossier else None


# Compte en cours (posé par le site à chaque requête). None = usage local habituel, sans comptes.
COMPTE: ContextVar[Compte | None] = ContextVar("compte", default=None)


def lire_cles(chemin: Path | None) -> dict[str, str]:
    """Les clés d'un compte (fichier cles.env de son dossier, format NOM=valeur)."""
    if not chemin or not chemin.exists():
        return {}
    cles = {}
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        nom, egal, valeur = ligne.partition("=")
        if egal and nom.strip() and not nom.lstrip().startswith("#"):
            cles[nom.strip()] = valeur.strip()
    return cles


# Lit .env s'il existe. Les variables déjà définies dans l'environnement
# (par exemple sur GitHub Actions) restent prioritaires.
load_dotenv(RACINE / ".env")


def charger_config(chemin: Path | None = None) -> dict:
    """Lit config.yaml (celui du compte en cours, s'il y en a un) et le renvoie sous forme de dictionnaire."""
    compte = COMPTE.get()
    chemin = Path(chemin) if chemin else (compte.config if compte else CHEMIN_CONFIG)
    with open(chemin, encoding="utf-8") as f:
        return yaml.safe_load(f)


def chemin_projet(relatif: str) -> Path:
    """Transforme un chemin relatif (tel qu'écrit dans config.yaml) en chemin complet : depuis le dossier du
    projet, ou depuis le dossier du compte en cours (sa base, son CV…)."""
    chemin = Path(relatif)
    compte = COMPTE.get()
    return chemin if chemin.is_absolute() else ((compte.dossier if compte and compte.dossier else RACINE) / chemin)


def secret(nom: str) -> str | None:
    """Renvoie la valeur d'un secret, ou None s'il n'est pas renseigné.
    Pour le compte d'un ami : sa propre clé IA, et aucun des autres secrets de BAP (Gmail, SerpApi, Careerjet…)."""
    compte = COMPTE.get()
    if compte and compte.dossier:
        if nom in SECRETS_PARTAGES:
            return os.getenv(nom) or None
        return (lire_cles(compte.cles).get(nom) or None) if nom in SECRETS_PERSONNELS else None
    return os.getenv(nom) or None


def ou_mettre_la_cle() -> str:
    """Où ajouter sa clé Gemini : dans .env pour BAP, dans Mon profil pour un ami."""
    compte = COMPTE.get()
    return "ajoute ta clé dans Mon profil" if compte and compte.dossier else "GEMINI_API_KEY dans .env"


def secrets_manquants() -> list[str]:
    """Liste des secrets attendus qui ne sont pas encore renseignés."""
    return [nom for nom in SECRETS_ATTENDUS if not secret(nom)]
