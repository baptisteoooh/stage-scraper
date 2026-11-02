"""Tests du parseur des mails d'alerte LinkedIn, avec un faux mail au format réel."""
from email.message import EmailMessage

from stage_scraper.sources.alertes import linkedin

CORPS = """Votre alerte Emploi pour stage data science (Paris et périphérie)
2 nouvelles offres d’emploi correspondent à vos préférences.

Stage IA pour la santé
GE HealthCare
Buc

Cette entreprise recrute activement
Voir l’offre d’emploi : https://www.linkedin.com/comm/jobs/view/4485369389/?trk=eml-email&refId=abc

---------------------------------------------------------

Internship - Embeddings for Epidemic Intelligence
World Organisation for Animal Health
Ville de Paris
Postulez avec un CV et un profil
Voir l’offre d’emploi : https://www.linkedin.com/comm/jobs/view/4483479043/

---------------------------------------------------------

Voir toutes les offres d’emploi sur LinkedIn : https://www.linkedin.com/comm/jobs/search-results/
"""


def faux_mail() -> EmailMessage:
    m = EmailMessage()
    m["From"] = "LinkedIn <jobalerts-noreply@linkedin.com>"
    m["Subject"] = "Votre alerte Emploi"
    m["Date"] = "Sat, 31 Oct 2026 09:12:00 +0000"
    m.set_content(CORPS)
    m.add_alternative("<html><body>version HTML</body></html>", subtype="html")
    return m


def test_reconnait():
    assert linkedin.reconnait("jobalerts-noreply@linkedin.com")
    assert not linkedin.reconnait("messages-noreply@linkedin.com")
    assert not linkedin.reconnait("alert@indeed.com")


def test_extrait_les_offres_du_mail():
    offres = linkedin.extraire(faux_mail())
    assert [o["source_id"] for o in offres] == ["4485369389", "4483479043"]
    premiere, seconde = offres
    assert premiere["titre"] == "Stage IA pour la santé"
    assert premiere["entreprise"] == "GE HealthCare"
    assert premiere["lieu"] == "Buc"
    assert premiere["lien"] == "https://www.linkedin.com/jobs/view/4485369389/"  # sans le suivi LinkedIn
    assert premiere["date_publication"] == "2026-10-31"
    assert premiere["source"] == "alerte_linkedin"
    assert seconde["entreprise"] == "World Organisation for Animal Health"
    assert seconde["lieu"] == "Ville de Paris"
