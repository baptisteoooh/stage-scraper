"""Ma sélection : étapes, prochaine action, changements d'étape et offres trouvées ailleurs."""
from contextlib import closing
from datetime import date

import pytest

from stage_scraper import db, dossier, requetes, selection
from stage_scraper.offre import nouvelle_offre

AUJOURD_HUI = date(2026, 11, 19)


@pytest.fixture
def conn(tmp_path):
    with closing(db.connecter(tmp_path / "s.db")) as c:
        db.initialiser(c)
        db.enregistrer_offres(c, [
            nouvelle_offre(source="test", source_id=str(i), titre=titre, entreprise=entreprise, lieu="Paris")
            for i, (titre, entreprise) in enumerate([("Stage Data IA", "Doctolib"), ("Stage ML", "Owkin"),
                                                      ("Stage Data Analyst", "Withings"), ("Stage CV", "Gleamer")],
                                                     start=1)], passage_id=1)
        yield c


def candidater(conn, offre_id, statut="à postuler", **dates):
    i = requetes.creer_candidature(conn, offre_id=offre_id)
    requetes.modifier_candidature(conn, i, statut=statut, **dates)
    return i


def test_etapes_et_prochaine_action(conn):
    doctolib = candidater(conn, 1)
    owkin = candidater(conn, 2, "postulé", date_candidature="2026-11-11", date_relance="2026-11-18")
    withings = candidater(conn, 3, "entretien", date_entretien="2026-11-26 14:00")
    gleamer = candidater(conn, 4, "refus")
    rangees = selection.par_etape(conn, AUJOURD_HUI)
    assert {nom: [f["id"] for f in liste] for nom, liste in rangees.items()} == {
        "preparation": [doctolib], "envoyee": [owkin], "entretien": [withings], "terminee": [gleamer]}
    actions = {f["entreprise"]: f["action"] for f in selection.fiches(conn, AUJOURD_HUI)}
    assert actions == {"Doctolib": "preparer", "Owkin": "relancer", "Withings": "entretien", "Gleamer": None}
    assert [f["entreprise"] for f in selection.fiches(conn, AUJOURD_HUI)][:2] == ["Owkin", "Withings"]  # urgent d'abord

    # une fois la lettre écrite, il reste à l'envoyer
    d = dossier.ouvrir(conn, 1)
    dossier.ajouter_version(conn, d, "Madame, Monsieur…", "premier jet", "faux")
    f = selection.fiche(conn, doctolib, AUJOURD_HUI)
    assert (f["action"], f["lettre_prete"], f["lettre_courante"]) == ("envoyer", True, "Madame, Monsieur…")
    assert f["titre"] == "Stage Data IA" and f["lieu"] == "Paris"

    # relance pas encore due, entretien passé : rien à faire
    requetes.modifier_candidature(conn, owkin, date_relance="2026-11-25")
    requetes.modifier_candidature(conn, withings, date_entretien="2026-11-10")
    actions = {f["entreprise"]: f["action"] for f in selection.fiches(conn, AUJOURD_HUI)}
    assert actions["Owkin"] is None and actions["Withings"] is None
    assert selection.compter(conn) == {"preparation": 1, "envoyee": 1, "entretien": 1, "terminee": 1, "actions": 1}


def test_changer_d_etape_puis_annuler(conn):
    i = candidater(conn, 1)
    avant = selection.changer_etape(conn, i, "envoyee", relance_jours=7, aujourd_hui=AUJOURD_HUI)
    c = requetes.candidature(conn, i)
    assert (c["statut"], c["date_candidature"], c["date_relance"]) == ("postulé", "2026-11-19", "2026-11-26")
    selection.noter_relance(conn, i, 7, date(2026, 11, 26))
    selection.changer_etape(conn, i, "envoyee")                        # déjà envoyée : reste « relancé »
    assert requetes.candidature(conn, i)["statut"] == "relancé"
    selection.changer_etape(conn, i, "terminee", resultat="accepté")
    assert requetes.candidature(conn, i)["statut"] == "accepté"
    with pytest.raises(ValueError):
        selection.changer_etape(conn, i, "terminee", resultat="peut-être")
    selection.annuler(conn, avant)
    assert requetes.candidature(conn, i)["statut"] == "à postuler"


def test_fixer_un_entretien(conn):
    i = candidater(conn, 1, "postulé", date_candidature="2026-11-11", date_relance="2026-11-18")
    selection.fixer_entretien(conn, i, "2026-11-26 14:00")
    c = requetes.candidature(conn, i)
    assert (c["statut"], c["date_entretien"], c["date_relance"]) == ("entretien", "2026-11-26 14:00", None)


def test_offre_trouvee_ailleurs(conn):
    i = requetes.ajouter_a_la_main(conn, "Sanofi", "Stage data", "https://exemple.org/sanofi", "postulé", None,
                                   date(2026, 11, 10), description="Analyse de données cliniques en Python.")
    f = selection.fiche(conn, i, AUJOURD_HUI)
    assert f["trouvee_ailleurs"] and f["etape"] == "envoyee" and f["action"] == "relancer"
    assert f["description"] == "Analyse de données cliniques en Python."      # l'IA pourra l'analyser
    o = requetes.offre(conn, f["offre_id"])
    assert (o["source"], o["vue"], o["notifiee"]) == ("manuel", 1, 1)         # jamais dans les mails
    assert f["offre_id"] not in {x["id"] for x in requetes.offres_a_trier(conn)}


def test_garder_une_offre_la_retire_d_a_trier(conn):
    assert 1 in {o["id"] for o in requetes.offres_a_trier(conn)}
    candidater(conn, 1)
    assert 1 not in {o["id"] for o in requetes.offres_a_trier(conn)}
    assert requetes.offre(conn, 1)["vue"] == 1


def test_migration_rattache_les_candidatures_manuelles(tmp_path):
    with closing(db.connecter(tmp_path / "v8.db")) as c:
        db.initialiser(c)
        c.execute("INSERT INTO candidatures (entreprise, poste, statut) VALUES ('Servier', 'Stage biostat', 'postulé')")
        c.execute("PRAGMA user_version = 8")
        c.commit()
        db.initialiser(c)                                                      # applique la migration 9
        cand = c.execute("SELECT * FROM candidatures").fetchone()
        o = requetes.offre(c, cand["offre_id"])
        assert (o["source"], o["titre"], o["entreprise"], o["notifiee"]) == ("manuel", "Stage biostat", "Servier", 1)
        assert c.execute("PRAGMA user_version").fetchone()[0] == db.VERSION_SCHEMA
