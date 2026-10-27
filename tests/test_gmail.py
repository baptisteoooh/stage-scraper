"""Tests de la source Gmail, avec de faux mails (aucune connexion à Gmail)."""
from email.message import EmailMessage
from types import SimpleNamespace

from stage_scraper.sources import Contexte, gmail

CONFIG = {"sources": {"gmail": {"libelle": "Alertes stage", "jours_a_relire": 14}}}


def faux_mail(expediteur: str, sujet: str = "Nouvelles offres") -> EmailMessage:
    m = EmailMessage()
    m["From"] = expediteur
    m["Subject"] = sujet
    m.set_content("corps")
    return m


def faux_parseur(nom: str, domaine: str, offres=None, plante=False):
    def extraire(message):
        if plante:
            raise ValueError("format inattendu")
        return offres or []
    return SimpleNamespace(NOM=nom, reconnait=lambda adr: adr.endswith(domaine), extraire=extraire)


def test_expediteur_et_sujet():
    m = faux_mail('"LinkedIn" <JobAlerts-NoReply@LinkedIn.com>', "=?utf-8?q?Stage_d=C3=A9veloppeur?=")
    assert gmail.adresse_expediteur(m) == "jobalerts-noreply@linkedin.com"
    assert gmail.sujet(m) == "Stage développeur"


def test_chaque_mail_va_a_son_parseur(monkeypatch):
    offre = {"titre": "Stage IA"}
    monkeypatch.setattr(gmail, "PARSEURS", [
        faux_parseur("alerte_linkedin", "@linkedin.com", [offre]),
        faux_parseur("alerte_indeed", "@indeed.com", plante=True),
    ])
    monkeypatch.setattr(gmail, "lire_messages", lambda reglages: [
        faux_mail("jobalerts-noreply@linkedin.com"),
        faux_mail("alert@indeed.com", "Offres Indeed"),
        faux_mail("newsletter@exemple.fr"),
    ])
    resultat = gmail.collecter(CONFIG, Contexte())
    assert resultat.offres == [offre]
    assert resultat.nb_requetes == 3
    assert len(resultat.erreurs) == 1 and "Offres Indeed" in resultat.erreurs[0]  # le plantage n'arrête pas tout
    assert "newsletter@exemple.fr" in resultat.message


def test_secrets_manquants(monkeypatch):
    monkeypatch.delenv("GMAIL_MOT_DE_PASSE_APPLI", raising=False)
    monkeypatch.setattr(gmail, "secret", lambda nom: None)
    resultat = gmail.collecter(CONFIG, Contexte())
    assert resultat.offres == [] and "manquant" in resultat.erreurs[0]


def test_libelle_entre_guillemets():
    assert gmail._entre_guillemets("Alertes stage") == '"Alertes stage"'


def test_nom_du_libelle_sans_tenir_compte_des_majuscules():
    lignes = [rb'(\HasNoChildren) "/" "INBOX"', rb'(\HasNoChildren) "/" "Alertes Stage"',
              rb'(\All) "/" "[Gmail]/Tous les messages"']
    imap = SimpleNamespace(list=lambda: ("OK", lignes))
    assert gmail.nom_du_libelle(imap, "Alertes stage") == "Alertes Stage"
    assert gmail.nom_du_libelle(imap, "Autre") is None
    assert gmail.extraire_nom_dossier(r'(\HasNoChildren) "/" Perso') == "Perso"
    assert gmail.extraire_nom_dossier(r'(\HasNoChildren) "/" "Dit \"oui\""') == 'Dit "oui"'
