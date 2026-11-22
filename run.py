"""Lancement d'un passage en ligne de commande.

    python run.py                          passage manuel (toutes les sources actives)
    python run.py --auto                   passage automatique (tâche planifiée)
    python run.py --source google_jobs     une seule source (peut être répété)
    python run.py --source google_jobs --max-requetes 1    test avec une seule requête
    python run.py --verifier               état de la base et des secrets, sans collecter
    python run.py --retraiter              refait le tri de toutes les offres (après un changement de config)
    python run.py --noter                  note les offres en attente avec l'IA, sans collecter
    python run.py --test-mail              envoie un mail de test à ton adresse (vérifie l'envoi Gmail)

Site partagé (comptes d'amis) : après un passage complet, chaque ami reçoit les nouvelles offres et les note
avec sa propre clé Gemini (aucune requête de plus vers les sites).
"""
import argparse
import logging
import sys
from contextlib import closing

from stage_scraper import collecte, comptes, db, notifications, pipeline, scoring
from stage_scraper.config import COMPTE, SECRETS_ATTENDUS, charger_config, chemin_projet, secrets_manquants


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
    parser.add_argument("--noter", action="store_true",
                        help="note avec l'IA les offres en attente, sans collecter (après avoir ajouté la clé)")
    parser.add_argument("--test-mail", action="store_true",
                        help="envoie un mail de test à ton adresse, même si l'envoi est désactivé")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

    config = charger_config()
    if args.test_mail:
        try:
            notifications.mail_de_test()
        except RuntimeError as e:
            print(f"Mail de test non envoyé : {e}")
            return 1
        print(f"Mail de test envoyé à {notifications.adresses()[2]}.")
        return 0
    chemin_db = chemin_projet(config["general"]["base_de_donnees"])

    with closing(db.connecter(chemin_db)) as conn:
        db.initialiser(conn)
        if args.verifier:
            afficher_etat(conn, chemin_db)
            return 0
        if args.retraiter:
            print(pipeline.resume_tri(pipeline.retrier(conn, config)))
            return 0
        if args.noter:
            passage_id = db.nouveau_passage_id(conn)
            print("\n".join(pipeline.resume_scoring(scoring.noter_nouvelles(conn, config, passage_id, args.auto))))
            return 0

        bilan = pipeline.passage_complet(conn, config, auto=args.auto, sources=args.source,
                                         max_requetes=args.max_requetes)

    print("\n" + "\n".join(pipeline.resume_texte(bilan)))
    if not args.source:
        passages_des_amis(chemin_db, auto=args.auto)
    return 0


def passages_des_amis(base_commune, auto: bool = False) -> list[str]:
    """Comptes d'amis (site partagé) : chacun reprend les offres de ce passage et les note avec sa clé.
    Un ami qui plante (clé refusée, base abîmée…) ne bloque pas les autres. Renvoie les lignes affichées."""
    if not (comptes.dossier_comptes() / "comptes.db").exists():
        return []
    lignes = []
    for ami in comptes.amis():
        jeton = COMPTE.set(ami)
        try:
            with closing(db.connecter(ami.dossier / "stages.db")) as conn:
                db.initialiser(conn)
                bilan = pipeline.passage_complet(conn, charger_config(), auto=auto, commune=base_commune)
            source, notes = bilan["sources"][0], bilan["scoring"]
            lignes.append(f"Compte {ami.nom} : {source['nb_nouvelles']} nouvelle(s) offre(s), {notes['notees']} notée(s)"
                          + (f" ({notes['message']})" if notes.get("message") else ""))
        except Exception as e:   # un compte ne doit pas bloquer les autres
            logging.getLogger(__name__).exception("Passage du compte %s", ami.nom)
            lignes.append(f"Compte {ami.nom} : erreur ({type(e).__name__})")
        finally:
            COMPTE.reset(jeton)
    for ligne in lignes:
        print(ligne)
    return lignes


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
