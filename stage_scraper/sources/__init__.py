"""Modules de collecte : un fichier par source (google_jobs.py, ...).

Chaque module expose une fonction `collecter(config, contexte) -> Resultat`.
Une source qui plante ne doit jamais bloquer les autres : le module renvoie ce
qu'il a pu récupérer, avec ses erreurs, et collecte.py écrit tout dans le journal.
"""
from dataclasses import dataclass, field


@dataclass
class Contexte:
    """Informations sur le passage en cours, transmises à chaque source."""
    auto: bool = False              # True = lancé par la tâche planifiée
    explicite: bool = False         # True = source demandée nommément (python run.py --source ...)
    max_requetes: int | None = None  # limite pour les tests


@dataclass
class Resultat:
    """Ce que renvoie une source après sa collecte."""
    offres: list[dict] = field(default_factory=list)
    nb_requetes: int = 0
    erreurs: list[str] = field(default_factory=list)
    message: str | None = None      # info pour l'utilisateur (ex. "ignorée en passage manuel")
