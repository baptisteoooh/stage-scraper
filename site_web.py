"""Lance le site de Stage Scraper et l'ouvre dans le navigateur.

    python site_web.py            (http://127.0.0.1:8000)
    python site_web.py --port 8010 --sans-navigateur
    python site_web.py --comptes  (site partagé : connexion, un dossier par personne ; voir le README)
    python site_web.py --en-ligne (sur le serveur : comme --comptes, sans navigateur, derrière Caddy en HTTPS)
    python site_web.py --creer-admin   (crée le premier compte, celui de BAP, sans passer par le site)

Le site n'écoute que sur cet ordinateur (127.0.0.1). Sur le serveur, c'est Caddy qui le rend visible sur Internet,
en HTTPS : il transmet chaque visite au site en précisant « X-Forwarded-Proto: https », et uvicorn fait confiance
à cette précision seulement quand elle vient de la machine elle-même (le cookie de connexion est alors « Secure » :
le navigateur ne l'envoie jamais en clair). Ctrl+C dans le terminal pour l'arrêter.
"""
import argparse
import getpass
import os
import sys
import threading
import webbrowser

import uvicorn


def main() -> int:
    parser = argparse.ArgumentParser(description="Site de Stage Scraper")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--sans-navigateur", action="store_true", help="ne pas ouvrir le navigateur")
    parser.add_argument("--comptes", action="store_true", help="site partagé : il faut se connecter, chacun a ses données")
    parser.add_argument("--en-ligne", action="store_true",
                        help="site sur Internet (serveur) : --comptes, sans navigateur, premier compte seulement "
                             "avec --creer-admin")
    parser.add_argument("--creer-admin", action="store_true", help="crée le premier compte (BAP) puis s'arrête")
    args = parser.parse_args()
    if args.creer_admin:
        return creer_admin()
    if args.comptes or args.en_ligne:
        os.environ["STAGE_SCRAPER_COMPTES"] = "1"
    if args.en_ligne:
        os.environ["STAGE_SCRAPER_EN_LIGNE"] = "1"
    adresse = f"http://127.0.0.1:{args.port}"
    if not (args.sans_navigateur or args.en_ligne):
        threading.Timer(1.2, webbrowser.open, args=(adresse,)).start()
    print(f"Stage Scraper : {adresse}  (Ctrl+C pour arrêter)", flush=True)
    uvicorn.run("stage_scraper.web.serveur:app", host="127.0.0.1", port=args.port, log_level="warning",
                proxy_headers=True, forwarded_allow_ips="127.0.0.1", server_header=False)
    return 0


def creer_admin() -> int:
    """Le premier compte, tapé dans le terminal du serveur (le mot de passe ne s'affiche pas)."""
    from stage_scraper import comptes

    if not comptes.aucun_compte():
        print("Le premier compte existe déjà. Les autres comptes se créent avec un lien d'invitation (Réglages).")
        return 1
    nom = input("Nom du compte admin (minuscules, sans espace) : ").strip().lower()
    mot_de_passe = getpass.getpass("Mot de passe (8 caractères ou plus, invisible) : ")
    if getpass.getpass("Le même, encore une fois : ") != mot_de_passe:
        print("Les deux mots de passe sont différents : rien n'a été créé.")
        return 1
    try:
        compte = comptes.creer_admin(nom, mot_de_passe)
    except comptes.CompteRefuse as e:
        print(f"Refusé : {e}")
        return 1
    print(f"Compte admin « {compte.nom} » créé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
