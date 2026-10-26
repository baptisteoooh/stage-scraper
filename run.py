"""Lancement d'un passage en ligne de commande.

    python run.py          passage manuel
    python run.py --auto   passage automatique (tâche planifiée, envoie le récap du jour)

Pour l'instant (étape 1), le script prépare la base et affiche son état.
La collecte arrive à l'étape 2.
"""
import argparse
import sys
from contextlib import closing

from stage_scraper import db
from stage_scraper.config import SECRETS_ATTENDUS, charger_config, chemin_projet, secrets_manquants


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collecte et notation des offres de stage.")
    parser.add_argument("--auto", action="store_true", help="passage automatique (tâche planifiée)")
    args = parser.parse_args(argv)

    config = charger_config()
    chemin_db = chemin_projet(config["general"]["base_de_donnees"])

    with closing(db.connecter(chemin_db)) as conn:
        db.initialiser(conn)
        print(f"Base de données : {chemin_db}")
        for table, nb in db.compter_lignes(conn).items():
            print(f"  - {table:<13} {nb} ligne(s)")

    manquants = secrets_manquants()
    if manquants:
        print("\nSecrets pas encore renseignés dans .env :")
        for nom in manquants:
            print(f"  - {nom} ({SECRETS_ATTENDUS[nom]})")
    else:
        print("\nTous les secrets sont renseignés.")

    mode = "automatique" if args.auto else "manuel"
    print(f"\nMode : {mode}. Aucune source branchée pour l'instant (étape 2 : France Travail).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
