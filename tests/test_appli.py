"""Tests de l'appli : requêtes, export Excel, réglages, et affichage de chaque page (sans navigateur)."""
import copy
import io
from contextlib import closing
from datetime import date

import openpyxl
import pytest
from streamlit.testing.v1 import AppTest

from stage_scraper import config as module_config
from stage_scraper import db, expiration, export, reglages, requetes, traitement
from stage_scraper.config import CHEMIN_CONFIG, RACINE, charger_config
from stage_scraper.offre import nouvelle_offre

CONFIG = charger_config()


def base(chemin):
    conn = db.connecter(chemin)
    db.initialiser(conn)
    offres = [
        nouvelle_offre(source="test", source_id="1", titre="Stage Machine Learning imagerie", entreprise="Gleamer",
                       lieu="Paris", date_publication="2026-10-20", lien="https://exemple.org/1"),
        nouvelle_offre(source="test", source_id="2", titre="Stage Data Analyst", entreprise="Withings",
                       lieu="Issy-les-Moulineaux", date_publication="2026-10-21", type_contrat="cdd"),
        nouvelle_offre(source="test", source_id="3", titre="Alternance Data Scientist", entreprise="Owkin",
                       lieu="Paris", date_publication="2026-10-21"),
    ]
    db.enregistrer_offres(conn, offres, passage_id=1)
    traitement.traiter(conn, CONFIG, aujourd_hui=date(2026, 10, 28))
    conn.execute("UPDATE offres SET score = 9, categorie = 'À postuler vite', section = 'Santé', "
                 "resume = 'Segmentation d''images.', pourquoi = 'IA + medtech.' WHERE source_id = '1'")
    conn.commit()
    return conn


# --------------------------------------------------------------------------- requêtes

def test_offres_visibles_et_tri(tmp_path):
    with closing(base(tmp_path / "t.db")) as conn:
        visibles = requetes.offres_visibles(conn)
        assert [o["source_id"] for o in visibles] == ["1", "2"]  # notée d'abord, l'alternance est exclue
        assert len(requetes.offres_exclues(conn)) == 1
        assert requetes.statistiques(conn)["a_postuler_vite"] == 1
        assert len(requetes.offres_visibles(conn, "passage", requetes.dernier_passage(conn))) == 2


def test_pas_interesse_et_retour(tmp_path):
    with closing(base(tmp_path / "t.db")) as conn:
        requetes.marquer_pas_interesse(conn, 1, "  trop loin ")
        assert [o["id"] for o in requetes.offres_visibles(conn)] == [2]
        assert requetes.offres_pas_interesse(conn)[0]["raison"] == "trop loin"
        requetes.annuler_pas_interesse(conn, 1)
        assert len(requetes.offres_visibles(conn)) == 2 and requetes.offres_pas_interesse(conn) == []


def test_favori_aller_retour(tmp_path):
    with closing(base(tmp_path / "t.db")) as conn:
        assert requetes.offres_favorites(conn) == []
        assert requetes.basculer_favori(conn, 2) is True
        assert requetes.offre(conn, 2)["date_favori"]
        # un favori reste dans « Favoris » même vu et expiré
        requetes.marquer_vue(conn, 2)
        expiration.marquer_expiree(conn, 2)
        assert [o["id"] for o in requetes.offres_favorites(conn)] == [2]
        assert requetes.basculer_favori(conn, 2) is False
        assert requetes.offre(conn, 2)["date_favori"] is None and requetes.offres_favorites(conn) == []
        # retiré pendant la visite : encore affiché pour pouvoir annuler
        assert [o["id"] for o in requetes.offres_favorites(conn, {2})] == [2]


def test_tri_par_note_ou_par_date():
    offres = [
        {"id": 1, "score": 9, "date_publication": "2026-10-01", "date_collecte": "2026-10-02 08:00:00"},
        {"id": 2, "score": None, "date_publication": None, "date_collecte": "2026-11-10 08:00:00"},
        {"id": 3, "score": 6, "date_publication": "2026-11-05T10:00:00", "date_collecte": "2026-11-06 08:00:00"},
        {"id": 4, "score": 8, "date_publication": "2026-11-05", "date_collecte": "2026-11-05 08:00:00"},
    ]
    ids = lambda liste: [o["id"] for o in liste]  # noqa: E731
    assert ids(requetes.trier_offres(offres)) == [1, 4, 3, 2]  # note décroissante, non notées à la fin
    # date de publication, sinon de collecte ; à égalité, la meilleure note d'abord
    assert ids(requetes.trier_offres(offres, "Plus récentes")) == [2, 4, 3, 1]


def test_candidatures(tmp_path):
    with closing(base(tmp_path / "t.db")) as conn:
        premiere = requetes.creer_candidature(conn, offre_id=1)
        assert requetes.creer_candidature(conn, offre_id=1) == premiere  # pas de doublon
        c = requetes.candidatures(conn)[0]
        assert (c["entreprise"], c["poste"], c["statut"]) == ("Gleamer", "Stage Machine Learning imagerie",
                                                               "à postuler")
        requetes.modifier_candidature(conn, premiere, statut="postulé", date_candidature=date(2026, 10, 28),
                                      notes=float("nan"))                         # case vide : pas de note
        c = requetes.candidature(conn, premiere)
        assert (c["statut"], c["date_candidature"], c["notes"]) == ("postulé", "2026-10-28", None)


# --------------------------------------------------------------------------- export

def test_export_excel(tmp_path):
    with closing(base(tmp_path / "t.db")) as conn:
        requetes.creer_candidature(conn, offre_id=1)
        classeur = openpyxl.load_workbook(io.BytesIO(export.classeur_excel(conn)))
        assert classeur.sheetnames == ["Offres", "Candidatures"]
        offres = list(classeur["Offres"].values)
        assert offres[0][:4] == ("Note", "Catégorie", "Section", "Titre") and len(offres) == 3
        assert list(classeur["Candidatures"].values)[1][0] == "Gleamer"


# --------------------------------------------------------------------------- réglages

def test_reglages_aller_retour_sans_rien_perdre(tmp_path):
    copie = tmp_path / "config.yaml"
    copie.write_text(CHEMIN_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    donnees = reglages.lire(copie)
    nb_commentaires = copie.read_text(encoding="utf-8").count("#")
    assert reglages.appliquer(donnees, {
        "entreprises_suivies": reglages.entreprises_en_lignes(donnees),
        "niveaux": list(donnees["exclusions"]["niveaux"]), "anciennete_max_jours": 90,
    }) == []  # rien de changé : rien à écrire

    lignes = reglages.entreprises_en_lignes(donnees)
    lignes.append({"nom": "Sanofi", "groupe": "grand_groupe", "alias": "Sanofi Aventis, ", "outil": "", "adresse_ou_id": ""})
    changements = reglages.appliquer(donnees, {
        "entreprises_suivies": lignes, "anciennete_max_jours": 60,
        "postes": reglages.texte_en_liste("marketing\n\nsales\nMarketing"),
    })
    assert set(changements) == {"anciennete_max_jours", "entreprises suivies", "exclusions postes"}
    reglages.ecrire(donnees, copie)

    assert (tmp_path / "config.yaml.bak").exists()
    assert copie.read_text(encoding="utf-8").count("#") == nb_commentaires  # commentaires gardés
    relu = charger_config(copie)
    assert relu["general"]["anciennete_max_jours"] == 60
    assert relu["exclusions"]["postes"] == ["marketing", "sales"]
    assert relu["entreprises_suivies"][-1] == {"nom": "Sanofi", "groupe": "grand_groupe", "alias": ["Sanofi Aventis"]}
    doctolib = relu["entreprises_suivies"][0]
    assert doctolib["carrieres"] == {"outil": "ashby", "id": "doctolib"}
    # le reste du fichier est inchangé
    attendu = copy.deepcopy(CONFIG)
    for cle in ("general", "exclusions", "entreprises_suivies"):
        attendu.pop(cle), relu.pop(cle)
    assert relu == attendu


# --------------------------------------------------------------------------- pages (sans navigateur)

@pytest.fixture
def appli(tmp_path, monkeypatch):
    base(tmp_path / "appli.db").close()
    config_test = copy.deepcopy(CONFIG)
    config_test["general"]["base_de_donnees"] = str(tmp_path / "appli.db")
    monkeypatch.setattr(module_config, "charger_config", lambda chemin=None: copy.deepcopy(config_test))
    return tmp_path / "appli.db"


def une_page(page):
    from stage_scraper.appli import main
    main(page)


@pytest.mark.parametrize("page", ["a_trier", "selection", "fiche", "chat", "reglages", "journal", "corbeille"])
def test_chaque_page_s_affiche(appli, page):
    at = AppTest.from_function(une_page, args=(page,), default_timeout=30).run()
    assert not at.exception, at.exception


def test_appli_complete_avec_menu(appli):
    at = AppTest.from_file(str(RACINE / "app.py"), default_timeout=30).run()
    assert not at.exception, at.exception
    assert at.title[0].value == "📥 À trier"
    assert at.segmented_control(key="filtre_a_trier").options[:2] == ["Toutes  2", "Santé  1"]


def vignettes_affichees(at):
    return [m.value for m in at.markdown if 'class="vignette"' in m.value]


def test_a_trier_en_vignettes(appli):
    at = AppTest.from_function(une_page, args=("a_trier",), default_timeout=30).run()
    assert not at.exception, at.exception
    vues = vignettes_affichees(at)
    assert len(vues) == 2 and any("Gleamer" in v and "<b>9</b>" in v for v in vues)
    assert not any("Extrait de l’annonce" in v for v in vues)                     # vignettes courtes
    assert {"✅ Je candidate", "👎 Pas pour moi", "⏳ Plus tard", "🔍 Détails"} <= {b.label for b in at.button}
    assert any("Aucun scrap" in c.value for c in at.caption)
    assert at.session_state["tri_a_trier"] == "Plus récentes"                     # les plus récentes d'abord
    assert "Withings" in vues[0]                                                  # publiée le 21/10, après Gleamer


def test_je_candidate_puis_annuler(appli):
    at = AppTest.from_function(une_page, args=("a_trier",), default_timeout=30).run()
    at.button(key="candidate_toutes_1").click().run()
    assert not at.exception, at.exception
    assert not any("Gleamer" in v for v in vignettes_affichees(at))               # l'offre quitte la liste
    assert any("ajoutée à Ma sélection" in m.value for m in at.markdown)
    with closing(db.connecter(appli)) as conn:
        assert requetes.candidature_de(conn, 1)["statut"] == "à postuler"
    at.button(key="annuler_decision").click().run()
    assert any("Gleamer" in v for v in vignettes_affichees(at))
    with closing(db.connecter(appli)) as conn:
        assert requetes.candidature_de(conn, 1) is None


def test_pas_pour_moi_avec_raison(appli):
    at = AppTest.from_function(une_page, args=("a_trier",), default_timeout=30).run()
    at.button(key="ecarte_toutes_1").click().run()
    assert not at.exception, at.exception
    assert len(vignettes_affichees(at)) == 1
    at.pills(key="raison_1").set_value("Pas mon domaine").run()
    assert not at.exception, at.exception
    with closing(db.connecter(appli)) as conn:
        assert requetes.offre(conn, 1)["pas_interesse"] == 1
        assert requetes.offres_pas_interesse(conn)[0]["raison"] == "Pas mon domaine"


def test_plus_tard_puis_remettre(appli):
    at = AppTest.from_function(une_page, args=("a_trier",), default_timeout=30).run()
    at.button(key="plus_tard_toutes_1").click().run()
    assert not at.exception, at.exception
    assert len(vignettes_affichees(at)) == 1
    at.segmented_control(key="filtre_a_trier").set_value("⏳ Plus tard").run()
    vues = vignettes_affichees(at)
    assert len(vues) == 1 and "Gleamer" in vues[0]
    at.button(key="remettre_plus_tard_1").click().run()
    assert not at.exception, at.exception
    with closing(db.connecter(appli)) as conn:
        assert requetes.offre(conn, 1)["favori"] == 0


def test_offres_bof_masquees_et_recherche(appli):
    with closing(db.connecter(appli)) as conn:
        conn.execute("UPDATE offres SET score = 3 WHERE source_id = '2'")
        conn.commit()
    at = AppTest.from_function(une_page, args=("a_trier",), default_timeout=30).run()
    assert len(vignettes_affichees(at)) == 1
    at.toggle(key="voir_bof").set_value(True).run()
    assert len(vignettes_affichees(at)) == 2
    at.text_input(key="recherche_a_trier").set_value("gleamer paris").run()
    vues = vignettes_affichees(at)
    assert len(vues) == 1 and "Gleamer" in vues[0]
    at.text_input(key="recherche_a_trier").set_value("introuvable").run()
    assert any("Aucune offre ne correspond" in m.value for m in at.markdown)


def test_tout_est_trie(appli):
    with closing(db.connecter(appli)) as conn:
        conn.execute("UPDATE offres SET pas_interesse = 1")
        conn.commit()
    at = AppTest.from_function(une_page, args=("a_trier",), default_timeout=30).run()
    assert any("Tout est trié" in m.value for m in at.markdown)


def test_phrase_du_dernier_scrap(tmp_path):
    from datetime import datetime
    from stage_scraper import page_a_trier
    with closing(base(tmp_path / "t.db")) as conn:
        assert requetes.dernier_scrap(conn) is None
        db.journaliser_run(conn, passage_id=1, date_debut="2026-11-19 08:02:00", declenchement="auto",
                           source="careerjet", nb_offres=3, erreurs=None)
        db.journaliser_run(conn, passage_id=1, date_debut="2026-11-19 08:03:00", declenchement="auto",
                           source="gmail", erreurs="IMAP refusé")
        db.journaliser_run(conn, passage_id=2, date_debut="2026-11-19 09:00:00", declenchement="manuel",
                           source="dossier")                                       # pas un scrap
        s = requetes.dernier_scrap(conn)
    assert (s["passage_id"], s["nouvelles"], s["top"], s["en_erreur"]) == (1, 2, 1, ["gmail"])
    phrase = page_a_trier.phrase_scrap(s, datetime(2026, 11, 19, 12, 0))
    assert phrase == ("Dernier scrap aujourd'hui à 08h02 (automatique) : 2 nouvelles offres, dont 1 notée 8 ou plus"
                      " · ⚠️ en erreur : gmail (détail dans Journal).")


def contenu_fiche(offre_id):
    """Contenu de la fenêtre « Détails », avec sa propre connexion comme dans l'appli."""
    from contextlib import closing
    from stage_scraper import db, vignettes
    from stage_scraper.config import charger_config, chemin_projet
    with closing(db.connecter(chemin_projet(charger_config()["general"]["base_de_donnees"]))) as conn:
        vignettes.fiche(conn, offre_id, "test")


def test_je_candidate_depuis_la_fiche(appli):
    # AppTest ne sait pas relancer une fenêtre seule : on affiche directement son contenu.
    at = AppTest.from_function(contenu_fiche, args=(1,), default_timeout=30).run()
    assert not at.exception, at.exception
    assert any(b.label == "Voir l'annonce ↗" for b in at.get("link_button"))
    next(b for b in at.button if b.label == "✅ Je candidate").click().run()
    assert not at.exception, at.exception
    with closing(db.connecter(appli)) as conn:
        assert [c["entreprise"] for c in requetes.candidatures(conn)] == ["Gleamer"]
        assert conn.execute("SELECT vue FROM offres WHERE source_id = '1'").fetchone()[0] == 1
    assert any(b.label == "📝 Ouvrir la fiche" for b in at.button)               # déjà dans Ma sélection


def test_contenu_d_une_vignette():
    from stage_scraper import vignettes
    o = {"score": 8, "categorie": "À postuler vite", "vue": 0, "poste_ia_data": 1, "type_contrat": "cdd",
         "entreprise": "Doctolib", "titre": "Stage <IA> & data", "lieu": "Levallois-Perret, Ile-de-France, France",
         "duree": None, "duree_ia": "4 mois", "date_debut": "2027-04-01", "date_debut_ia": None,
         "teletravail": "hybride", "gratification": None, "resume": "Modèles de langage.",
         "date_publication": "2026-10-25", "site_origine": "Ashby", "source": "carrieres",
         "section": "Hors santé mais intéressant", "description": "Tu rejoins   l'équipe IA.\n" + "mot " * 200}
    contenu = vignettes.html_vignette(o, suivie=True, aujourd_hui=date(2026, 10, 28), avec_section=True)
    assert "Extrait de l’annonce" in contenu and "Tu rejoins l&#x27;équipe IA. mot" in contenu
    assert ">Hors santé<" in contenu  # étiquette de section (onglet « Toutes sections »)
    assert vignettes.extrait("mot " * 200).endswith("mot…") and len(vignettes.extrait("mot " * 200)) <= 481
    assert "Stage &lt;IA&gt; &amp; data" in contenu  # texte des sites échappé
    for attendu in ("v-note-haute", "Nouvelle", "IA / data", "CDD", "Dans mes candidatures", "Levallois-Perret<",
                    "4 mois", "avril 2027", "Hybride", "il y a 3 j", "Ashby"):
        assert attendu in contenu, attendu
    assert "Gratification" not in contenu and "💶" not in contenu  # inconnue : pas affichée
    o.update(score=None, duree_ia=None, date_debut=None, vue=1, description=None)
    contenu = vignettes.html_vignette(o)
    assert "Extrait" not in contenu and ">Hors santé<" not in contenu
    assert "v-note-attente" in contenu and "Durée ?" in contenu and "Début ?" in contenu


# --------------------------------------------------------------------------- suivi des candidatures

def test_changer_statut_remplit_les_dates(tmp_path):
    with closing(base(tmp_path / "t.db")) as conn:
        identifiant = requetes.creer_candidature(conn, offre_id=1)
        avant = requetes.changer_statut(conn, identifiant, "postulé", relance_jours=7, aujourd_hui=date(2026, 10, 28))
        c = requetes.candidature(conn, identifiant)
        assert (c["statut"], c["date_candidature"], c["date_relance"]) == ("postulé", "2026-10-28", "2026-11-04")
        requetes.changer_statut(conn, identifiant, "relancé", relance_jours=7, aujourd_hui=date(2026, 11, 5))
        c = requetes.candidature(conn, identifiant)
        assert (c["date_candidature"], c["date_relance"]) == ("2026-10-28", "2026-11-12")  # date d'envoi gardée
        requetes.changer_statut(conn, identifiant, "entretien")
        assert requetes.candidature(conn, identifiant)["date_relance"] is None
        # annuler = revenir à l'état d'avant le premier changement
        requetes.restaurer_candidature(conn, avant)
        c = requetes.candidature(conn, identifiant)
        assert (c["statut"], c["date_candidature"]) == ("à postuler", None)


def test_supprimer_puis_annuler(tmp_path):
    with closing(base(tmp_path / "t.db")) as conn:
        identifiant = requetes.creer_candidature(conn, offre_id=1, notes="appel prévu")
        avant = requetes.supprimer_candidature(conn, identifiant)
        assert requetes.candidatures(conn) == []
        requetes.restaurer_candidature(conn, avant)
        assert requetes.candidature(conn, identifiant)["notes"] == "appel prévu"
        with pytest.raises(ValueError):
            requetes.modifier_candidature(conn, identifiant, statut="n'importe quoi")


def une_fiche(offre_id):
    """La fiche d'une offre, comme si on l'avait ouverte depuis Ma sélection."""
    import streamlit as st
    from stage_scraper.appli import main
    st.session_state.setdefault("fiche_offre_id", offre_id)
    main("fiche")


def test_ma_selection_par_etape(appli):
    with closing(db.connecter(appli)) as conn:
        requetes.creer_candidature(conn, offre_id=1)
        withings = requetes.creer_candidature(conn, offre_id=2)
        requetes.modifier_candidature(conn, withings, statut="postulé", date_candidature="2026-11-01",
                                      date_relance="2026-11-08")                # relance en retard
    at = AppTest.from_function(une_page, args=("selection",), default_timeout=30).run()
    assert not at.exception, at.exception
    etapes = at.segmented_control(key="etape_selection_bouton")
    assert etapes.value == "preparation"
    assert any("Gleamer" in m.value for m in at.markdown) and not any("Withings" in m.value for m in at.markdown)
    assert any(b.label == "✨ Préparer" for b in at.button)                       # prochaine action
    etapes.set_value("envoyee").run()
    assert any("Withings" in m.value for m in at.markdown)
    at.button(key=f"agir_{withings}").click().run()                              # « J'ai relancé »
    assert not at.exception, at.exception
    with closing(db.connecter(appli)) as conn:
        c = requetes.candidature(conn, withings)
        assert c["statut"] == "relancé" and c["date_relance"] > date.today().isoformat()
    at.button(key="annuler_selection").click().run()
    with closing(db.connecter(appli)) as conn:
        assert requetes.candidature(conn, withings)["statut"] == "postulé"
    assert at.session_state["etape_selection"] == "envoyee"                        # étape gardée


def test_ma_selection_vide(appli):
    at = AppTest.from_function(une_page, args=("selection",), default_timeout=30).run()
    assert not at.exception, at.exception
    assert any("Rien dans ta sélection" in i.value for i in at.info)


def test_fiche_changer_d_etape_entretien_et_retirer(appli):
    with closing(db.connecter(appli)) as conn:
        identifiant = requetes.creer_candidature(conn, offre_id=1)
    at = AppTest.from_function(une_fiche, args=(1,), default_timeout=30).run()
    assert not at.exception, at.exception
    assert at.title[0].value == "Stage Machine Learning imagerie"
    assert any("Segmentation" in m.value for m in at.markdown)                   # onglet L'offre
    at.segmented_control(key=f"etape_fiche_{identifiant}_à postuler").set_value("entretien").run()
    assert not at.exception, at.exception
    at.date_input[0].set_value(date(2026, 11, 26)).run()                          # date de l'entretien
    with closing(db.connecter(appli)) as conn:
        c = requetes.candidature(conn, identifiant)
        assert (c["statut"], c["date_entretien"]) == ("entretien", "2026-11-26")
    assert any("Entretien le 26/11" in x.value for x in at.caption)

    next(b for b in at.button if b.label == "🗑️ Retirer de ma sélection").click().run()
    assert not at.exception, at.exception
    with closing(db.connecter(appli)) as conn:
        assert requetes.candidature_de(conn, 1) is None
        assert 1 in {o["id"] for o in requetes.offres_a_trier(conn)}             # revenue dans À trier
    at.button(key="annuler_selection").click().run()
    with closing(db.connecter(appli)) as conn:
        assert requetes.candidature_de(conn, 1)["statut"] == "entretien"


def test_fiche_notes_gardees_toutes_seules(appli):
    with closing(db.connecter(appli)) as conn:
        identifiant = requetes.creer_candidature(conn, offre_id=1)
    at = AppTest.from_function(une_fiche, args=(1,), default_timeout=30).run()
    zone = next(t for t in at.text_area if t.label == "Notes")
    zone.set_value("Contact : Marie, responsable data").run()
    assert not at.exception, at.exception
    with closing(db.connecter(appli)) as conn:
        assert requetes.candidature(conn, identifiant)["notes"] == "Contact : Marie, responsable data"


def contenu_fenetre_nouvelle():
    from stage_scraper import page_selection
    from stage_scraper.config import charger_config
    config = charger_config()
    with page_selection._connexion(config) as conn:
        page_selection._nouvelle(conn, config)


def test_offre_trouvee_ailleurs_avec_sa_fiche(appli):
    # AppTest ne sait pas relancer une fenêtre seule : on affiche directement son contenu.
    at = AppTest.from_function(contenu_fenetre_nouvelle, default_timeout=30).run()
    at.text_input[0].set_value("Sanofi").run()
    at.text_input[1].set_value("Stage data clinique").run()
    at.text_area[0].set_value("Analyse de données cliniques en Python.").run()
    next(b for b in at.button if b.label == "Ajouter à Ma sélection").click().run()
    assert not at.exception, at.exception
    with closing(db.connecter(appli)) as conn:
        c = requetes.candidatures(conn)[0]
        o = requetes.offre(conn, c["offre_id"])
        assert (c["entreprise"], c["statut"], o["source"]) == ("Sanofi", "à postuler", "manuel")
        assert o["description"] == "Analyse de données cliniques en Python."
    at = AppTest.from_function(une_fiche, args=(c["offre_id"],), default_timeout=30).run()
    assert not at.exception, at.exception
    zone = next(t for t in at.text_area if t.label == "Texte de l'annonce")         # modifiable
    zone.set_value("Analyse de données cliniques en Python et SQL.").run()
    with closing(db.connecter(appli)) as conn:
        assert requetes.offre(conn, c["offre_id"])["description"].endswith("et SQL.")


def test_corbeille_remettre_a_trier(appli):
    with closing(db.connecter(appli)) as conn:
        requetes.marquer_pas_interesse(conn, 1, "Pas mon domaine")
    at = AppTest.from_function(une_page, args=("corbeille",), default_timeout=30).run()
    assert not at.exception, at.exception
    assert any("Pas mon domaine" in m.value for m in at.markdown)
    at.button(key="retablir_1").click().run()
    with closing(db.connecter(appli)) as conn:
        assert requetes.offre(conn, 1)["pas_interesse"] == 0
    at.segmented_control(key="choix_corbeille").set_value("tri").run()            # l'alternance exclue
    assert not at.exception, at.exception
    assert "Owkin" in at.dataframe[0].value["Entreprise"].tolist()


def test_journal_une_ligne_par_passage(tmp_path):
    with closing(base(tmp_path / "t.db")) as conn:
        for source, nb, erreur in (("careerjet", 5, "403 : IP non autorisée"), ("google_jobs", 3, None),
                                   ("scoring", 2, None)):
            db.journaliser_run(conn, passage_id=1, date_debut="2026-11-19 08:00:00", declenchement="auto",
                               source=source, nb_offres=nb, nb_nouvelles=nb if source != "scoring" else 0,
                               erreurs=erreur, cout_usd=0.001 if source == "scoring" else 0)
        db.journaliser_run(conn, passage_id=2, date_debut="2026-11-19 09:00:00", declenchement="manuel",
                           source="dossier", modele="claude-sonnet-5-5", cout_usd=0.04)
        (p,) = requetes.passages(conn)                                              # l'appel d'IA n'est pas un passage
        assert (p["auto"], p["sources"], p["trouvees"], p["nouvelles"], p["notees"]) == (True, 2, 8, 8, 2)
        assert p["gardees"] == 2 and p["top"] == 1 and p["en_erreur"] == ["careerjet"]
        assert [a["modele"] for a in requetes.appels_ia(conn)] == ["claude-sonnet-5-5"]


def test_chat_affiche_les_offres_proposees(appli, monkeypatch):
    from stage_scraper import chat_offres

    def faux_demander(conn, config, question, historique, client=None):
        o = requetes.offres_visibles(conn)[0]
        return {"reponse": "Une offre correspond.", "offres": [{**o, "raison": "Imagerie et deep learning."}],
                "ignores": 0, "lues": ["Stage ML — Gleamer"]}
    monkeypatch.setattr(chat_offres, "demander", faux_demander)
    at = AppTest.from_function(une_page, args=("chat",), default_timeout=30).run()
    at.chat_input[0].set_value("un stage en imagerie").run()
    assert not at.exception, at.exception
    assert any("Une offre correspond." in m.value for m in at.markdown)
    assert any("Imagerie et deep learning." in m.value for m in at.markdown)
    assert at.expander[0].label == "📋 1 offre proposée"
    assert any("Lu : Stage ML — Gleamer" in c.value for c in at.caption)
    assert any(b.label == "🔍 Détails" for b in at.button)
    assert not any('class="vignette"' in m.value for m in at.markdown)   # plus de grandes vignettes
    # la conversation est gardée en base : elle est encore là à la réouverture de l'appli
    at = AppTest.from_function(une_page, args=("chat",), default_timeout=30).run()
    assert any("Une offre correspond." in m.value for m in at.markdown)
    next(b for b in at.button if b.label == "🧹 Nouvelle conversation").click().run()
    assert not any("Une offre correspond." in m.value for m in at.markdown)


# --------------------------------------------------------------------------- dossier dans la fiche

DIAG_TEST = {"adequation": "partielle", "synthese": "Python oui, imagerie non.", "pour": ["Python"],
             "contre": ["Pas d'imagerie"], "alertes": [{"alerte": "Durée non précisée", "question_recruteur": "Combien ?"}],
             "exigences": [{"exigence": "Python", "obligatoire": True, "preuve_cv": "Python (pandas)",
                            "couverture": "couverte", "action": "-", "citation_verifiee": True}],
             "conseils_cv": [{"section": "Projets", "action": "reformuler", "avant": "ancienne ligne",
                              "apres": "nouvelle ligne", "sources": [], "justification": "plus clair",
                              "mots_cles": ["imagerie"], "a_verifier": True}],
             "a_apprendre": ["PyTorch"], "conseils_ecartes": 0}


@pytest.fixture
def candidater(appli, monkeypatch):
    """Faux CV et fausse IA : la page ne fait aucun appel réel."""
    from stage_scraper import cv, dossier
    appels = []
    monkeypatch.setattr(cv, "texte_cv", lambda config: "[Prénom Nom]\nPython (pandas)")
    monkeypatch.setattr(cv, "modele_lettre", lambda config: None)
    monkeypatch.setattr(cv, "nom_reel", lambda config: "Alex Martin")

    def faux_diagnostiquer(conn, config, d, client=None):
        appels.append("diagnostic")
        conn.execute("UPDATE dossiers SET diagnostic = ?, empreinte_cv = ?, modele_diagnostic = 'faux', "
                     "date_diagnostic = '2026-11-19 10:00:00' WHERE id = ?",
                     (__import__("json").dumps(DIAG_TEST), cv.empreinte(cv.texte_cv(config)), d["id"]))
        conn.commit()

    def faux_discuter(conn, config, d, demande, client=None):
        appels.append(demande)
        dossier.ajouter_message(conn, dossier.conversation_de(d), "user", demande)
        texte = f"Objet : Stage\n\nMadame, Monsieur,\n\nVersion pour « {demande} ».\n\n[Prénom Nom]"
        numero = dossier.ajouter_version(conn, d, texte, demande, "faux", ["Phrase inventée."])
        dossier.ajouter_message(conn, dossier.conversation_de(d), "assistant", "C'est fait.", {"version": numero})
        return {"reponse": "C'est fait.", "numero": numero, "alertes": []}

    monkeypatch.setattr(dossier, "diagnostiquer", faux_diagnostiquer)
    monkeypatch.setattr(dossier, "discuter", faux_discuter)
    with closing(db.connecter(appli)) as conn:
        offre_id = conn.execute("SELECT id FROM offres WHERE source_id = '1'").fetchone()[0]
        dossier.ouvrir(conn, offre_id)
    return appels, offre_id


def _preparer(at):
    next(b for b in at.button if b.label.startswith("✨ Préparer avec l'IA")).click().run()
    return at


def test_candidater_ia_seulement_sur_bouton(appli, candidater):
    appels, offre_id = candidater
    at = AppTest.from_function(une_fiche, args=(offre_id,), default_timeout=30).run()
    assert not at.exception, at.exception
    assert appels == []                                                          # rien ne part tout seul
    bouton = next(b for b in at.button if b.label.startswith("✨ Préparer avec l'IA"))
    assert "c)" in bouton.label or "gratuit" in bouton.label                     # le prix est affiché
    _preparer(at)
    assert not at.exception, at.exception
    assert appels == ["diagnostic", "Rédige une première version de la lettre."]
    assert "Version pour" in at.text_area[0].value
    assert any("Phrase inventée." in w.value for w in at.warning)                # affirmation hors CV signalée
    assert any("nouvelle ligne" in m.value for m in at.markdown)                 # conseils CV
    assert any("Combien ?" in w.value for w in at.warning)                       # question au recruteur
    with closing(db.connecter(appli)) as conn:
        assert requetes.candidature_de(conn, offre_id)["statut"] == "à postuler"

    at.run()                                                                     # pas de relance automatique
    assert len(appels) == 2
    assert not any(b.label.startswith("✨ Préparer") for b in at.button)          # dossier complet : bouton parti


def test_candidater_retouche_garde_les_modifs_et_annule(appli, candidater):
    appels, offre_id = candidater
    at = _preparer(AppTest.from_function(une_fiche, args=(offre_id,), default_timeout=30).run())
    at.text_area[0].set_value("Ma version").run()                               # gardée sans bouton…
    at.text_area[0].set_value("Ma version écrite à la main.").run()             # …et dans la même version
    at.chat_input[0].set_value("plus court").run()
    assert not at.exception, at.exception
    assert appels[-1] == "plus court"
    from stage_scraper import dossier
    with closing(db.connecter(appli)) as conn:
        d = dossier.obtenir(conn, offre_id)
        textes = [v["texte"] for v in dossier.versions(conn, d["id"])]
        assert textes[1] == "Ma version écrite à la main."                      # gardée avant la retouche
        assert len(textes) == 3 and d["version_courante"] == 3
    assert any("C'est fait." in m.value for m in at.markdown)
    next(b for b in at.button if b.label == "↩️ Annuler").click().run()
    assert at.text_area[0].value == "Ma version écrite à la main."
    with closing(db.connecter(appli)) as conn:
        assert requetes.candidature_de(conn, offre_id)["lettre"] == "Ma version écrite à la main."


def test_candidater_lettre_figee_apres_envoi(appli, candidater):
    appels, offre_id = candidater
    at = _preparer(AppTest.from_function(une_fiche, args=(offre_id,), default_timeout=30).run())
    next(b for b in at.button if b.label == "📨 C'est envoyé").click().run()
    with closing(db.connecter(appli)) as conn:
        envoyee = requetes.candidature_de(conn, offre_id)["lettre"]
    at.chat_input[0].set_value("plus court").run()
    assert not at.exception, at.exception
    assert any("ne change plus" in c.value for c in at.caption)
    with closing(db.connecter(appli)) as conn:
        assert requetes.candidature_de(conn, offre_id)["lettre"] == envoyee      # celle que le recruteur a lue
