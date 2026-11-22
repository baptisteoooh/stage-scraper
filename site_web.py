"""Lance le site de Stage Scraper et l'ouvre dans le navigateur.

    python site_web.py            (http://127.0.0.1:8000)
    python site_web.py --port 8010 --sans-navigateur
    python site_web.py --comptes  (site partagé : connexion, un dossier par personne ; voir le README)

Le site n'est visible que depuis cet ordinateur. Ctrl+C dans le terminal pour l'arrêter.
"""
import argparse
import os
import threading
import webbrowser

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Site de Stage Scraper")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--sans-navigateur", action="store_true", help="ne pas ouvrir le navigateur")
    parser.add_argument("--comptes", action="store_true", help="site partagé : il faut se connecter, chacun a ses données")
    args = parser.parse_args()
    if args.comptes:
        os.environ["STAGE_SCRAPER_COMPTES"] = "1"
    adresse = f"http://127.0.0.1:{args.port}"
    if not args.sans_navigateur:
        threading.Timer(1.2, webbrowser.open, args=(adresse,)).start()
    print(f"Stage Scraper : {adresse}  (Ctrl+C pour arrêter)")
    uvicorn.run("stage_scraper.web.serveur:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
