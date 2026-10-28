"""Mails : alerte immédiate (à chaque passage) et récap quotidien (passage automatique).

Tant que `notifications.envoi_actif` vaut false dans config.yaml, rien n'est envoyé : chaque mail est
écrit en aperçu (fichier HTML dans data/mails/) et les offres restent « à notifier ».
Une offre n'est jamais notifiée deux fois (colonne `notifiee`).
"""
import html
import logging
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from . import db, prefiltre
from .config import chemin_projet, secret
from .requetes import SECTIONS, VISIBLE

log = logging.getLogger(__name__)

SERVEUR_SMTP, PORT_SMTP = "smtp.gmail.com", 465


def _maintenant() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


# --------------------------------------------------------------------------- choix des offres

def a_notifier(conn) -> list[dict]:
    """Offres gardées, notées par l'IA et jamais notifiées, de la meilleure note à la moins bonne."""
    return [dict(l) for l in conn.execute(
        f"SELECT * FROM offres WHERE {VISIBLE} AND score IS NOT NULL AND notifiee = 0 "
        "ORDER BY score DESC, date_publication DESC, id DESC")]


def merite_alerte(offre: dict, config: dict) -> bool:
    """Note ≥ seuil, ou poste IA/data chez une entreprise suivie (Doctolib compris)."""
    reglages = config["notifications"]
    if offre["score"] >= reglages["alerte_seuil_score"]:
        return True
    if reglages.get("alerte_ia_data_entreprise_suivie") and offre["poste_ia_data"]:
        entreprise = prefiltre.entreprise_suivie(offre["entreprise"], config)
        return bool(entreprise) and entreprise.get("groupe") != "ecosysteme"
    return False


def offres_alerte(conn, config: dict) -> list[dict]:
    return [o for o in a_notifier(conn) if merite_alerte(o, config)]


def offres_recap(conn, config: dict) -> list[dict]:
    minimum = config["notifications"].get("recap_score_min", config["scoring"]["seuils"]["a_regarder"])
    return [o for o in a_notifier(conn) if o["score"] >= minimum]


# --------------------------------------------------------------------------- contenu des mails

def _lien_sur(url: str | None) -> str | None:
    """Seuls les liens web classiques sont mis dans le mail."""
    return url if url and url.lower().startswith(("https://", "http://")) else None


def _carte(o: dict, avec_pourquoi: bool) -> str:
    e = lambda texte: html.escape(str(texte)) if texte else ""  # noqa: E731
    lien = _lien_sur(o["lien"])
    titre = f'<a href="{html.escape(lien, quote=True)}" style="color:#1a56db">{e(o["titre"])}</a>' if lien \
        else e(o["titre"])
    badges = "".join(
        f'<span style="background:{fond};color:#fff;border-radius:4px;padding:1px 6px;margin-right:4px;'
        f'font-size:12px">{e(texte)}</span>'
        for texte, fond in (("CDD", "#d97706") if o["type_contrat"] == "cdd" else (None, None),
                            ("IA / data", "#7c3aed") if o["poste_ia_data"] else (None, None))
        if texte)
    infos = " · ".join(e(x) for x in (o["duree"] or o["duree_ia"], o["date_debut"] or o["date_debut_ia"],
                                       o["gratification"]) if x)
    pourquoi = f'<div style="color:#555;font-size:13px">Pourquoi : {e(o["pourquoi"])}</div>' \
        if avec_pourquoi and o["pourquoi"] else ""
    return (
        '<div style="border:1px solid #e5e7eb;border-radius:8px;padding:10px 12px;margin:8px 0">'
        f'<div><b style="font-size:16px">{o["score"]}/10</b> &nbsp; <b>{titre}</b></div>'
        f'<div>{e(o["entreprise"]) or "Entreprise inconnue"} — {e(o["lieu"]) or "lieu inconnu"} {badges}</div>'
        f'<div style="margin-top:4px">{e(o["resume"])}</div>{pourquoi}'
        f'<div style="color:#555;font-size:13px">{infos}</div></div>')


def _texte(o: dict) -> str:
    morceaux = [f"{o['score']}/10  {o['titre']} — {o['entreprise'] or '?'} ({o['lieu'] or '?'})"]
    if o["resume"]:
        morceaux.append(f"   {o['resume']}")
    if _lien_sur(o["lien"]):
        morceaux.append(f"   {o['lien']}")
    return "\n".join(morceaux)


def construire(type_mail: str, offres: list[dict], config: dict) -> tuple[str, str, str]:
    """(sujet, texte brut, HTML) d'un mail 'alerte' ou 'recap'."""
    maxi = config["notifications"].get("max_offres_par_mail", 30)
    montrees, reste = offres[:maxi], len(offres) - maxi
    entreprises = ", ".join(dict.fromkeys(o["entreprise"] for o in montrees if o["entreprise"]))
    if type_mail == "alerte":
        sujet = f"🔥 Stage à regarder vite : {len(offres)} offre(s)" + (f" ({entreprises[:80]})" if entreprises else "")
        intro = "Ces offres viennent d'arriver et correspondent très bien à tes critères :"
        groupes = [("", montrees)]
    else:
        sujet = f"Récap stages du {datetime.now():%d/%m} : {len(offres)} nouvelle(s) offre(s)"
        intro = "Les nouvelles offres intéressantes depuis le dernier mail, de la meilleure note à la moins bonne :"
        groupes = [(s, [o for o in montrees if o["section"] == s]) for s in SECTIONS]
        groupes.append(("Autres", [o for o in montrees if o["section"] not in SECTIONS]))

    corps_html, corps_texte = [f"<p>{intro}</p>"], [intro, ""]
    for nom, liste in groupes:
        if not liste:
            continue
        if nom:
            corps_html.append(f'<h3 style="margin:16px 0 4px">{html.escape(nom)} ({len(liste)})</h3>')
            corps_texte.append(f"== {nom} ==")
        corps_html.extend(_carte(o, avec_pourquoi=(type_mail == "alerte")) for o in liste)
        corps_texte.extend(_texte(o) for o in liste)
        corps_texte.append("")
    if reste > 0:
        corps_html.append(f"<p>… et {reste} autre(s), à voir dans l'appli.</p>")
        corps_texte.append(f"… et {reste} autre(s), à voir dans l'appli.")
    pied = "Envoyé par Stage Scraper (streamlit run app.py pour tout voir)."
    corps_html.append(f'<p style="color:#888;font-size:12px">{pied}</p>')
    corps_texte.append(pied)
    page = ('<html><body style="font-family:Segoe UI,Arial,sans-serif;max-width:720px">'
            + "".join(corps_html) + "</body></html>")
    return sujet, "\n".join(corps_texte), page


# --------------------------------------------------------------------------- envoi

def adresses() -> tuple[str | None, str | None, str | None]:
    """(expéditeur, mot de passe d'application, destinataire)."""
    expediteur = secret("GMAIL_ADRESSE")
    return expediteur, secret("GMAIL_MOT_DE_PASSE_APPLI"), secret("EMAIL_DESTINATAIRE") or expediteur


def envoyer(sujet: str, texte: str, page_html: str) -> None:
    """Envoie un mail via le SMTP de Gmail. Lève RuntimeError avec un message clair (sans secret)."""
    expediteur, mot_de_passe, destinataire = adresses()
    if not expediteur or not mot_de_passe:
        raise RuntimeError("GMAIL_ADRESSE ou GMAIL_MOT_DE_PASSE_APPLI manquant dans .env")
    message = EmailMessage()
    message["Subject"], message["From"], message["To"] = sujet, f"Stage Scraper <{expediteur}>", destinataire
    message["Date"], message["Message-ID"] = formatdate(localtime=True), make_msgid(domain="stage-scraper.local")
    message.set_content(texte)
    message.add_alternative(page_html, subtype="html")
    try:
        with smtplib.SMTP_SSL(SERVEUR_SMTP, PORT_SMTP, timeout=30, context=ssl.create_default_context()) as smtp:
            smtp.login(expediteur, mot_de_passe)
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError("Gmail a refusé la connexion : vérifie GMAIL_ADRESSE et GMAIL_MOT_DE_PASSE_APPLI "
                           "(mot de passe d'application, pas ton mot de passe habituel)") from None
    except (smtplib.SMTPException, OSError) as e:
        raise RuntimeError(f"envoi impossible ({type(e).__name__})") from None


def ecrire_apercu(type_mail: str, sujet: str, page_html: str, config: dict):
    dossier = chemin_projet(config["notifications"].get("dossier_apercus", "data/mails"))
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"apercu_{type_mail}.html"
    chemin.write_text(page_html.replace("<body", f"<body data-sujet=\"{html.escape(sujet, quote=True)}\"", 1),
                      encoding="utf-8")
    return chemin


def _traiter(conn, config, type_mail: str, offres: list[dict], passage_id: int, auto: bool) -> dict:
    bilan = {"type": type_mail, "nb": len(offres), "envoye": False, "apercu": None, "erreur": None}
    if not offres:
        return bilan
    debut = _maintenant()
    sujet, texte, page = construire(type_mail, offres, config)
    if config["notifications"].get("envoi_actif"):
        try:
            envoyer(sujet, texte, page)
            conn.executemany("UPDATE offres SET notifiee = 1 WHERE id = ?", [(o["id"],) for o in offres])
            bilan["envoye"] = True
        except RuntimeError as e:
            bilan["erreur"] = str(e)
            log.warning("Mail %s non envoyé : %s", type_mail, e)
    else:
        bilan["apercu"] = str(ecrire_apercu(type_mail, sujet, page, config))
    db.journaliser_run(conn, passage_id=passage_id, date_debut=debut, date_fin=_maintenant(),
                       declenchement="auto" if auto else "manuel", source=f"mail_{type_mail}",
                       nb_offres=len(offres), erreurs=bilan["erreur"])
    conn.commit()
    return bilan


def apres_passage(conn, config: dict, passage_id: int, auto: bool) -> list[dict]:
    """Alerte immédiate à chaque passage, puis récap si passage automatique."""
    bilans = [_traiter(conn, config, "alerte", offres_alerte(conn, config), passage_id, auto)]
    if auto:
        bilans.append(_traiter(conn, config, "recap", offres_recap(conn, config), passage_id, auto))
    return bilans


def resume(bilans: list[dict]) -> list[str]:
    lignes = []
    for b in bilans:
        nom = "Alerte immédiate" if b["type"] == "alerte" else "Récap quotidien"
        if not b["nb"]:
            lignes.append(f"  {nom} : aucune offre à signaler")
        elif b["envoye"]:
            lignes.append(f"  {nom} : mail envoyé ({b['nb']} offre(s))")
        elif b["erreur"]:
            lignes.append(f"  {nom} : ERREUR, mail non envoyé ({b['erreur']})")
        else:
            lignes.append(f"  {nom} : envoi désactivé, aperçu écrit dans {b['apercu']} ({b['nb']} offre(s))")
    return lignes


def mail_de_test() -> None:
    """Petit mail pour vérifier que l'envoi marche (envoyé même si envoi_actif est false)."""
    envoyer("Stage Scraper : mail de test",
            "Si tu lis ceci, l'envoi des mails fonctionne.",
            "<html><body><p>Si tu lis ceci, l'envoi des mails fonctionne. 🎉</p></body></html>")
