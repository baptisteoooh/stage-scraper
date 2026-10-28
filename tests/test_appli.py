"""Tests de l'appli : requêtes, export Excel, réglages, et affichage de chaque page (sans navigateur)."""
import copy
import io
from contextlib import closing
from datetime import date

import openpyxl
import pytest
from streamlit.testing.v1 import AppTest

from stage_scraper import config as module_config
from stage_scraper import db, export, reglages, requetes, traitement
from stage_scraper.config import CHEMIN_CONFIG, charger_config
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


def test_candidatures(tmp_path):
    with closing(base(tmp_path / "t.db")) as conn:
        premiere = requetes.creer_candidature(conn, offre_id=1)
        assert requetes.creer_candidature(conn, offre_id=1) == premiere  # pas de doublon
        c = requetes.candidatures(conn)[0]
        assert (c["entreprise"], c["poste"], c["statut"]) == ("Gleamer", "Stage Machine Learning imagerie",
                                                               "à postuler")

        lignes = [dict(c, statut="postulé", date_candidature=date(2026, 10, 28), notes=float("nan")),
                  {"id": float("nan"), "entreprise": "Sanofi", "poste": "Stage data", "statut": None},
                  {"id": None, "entreprise": None, "poste": None}]  # ligne vide ignorée
        bilan = requetes.enregistrer_candidatures(conn, lignes)
        assert bilan == {"ajoutees": 1, "modifiees": 1, "supprimees": 0}
        toutes = {c["entreprise"]: c for c in requetes.candidatures(conn)}
        assert toutes["Gleamer"]["statut"] == "postulé" and toutes["Gleamer"]["date_candidature"] == "2026-10-28"
        assert toutes["Sanofi"]["statut"] == "à postuler"

        bilan = requetes.enregistrer_candidatures(conn, [toutes["Sanofi"]])
        assert bilan == {"ajoutees": 0, "modifiees": 0, "supprimees": 1}


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


@pytest.mark.parametrize("page", ["tableau_de_bord", "candidatures", "lettre", "reglages", "journal"])
def test_chaque_page_s_affiche(appli, page):
    at = AppTest.from_function(une_page, args=(page,), default_timeout=30).run()
    assert not at.exception, at.exception


def test_appli_complete_avec_menu(appli):
    at = AppTest.from_file(str(CHEMIN_CONFIG.parent / "app.py"), default_timeout=30).run()
    assert not at.exception, at.exception
    assert at.title[0].value.endswith("Offres de stage")
    onglets = [t.label for t in at.tabs]
    assert onglets[:2] == ["Toutes sections (1)", "Santé (1)"] and onglets[-1] == "En attente de note IA (1)"


def test_page_offres_en_vignettes(appli):
    at = AppTest.from_function(une_page, args=("tableau_de_bord",), default_timeout=30).run()
    assert not at.exception, at.exception
    vignettes = [m.value for m in at.markdown if 'class="vignette"' in m.value]
    assert any("Gleamer" in v and "<b>9</b>" in v for v in vignettes)
    assert any(b.label == "Voir la fiche" for b in at.button)
    assert not at.dataframe or len(at.dataframe) == 1  # seul reste le tableau des offres écartées


def contenu_fiche(offre_id):
    """Contenu de la fenêtre « Voir la fiche », avec sa propre connexion comme dans l'appli."""
    from contextlib import closing
    from stage_scraper import db, vignettes
    from stage_scraper.config import charger_config, chemin_projet
    with closing(db.connecter(chemin_projet(charger_config()["general"]["base_de_donnees"]))) as conn:
        vignettes.fiche(conn, offre_id, "test")


def test_postuler_depuis_la_fiche(appli):
    # AppTest ne sait pas relancer une fenêtre seule : on affiche directement son contenu.
    at = AppTest.from_function(contenu_fiche, args=(1,), default_timeout=30).run()
    assert not at.exception, at.exception
    next(b for b in at.button if "Postuler" in b.label).click().run()
    assert not at.exception, at.exception
    with closing(db.connecter(appli)) as conn:
        assert [c["entreprise"] for c in requetes.candidatures(conn)] == ["Gleamer"]
        assert conn.execute("SELECT vue FROM offres WHERE source_id = '1'").fetchone()[0] == 1


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


def test_relance_due_et_recherche():
    from stage_scraper import suivi
    c = {"statut": "postulé", "date_relance": "2026-11-04", "entreprise": "Doctolib", "poste": "ML", "notes": None}
    assert not suivi.relance_due(c, date(2026, 11, 3)) and suivi.relance_due(c, date(2026, 11, 4))
    assert not suivi.relance_due(dict(c, statut="entretien"), date(2026, 12, 1))
    assert suivi.correspond(c, "docto") and not suivi.correspond(c, "withings")
    assert suivi.etape(dict(c, statut="refus")) == "terminé"


def test_page_candidatures_en_cartes(appli):
    with closing(db.connecter(appli)) as conn:
        identifiant = requetes.creer_candidature(conn, offre_id=1)
    at = AppTest.from_function(une_page, args=("candidatures",), default_timeout=30).run()
    assert not at.exception, at.exception
    assert any("Gleamer" in m.value for m in at.markdown)
    at.button(key=f"avancer_{identifiant}").click().run()  # « J'ai postulé »
    assert not at.exception, at.exception
    with closing(db.connecter(appli)) as conn:
        c = requetes.candidature(conn, identifiant)
        assert c["statut"] == "postulé" and c["date_candidature"] == date.today().isoformat()
    bouton_annuler = next(b for b in at.button if "Annuler" in b.label)
    bouton_annuler.click().run()
    with closing(db.connecter(appli)) as conn:
        assert requetes.candidature(conn, identifiant)["statut"] == "à postuler"


def contenu_fenetre_details(candidature_id):
    """Contenu de la fenêtre « Détails », avec sa propre connexion comme dans l'appli."""
    from stage_scraper import suivi
    from stage_scraper.config import charger_config
    with suivi._connexion(charger_config()) as conn:
        suivi._bandeau_annulation(conn)
        suivi._details(conn, candidature_id, 7)


def test_supprimer_depuis_la_fenetre_details(appli):
    # AppTest ne sait pas relancer une fenêtre seule : on affiche directement son contenu.
    with closing(db.connecter(appli)) as conn:
        identifiant = requetes.creer_candidature(conn, offre_id=1)
    at = AppTest.from_function(contenu_fenetre_details, args=(identifiant,), default_timeout=30).run()
    assert not at.exception, at.exception
    next(b for b in at.button if b.label == "Supprimer").click().run()
    assert not at.exception, at.exception
    with closing(db.connecter(appli)) as conn:
        assert requetes.candidatures(conn) == []
    next(b for b in at.button if "Annuler" in b.label).click().run()
    with closing(db.connecter(appli)) as conn:
        assert requetes.candidature(conn, identifiant)["entreprise"] == "Gleamer"


def test_page_candidatures_vide(appli):
    at = AppTest.from_function(une_page, args=("candidatures",), default_timeout=30).run()
    assert not at.exception, at.exception
    assert any("Aucune candidature" in m.value for m in at.markdown)
