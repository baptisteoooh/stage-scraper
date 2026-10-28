"""Tests des mails, avec un faux serveur Gmail : aucun mail réel n'est envoyé."""
import copy
import smtplib
from contextlib import closing
from datetime import date

import pytest

from stage_scraper import db, notifications, traitement
from stage_scraper.config import charger_config
from stage_scraper.offre import nouvelle_offre

CONFIG = charger_config()


def config_test(tmp_path, envoi_actif=False):
    config = copy.deepcopy(CONFIG)
    config["notifications"]["envoi_actif"] = envoi_actif
    config["notifications"]["dossier_apercus"] = str(tmp_path / "mails")
    return config


def base(tmp_path):
    """4 offres notées : 9 (alerte), 6 IA chez Doctolib (alerte), 6 ailleurs (récap), 3 (rien)."""
    conn = db.connecter(tmp_path / "t.db")
    db.initialiser(conn)
    offres = [
        nouvelle_offre(source="test", source_id="1", titre="Stage Computer Vision", entreprise="Gleamer",
                       lieu="Paris", date_publication="2026-10-20", lien="https://exemple.org/1"),
        nouvelle_offre(source="test", source_id="2", titre="Stage Data Scientist", entreprise="Doctolib",
                       lieu="Levallois-Perret", date_publication="2026-10-20", lien="javascript:alert(1)"),
        nouvelle_offre(source="test", source_id="3", titre="Stage Data Analyst <b>", entreprise="Withings",
                       lieu="Issy-les-Moulineaux", date_publication="2026-10-20", type_contrat="cdd"),
        nouvelle_offre(source="test", source_id="4", titre="Stage qualité", entreprise="Sanofi",
                       lieu="Paris", date_publication="2026-10-20"),
    ]
    db.enregistrer_offres(conn, offres, passage_id=1)
    traitement.traiter(conn, CONFIG, aujourd_hui=date(2026, 10, 28))
    for source_id, score, ia, section in (("1", 9, 1, "Santé"), ("2", 6, 1, "Santé"),
                                          ("3", 6, 0, "Santé"), ("4", 3, 0, "Santé")):
        conn.execute("UPDATE offres SET score = ?, poste_ia_data = ?, section = ?, resume = 'Résumé.', "
                     "pourquoi = 'Parce que.' WHERE source_id = ?", (score, ia, section, source_id))
    conn.commit()
    return conn


class FauxSMTP:
    envoyes = []
    refuser = False

    def __init__(self, serveur, port, timeout=None, context=None):
        assert (serveur, port) == ("smtp.gmail.com", 465)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, adresse, mot_de_passe):
        if FauxSMTP.refuser:
            raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")

    def send_message(self, message):
        FauxSMTP.envoyes.append(message)


@pytest.fixture
def faux_gmail(monkeypatch):
    FauxSMTP.envoyes, FauxSMTP.refuser = [], False
    monkeypatch.setattr(smtplib, "SMTP_SSL", FauxSMTP)
    secrets = {"GMAIL_ADRESSE": "moi@example.com", "GMAIL_MOT_DE_PASSE_APPLI": "secret-de-test"}
    monkeypatch.setattr(notifications, "secret", lambda nom: secrets.get(nom))
    return FauxSMTP


def ids(offres):
    return [o["source_id"] for o in offres]


def test_choix_des_offres(tmp_path):
    with closing(base(tmp_path)) as conn:
        assert ids(notifications.offres_alerte(conn, CONFIG)) == ["1", "2"]  # 9/10, puis IA chez Doctolib
        assert sorted(ids(notifications.offres_recap(conn, CONFIG))) == ["1", "2", "3"]  # note >= 5


def test_contenu_echappe_et_liens_surs(tmp_path):
    with closing(base(tmp_path)) as conn:
        sujet, texte, page = notifications.construire("recap", notifications.offres_recap(conn, CONFIG), CONFIG)
        assert "3 nouvelle(s) offre(s)" in sujet
        assert "Stage Data Analyst &lt;b&gt;" in page and "<b>>" not in page
        assert "javascript:" not in page and 'href="https://exemple.org/1"' in page
        assert "CDD" in page and "Santé (3)" in page
        assert "https://exemple.org/1" in texte


def test_envoi_desactive_ecrit_un_apercu(tmp_path, faux_gmail):
    config = config_test(tmp_path, envoi_actif=False)
    with closing(base(tmp_path)) as conn:
        bilans = notifications.apres_passage(conn, config, passage_id=2, auto=True)
        assert [b["nb"] for b in bilans] == [2, 3] and not any(b["envoye"] for b in bilans)
        assert (tmp_path / "mails" / "apercu_alerte.html").exists()
        assert faux_gmail.envoyes == []
        assert conn.execute("SELECT COUNT(*) FROM offres WHERE notifiee = 1").fetchone()[0] == 0


def test_alerte_puis_recap_sans_doublon(tmp_path, faux_gmail):
    config = config_test(tmp_path, envoi_actif=True)
    with closing(base(tmp_path)) as conn:
        # Passage manuel : l'alerte seulement
        bilans = notifications.apres_passage(conn, config, passage_id=2, auto=False)
        assert len(bilans) == 1 and bilans[0]["envoye"] and len(faux_gmail.envoyes) == 1
        assert faux_gmail.envoyes[0]["To"] == "moi@example.com"
        # Passage auto : plus d'alerte, le récap ne contient que l'offre pas encore envoyée
        bilans = notifications.apres_passage(conn, config, passage_id=3, auto=True)
        assert [b["nb"] for b in bilans] == [0, 1] and len(faux_gmail.envoyes) == 2
        assert "Withings" in faux_gmail.envoyes[1].get_body(("plain",)).get_content()
        # Plus rien à envoyer ensuite
        assert [b["nb"] for b in notifications.apres_passage(conn, config, 4, auto=True)] == [0, 0]
        runs = conn.execute("SELECT source, nb_offres FROM runs ORDER BY id").fetchall()
        assert [tuple(r) for r in runs] == [("mail_alerte", 2), ("mail_recap", 1)]


def test_mot_de_passe_refuse(tmp_path, faux_gmail):
    faux_gmail.refuser = True
    config = config_test(tmp_path, envoi_actif=True)
    with closing(base(tmp_path)) as conn:
        bilan = notifications.apres_passage(conn, config, passage_id=2, auto=False)[0]
        assert not bilan["envoye"] and "GMAIL_MOT_DE_PASSE_APPLI" in bilan["erreur"]
        assert "secret-de-test" not in bilan["erreur"]
        # les offres restent à notifier : elles repartiront au prochain passage
        assert len(notifications.offres_alerte(conn, config)) == 2


def test_resume_dans_le_bilan_du_passage(tmp_path):
    lignes = notifications.resume([{"type": "alerte", "nb": 0, "envoye": False, "apercu": None, "erreur": None},
                                   {"type": "recap", "nb": 3, "envoye": True, "apercu": None, "erreur": None}])
    assert lignes == ["  Alerte immédiate : aucune offre à signaler", "  Récap quotidien : mail envoyé (3 offre(s))"]
