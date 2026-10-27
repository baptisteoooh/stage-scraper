"""Collecte des offres depuis les mails d'alerte rangés dans Gmail.

BAP crée des alertes sur LinkedIn, Indeed, WTTJ, HelloWork et JobTeaser.
Un filtre Gmail range ces mails sous un libellé (réglage `libelle` de config.yaml).
Ce module lit ce libellé en IMAP, avec un mot de passe d'application Google,
et confie chaque mail au parseur du site qui l'a envoyé (dossier alertes/).

Les mails sont lus en lecture seule : rien n'est supprimé, déplacé ni marqué comme lu.

Pour étudier le format des mails (avant d'écrire un parseur) :
    python -m stage_scraper.sources.gmail --telecharger
enregistre les mails du libellé dans data/emails/ (dossier ignoré par Git).
"""
import argparse
import email
import imaplib
import logging
import re
import sys
from datetime import date, timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr

from ..config import charger_config, chemin_projet, secret
from . import Contexte, Resultat
from .alertes import PARSEURS

NOM = "gmail"
SERVEUR = "imap.gmail.com"

log = logging.getLogger(__name__)


class ErreurGmail(Exception):
    """Connexion refusée, libellé introuvable..."""


def collecter(config: dict, contexte: Contexte) -> Resultat:
    reglages = config["sources"][NOM]
    resultat = Resultat()
    try:
        messages = lire_messages(reglages)
    except ErreurGmail as e:
        return Resultat(erreurs=[str(e)])

    sans_parseur: dict[str, int] = {}
    for message in messages:
        resultat.nb_requetes += 1
        expediteur = adresse_expediteur(message)
        parseur = trouver_parseur(expediteur)
        if parseur is None:
            sans_parseur[expediteur] = sans_parseur.get(expediteur, 0) + 1
            continue
        try:
            offres = parseur.extraire(message)
        except Exception as e:  # un mail mal formé ne doit pas bloquer les autres
            resultat.erreurs.append(f"mail « {sujet(message)} » ({parseur.NOM}) : {type(e).__name__} : {e}")
            continue
        log.info("  %s « %s » : %d offre(s)", parseur.NOM, sujet(message)[:60], len(offres))
        resultat.offres.extend(offres)

    if sans_parseur:
        detail = ", ".join(f"{adr} ({nb})" for adr, nb in sorted(sans_parseur.items()))
        resultat.message = f"mails sans parseur, ignorés : {detail}"
    return resultat


def lire_messages(reglages: dict) -> list[Message]:
    """Renvoie les mails du libellé reçus ces N derniers jours (réglage `jours_a_relire`)."""
    adresse = secret("GMAIL_ADRESSE")
    mot_de_passe = (secret("GMAIL_MOT_DE_PASSE_APPLI") or "").replace(" ", "")
    if not adresse or not mot_de_passe:
        raise ErreurGmail("GMAIL_ADRESSE ou GMAIL_MOT_DE_PASSE_APPLI manquant dans .env")

    libelle = reglages.get("libelle", "Alertes stage")
    depuis = date.today() - timedelta(days=reglages.get("jours_a_relire", 14))

    try:
        imap = imaplib.IMAP4_SSL(SERVEUR, 993, timeout=30)
    except OSError as e:
        raise ErreurGmail(f"impossible de joindre {SERVEUR} : {e}") from None
    try:
        try:
            imap.login(adresse, mot_de_passe)
        except imaplib.IMAP4.error:
            # On n'affiche jamais le mot de passe, seulement la marche à suivre.
            raise ErreurGmail("connexion à Gmail refusée : vérifie GMAIL_ADRESSE et le mot de passe "
                              "d'application dans .env") from None

        nom_exact = nom_du_libelle(imap, libelle)
        statut, _ = imap.select(_entre_guillemets(nom_exact), readonly=True) if nom_exact else ("NO", None)
        if statut != "OK":
            raise ErreurGmail(f"libellé « {libelle} » introuvable dans Gmail : crée-le "
                              "(Paramètres > Libellés) ou corrige `sources.gmail.libelle`")

        statut, donnees = imap.uid("SEARCH", None, "SINCE", depuis.strftime("%d-%b-%Y"))
        if statut != "OK":
            raise ErreurGmail("recherche des mails impossible")
        uids = donnees[0].split()

        messages = []
        for uid in uids:
            # BODY.PEEK : lit le mail sans le marquer comme lu.
            statut, contenu = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            if statut == "OK" and contenu and isinstance(contenu[0], tuple):
                messages.append(email.message_from_bytes(contenu[0][1]))
        return messages
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def nom_du_libelle(imap, libelle: str) -> str | None:
    """Nom exact du libellé dans Gmail, sans tenir compte des majuscules ("Alertes Stage" = "alertes stage")."""
    statut, lignes = imap.list()
    if statut != "OK":
        return None
    for ligne in lignes:
        nom = extraire_nom_dossier(ligne.decode("utf-8", "replace"))
        if nom and nom.casefold() == libelle.casefold():
            return nom
    return None


def extraire_nom_dossier(ligne: str) -> str | None:
    """Extrait le nom d'une ligne renvoyée par la commande IMAP LIST.

    Format : (attributs) "séparateur" nom   ->   par ex. (HasNoChildren) "/" "Alertes Stage"
    """
    fin_attributs = ligne.find(") ")
    if not ligne.startswith("(") or fin_attributs < 0:
        return None
    reste = ligne[fin_attributs + 2:]
    if reste.startswith("NIL "):
        nom = reste[4:]
    elif reste.startswith('"'):
        fin_separateur = reste.find('" ', 1)
        if fin_separateur < 0:
            return None
        nom = reste[fin_separateur + 2:]
    else:
        return None
    nom = nom.strip()
    if len(nom) >= 2 and nom[0] == nom[-1] == '"':
        nom = _sans_echappement(nom[1:-1])
    return nom


ANTISLASH = chr(92)


def _sans_echappement(texte: str) -> str:
    """Retire les antislashs d'échappement d'un nom entre guillemets (Dit \\"oui\\" -> Dit "oui")."""
    sortie, i = [], 0
    while i < len(texte):
        if texte[i] == ANTISLASH and i + 1 < len(texte):
            i += 1
        sortie.append(texte[i])
        i += 1
    return "".join(sortie)


def trouver_parseur(expediteur: str):
    """Renvoie le module parseur qui reconnaît cet expéditeur, ou None."""
    for parseur in PARSEURS:
        if parseur.reconnait(expediteur):
            return parseur
    return None


def adresse_expediteur(message: Message) -> str:
    return parseaddr(message.get("From", ""))[1].lower()


def sujet(message: Message) -> str:
    return str(make_header(decode_header(message.get("Subject", ""))))


def _entre_guillemets(libelle: str) -> str:
    """Les libellés contenant un espace doivent être entre guillemets en IMAP."""
    return '"' + libelle.replace("\\", "\\\\").replace('"', '\\"') + '"'


def telecharger(config: dict) -> None:
    """Enregistre les mails du libellé en .eml dans data/emails/, pour étudier leur format."""
    dossier = chemin_projet(config["sources"][NOM].get("dossier_emails", "data/emails"))
    dossier.mkdir(parents=True, exist_ok=True)
    messages = lire_messages(config["sources"][NOM])
    for message in messages:
        jour = email.utils.parsedate_to_datetime(message["Date"]).strftime("%Y-%m-%d")
        nom = re.sub(r"\(.)", lambda m: m.group(1), nom[1:-1])  # retire les antislashs d'échappement
        (dossier / f"{nom}.eml").write_bytes(message.as_bytes())
        print(f"  {nom}.eml")
    print(f"{len(messages)} mail(s) enregistré(s) dans {dossier}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Outils pour la source Gmail.")
    parser.add_argument("--telecharger", action="store_true",
                        help="enregistre les mails du libellé dans data/emails/")
    args = parser.parse_args()
    for flux in (sys.stdout, sys.stderr):
        flux.reconfigure(encoding="utf-8", errors="replace")
    if args.telecharger:
        try:
            telecharger(charger_config())
        except ErreurGmail as e:
            print(f"ERREUR : {e}")
    else:
        parser.print_help()
