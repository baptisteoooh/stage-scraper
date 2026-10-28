"""Lancement d'un passage en ligne de commande.

    python run.py                          passage manuel (toutes les sources actives)
    python run.py --auto                   passage automatique (tâche planifiée)
    python run.py --source google_jobs     une seule source (peut être répété)
    python run.py --source google_jobs --max-requetes 1    test avec une seule requête
    python run.py --verifier               état de la base et des secrets, sans collecter
"""
import argparse
import logging
import sys
from contextlib import closing

from stage_scraper import collecte, db, traitement
from stage_scraper.config import SECRETS_ATTENDUS, charger_config, chemin_projet, secrets_manquants


def main(argv: list[str] | None = None) -> int:
    utf8_sur_la_console()
    parser = argparse.ArgumentParser(description="Collecte et notation des offres de stage.")
    parser.add_argument("--auto", action="store_true", help="passage automatique (tâche planifiée)")
    parser.add_argument("--source", action="append", choices=list(collecte.SOURCES),
                        help="ne lancer que cette source (même si elle est désactivée ou réservée au mode auto)")
    parser.add_argument("--max-requetes", type=int, help="nombre maximum de requêtes par source (pour tester)")
    parser.add_argument("--verifier", action="store_true", help="affiche l'état de la base et des secrets")
    parser.add_argument("--retraiter", action="store_true",
                        help="refait le pré-filtre et le dédoublonnage de toutes les offres, sans collecter "
                             "(après un changement de config.yaml)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

    config = charger_config()
    chemin_db = chemin_projet(config["general"]["base_de_donnees"])

    with closing(db.connecter(chemin_db)) as conn:
        db.initialiser(conn)
        if args.verifier:
            afficher_etat(conn, chemin_db)
            return 0
        if args.retraiter:
            afficher_traitement(traitement.traiter(conn, config, tout=True))
            return 0

        passage_id, bilan = collecte.lancer_passage(
            conn, config, auto=args.auto,
            sources_demandees=args.source, max_requetes=args.max_requetes,
        )
        bilan_traitement = traitement.traiter(conn, config)

    mode = "automatique" if args.auto else "manuel"
    print(f"\nPassage n°{passage_id} ({mode})")
    if not bilan:
        print("  Aucune source active.")
    for ligne in bilan:
        print(f"  - {ligne['source']} : {ligne['nb_offres']} offre(s) dont {ligne['nb_nouvelles']} nouvelle(s), "
              f"{ligne['nb_requetes']} requête(s)")
        if ligne["message"]:
            print(f"      {ligne['message']}")
        for erreur in ligne["erreurs"]:
            print(f"      ERREUR : {erreur}")
    afficher_traitement(bilan_traitement)
    return 0


def afficher_traitement(bilan: dict) -> None:
    print(f"  Tri des {bilan['traitees']} offre(s) à traiter : {bilan['gardees']} gardée(s), "
          f"{bilan['exclues']} exclue(s) par le pré-filtre, {bilan['doublons']} doublon(s)")


def utf8_sur_la_console() -> None:
    """Évite un plantage sur les accents quand la sortie va dans un fichier (tâche planifiée)."""
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def afficher_etat(conn, chemin_db) -> None:
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


if __name__ == "__main__":
    sys.exit(main())
