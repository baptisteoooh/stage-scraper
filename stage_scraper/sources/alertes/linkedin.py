"""Parseur des mails d'alerte LinkedIn (expéditeur jobalerts-noreply@linkedin.com).

On lit la partie texte du mail. Chaque offre y forme un bloc, séparé des autres par une
ligne de tirets :

    Titre du poste
    Entreprise
    Lieu
    (lignes facultatives : « Cette entreprise recrute activement »...)
    Voir l’offre d’emploi : https://www.linkedin.com/comm/jobs/view/4485369389/?...

Le premier bloc commence par l'en-tête du mail (« Votre alerte Emploi pour... »), qu'on saute.
Le mail ne contient pas la description : l'IA note l'offre sur son titre, son entreprise et son lieu.
"""
import re
from email.message import Message
from email.utils import parsedate_to_datetime

from ...offre import nouvelle_offre

NOM = "alerte_linkedin"

_RE_LIEN = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)")
_RE_SEPARATEUR = re.compile(r"^\s*-{10,}\s*$", re.M)
# Lignes d'en-tête du mail, à sauter au début du premier bloc.
_EN_TETES = ("votre alerte emploi", "vous recevrez", "your job alert", "you'll receive")
_RE_NB_OFFRES = re.compile(r"^\d+\s+(nouvelles?|new)\b", re.I)


def reconnait(expediteur: str) -> bool:
    return expediteur.endswith("@linkedin.com") and "jobalerts" in expediteur


def extraire(message: Message) -> list[dict]:
    texte = partie_texte(message)
    date_mail = _date_du_mail(message)
    offres, vus = [], set()
    for bloc in _RE_SEPARATEUR.split(texte):
        lien = _RE_LIEN.search(bloc)
        if not lien or lien.group(1) in vus:
            continue
        lignes = [l.strip() for l in bloc[:bloc.find("http")].splitlines()]
        lignes = [l for l in lignes if l and not _est_en_tete(l)]
        if len(lignes) < 2:
            continue
        identifiant = lien.group(1)
        vus.add(identifiant)
        offres.append(nouvelle_offre(
            source=NOM,
            source_id=identifiant,
            titre=lignes[0],
            entreprise=lignes[1],
            lieu=lignes[2] if len(lignes) > 2 and not lignes[2].lower().startswith("voir l") else None,
            date_publication=date_mail,
            lien=f"https://www.linkedin.com/jobs/view/{identifiant}/",
            site_origine="LinkedIn",
        ))
    return offres


def partie_texte(message: Message) -> str:
    for partie in message.walk():
        if partie.get_content_type() == "text/plain":
            return partie.get_payload(decode=True).decode(partie.get_content_charset() or "utf-8", "replace")
    return ""


def _est_en_tete(ligne: str) -> bool:
    bas = ligne.lower()
    return bas.startswith(_EN_TETES) or bool(_RE_NB_OFFRES.match(ligne))


def _date_du_mail(message: Message) -> str | None:
    try:
        return parsedate_to_datetime(message["Date"]).date().isoformat()
    except (TypeError, ValueError):
        return None
