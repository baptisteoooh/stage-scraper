"""Tests du dossier de candidature (diagnostic, lettre, versions) avec un faux client Gemini et un faux CV."""
import json
from contextlib import closing

import pytest

from stage_scraper import cv, db, dossier, gemini, requetes
from stage_scraper.config import charger_config
from stage_scraper.offre import nouvelle_offre

CONFIG = charger_config()
USAGE = {"promptTokenCount": 5000, "candidatesTokenCount": 800}

FAUX_CV = """[Prénom Nom]
[coordonnées retirées]
École d'ingénieurs Exemple Sept. 2023 - 2028
Diplôme d'ingénieur - Spécialisation Santé
• Matières principales : Machine Learning, Probability Theory & Statistics
Projet de prédiction de la glycémie | Python, scikit-learn Oct. 2026
• Validation croisée groupée par patient pour éviter la fuite de données.
Programmation : C++, SQL, Python (pandas, NumPy, scikit-learn)"""

DESCRIPTION = ("Vous développerez des modèles de segmentation d'images médicales. "
               "Profil : bon niveau en Python, connaissance de PyTorch, stage de 5 mois.")


def reponse(donnees):
    return {"role": "model", "parts": [{"text": json.dumps(donnees, ensure_ascii=False)}]}


class FauxClient:
    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.appels = []

    def appeler(self, modele, systeme, contents, schema=None, reflexion=None, outils=None):
        self.appels.append(dict(modele=modele, reflexion=reflexion, systeme=systeme,
                                contents=json.loads(json.dumps(contents))))
        r = self.reponses.pop(0) if len(self.reponses) > 1 else self.reponses[0]
        if isinstance(r, Exception):
            raise r
        return r, USAGE


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(cv, "texte_cv", lambda config: FAUX_CV)
    monkeypatch.setattr(cv, "modele_lettre", lambda config: None)
    c = db.connecter(tmp_path / "t.db")
    db.initialiser(c)
    db.enregistrer_offres(c, [nouvelle_offre(source="test", source_id="1", titre="Stage segmentation",
                                             entreprise="Imagix", lieu="Paris", date_publication="2026-11-10",
                                             description=DESCRIPTION)], passage_id=1)
    yield c
    c.close()


def offre_id(conn):
    return conn.execute("SELECT id FROM offres").fetchone()[0]


DIAG = {
    "adequation": "partielle", "synthese": "Python oui, imagerie non.",
    "pour": ["Python"], "contre": ["Pas de PyTorch"], "alertes": [],
    "exigences": [
        {"exigence": "bon niveau en Python", "obligatoire": True,
         "preuve_cv": "Python (pandas, NumPy, scikit-learn)", "couverture": "couverte", "action": "-"},
        {"exigence": "connaissance de PyTorch", "obligatoire": True,
         "preuve_cv": "Trois ans de PyTorch en entreprise", "couverture": "couverte", "action": "-"},
        {"exigence": "expert Kubernetes certifié", "obligatoire": False,
         "preuve_cv": None, "couverture": "absente", "action": "-"}],
    "conseils_cv": [
        {"section": "Projets", "action": "reformuler",
         "avant": "Validation croisée groupée par patient pour éviter la fuite de données.",
         "apres": "Validation croisée groupée par patient (données médicales).",
         "sources": ["Validation croisée groupée par patient"], "justification": "-", "mots_cles": ["médicales"]},
        {"section": "Projets", "action": "reformuler", "avant": "Stage de 6 mois chez Google",
         "apres": "x", "sources": [], "justification": "-", "mots_cles": []},
        {"section": "Compétences", "action": "ajouter", "avant": None,
         "apres": "Segmentation d'images (U-Net)", "sources": ["Kaggle grandmaster"],
         "justification": "-", "mots_cles": ["segmentation"]}],
    "a_apprendre": ["PyTorch"],
}


# ---------------------------------------------------------------- citations

def test_est_cite_tolere_accents_ponctuation_et_casse():
    assert dossier.est_cite("validation croisee groupee PAR patient", FAUX_CV)
    assert dossier.est_cite("Machine Learning … Probability Theory", FAUX_CV)
    assert not dossier.est_cite("Deep Learning avancé", FAUX_CV)
    assert not dossier.est_cite("C++", FAUX_CV)          # trop court pour prouver quoi que ce soit
    assert not dossier.est_cite(None, FAUX_CV)


def test_est_cite_longue_citation_legerement_reformulee():
    longue = ("Projet de prédiction de la glycémie | Python, scikit-learn Oct. 2026\n"
              "• Validation croisée groupée par patient pour éviter la fuite de données.\n"
              "Programmation : C++, SQL, Python et R")   # dernière ligne un peu changée
    assert dossier.est_cite(longue, FAUX_CV)
    inventee = "Stage chez Google\n• Kubernetes en production\nProgrammation : C++, SQL"
    assert not dossier.est_cite(inventee, FAUX_CV)


def test_verifier_diagnostic_retire_les_preuves_et_conseils_inventes():
    d = dossier.verifier_diagnostic(DIAG, FAUX_CV, DESCRIPTION)
    python, pytorch, kube = d["exigences"]
    assert python["preuve_cv"] and python["couverture"] == "couverte" and python["citation_verifiee"]
    assert pytorch["preuve_cv"] is None and pytorch["couverture"] == "partielle" and pytorch["preuve_retiree"]
    assert not kube["citation_verifiee"]                       # exigence absente de l'offre
    assert d["conseils_ecartes"] == 1                            # « Stage de 6 mois chez Google » n'est pas dans le CV
    reformuler, ajouter = d["conseils_cv"]
    assert not reformuler["a_verifier"]
    assert ajouter["a_verifier"] and ajouter["sources"] == []    # source « Kaggle » introuvable


# ---------------------------------------------------------------- diagnostic

def test_diagnostic_enregistre_journalise_et_ouvre_la_conversation(conn):
    o = offre_id(conn)
    d = dossier.ouvrir(conn, o)
    assert requetes.candidature_de(conn, o)["statut"] == "à postuler"   # Préparer = candidature créée
    client = FauxClient(reponse(DIAG))
    dossier.diagnostiquer(conn, CONFIG, d, client=client)

    relu = dossier.obtenir(conn, o)
    assert relu["diagnostic"]["conseils_ecartes"] == 1
    assert relu["empreinte_cv"] == cv.empreinte(FAUX_CV) and not dossier.a_refaire(relu, CONFIG)
    systeme = client.appels[0]["systeme"]
    assert "<cv>" in systeme and "Validation croisée" in systeme and "segmentation" in systeme
    assert client.appels[0]["reflexion"] == "high"             # « gemini-3.5-flash-lite:high » par défaut
    run = conn.execute("SELECT source, tokens_entree, erreurs FROM runs").fetchone()
    assert tuple(run) == ("dossier", 5000, None)
    premier = dossier.messages(conn, dossier.conversation_de(d))
    assert len(premier) == 1 and "partielle" in premier[0]["texte"]


def test_diagnostic_a_refaire_quand_le_cv_change(conn, monkeypatch):
    d = dossier.ouvrir(conn, offre_id(conn))
    dossier.diagnostiquer(conn, CONFIG, d, client=FauxClient(reponse(DIAG)))
    monkeypatch.setattr(cv, "texte_cv", lambda config: FAUX_CV + "\nNouveau projet")
    assert dossier.a_refaire(dossier.obtenir(conn, offre_id(conn)), CONFIG)


def test_modele_suivant_si_le_premier_est_surcharge(conn):
    d = dossier.ouvrir(conn, offre_id(conn))
    client = FauxClient(gemini.ErreurGemini("Gemini surchargé (503)"), reponse(DIAG))
    dossier.diagnostiquer(conn, CONFIG, d, client=client)
    assert [a["reflexion"] for a in client.appels] == ["high", None]


def test_erreur_partout_message_lisible_et_journal(conn):
    d = dossier.ouvrir(conn, offre_id(conn))
    with pytest.raises(dossier.DossierImpossible, match="réessaie"):
        dossier.diagnostiquer(conn, CONFIG, d, client=FauxClient(gemini.ErreurGemini("503")))
    assert conn.execute("SELECT erreurs FROM runs").fetchone()[0]
    assert dossier.obtenir(conn, offre_id(conn))["diagnostic"] is None


def test_sans_cv_pas_d_appel(conn, monkeypatch):
    monkeypatch.setattr(cv, "texte_cv", lambda config: None)
    d = dossier.ouvrir(conn, offre_id(conn))
    with pytest.raises(dossier.DossierImpossible, match="CV"):
        dossier.diagnostiquer(conn, CONFIG, d, client=FauxClient(reponse(DIAG)))


# ---------------------------------------------------------------- lettre

LETTRE_1 = "Objet : Stage\n\nMadame, Monsieur,\n\nJ'ai validé par patient mes modèles.\n\n[Prénom Nom]"
LETTRE_2 = LETTRE_1.replace("J'ai validé", "J'ai rigoureusement validé") + "\nJ'ai trois ans de PyTorch."


def test_lettre_versions_alertes_et_annulation(conn):
    o = offre_id(conn)
    d = dossier.ouvrir(conn, o)
    client = FauxClient(
        reponse({"reponse": "Voici un premier jet.", "lettre": LETTRE_1, "affirmations": [
            {"phrase": "J'ai validé par patient mes modèles.",
             "citation_cv": "Validation croisée groupée par patient"}]}),
        reponse({"reponse": "C'est fait.", "lettre": LETTRE_2, "affirmations": [
            {"phrase": "J'ai trois ans de PyTorch.", "citation_cv": None}]}),
        reponse({"reponse": "Oui, elle fait 20 mots.", "lettre": None, "affirmations": []}))

    r1 = dossier.discuter(conn, CONFIG, d, "Rédige la lettre.", client=client)
    assert r1["numero"] == 1 and r1["alertes"] == []
    assert requetes.candidature_de(conn, o)["lettre"] == LETTRE_1      # recopiée dans la candidature

    r2 = dossier.discuter(conn, CONFIG, d, "Ajoute PyTorch.", client=client)
    assert r2["numero"] == 2 and r2["alertes"] == ["J'ai trois ans de PyTorch."]
    envoye = client.appels[1]["contents"]
    assert envoye[-1]["role"] == "user" and LETTRE_1 in envoye[-1]["parts"][0]["text"]   # lettre actuelle jointe
    assert [m["role"] for m in envoye[:-1]] == ["user", "model"]                           # historique gardé

    r3 = dossier.discuter(conn, CONFIG, d, "Elle est courte ?", client=client)
    assert r3["numero"] is None and len(dossier.versions(conn, d["id"])) == 2              # simple question

    dossier.choisir_version(conn, d, 1)                                                   # Annuler
    assert dossier.version_courante(conn, d)["texte"] == LETTRE_1
    assert requetes.candidature_de(conn, o)["lettre"] == LETTRE_1
    roles = [m["role"] for m in dossier.messages(conn, dossier.conversation_de(d))]
    assert roles == ["user", "assistant"] * 3


def test_modification_a_la_main_est_une_version(conn):
    d = dossier.ouvrir(conn, offre_id(conn))
    numero = dossier.ajouter_version(conn, d, "Ma lettre écrite à la main.", "modification à la main", None)
    assert numero == 1 and dossier.version_courante(conn, d)["modele"] is None


def test_suppression_de_l_offre_supprime_le_dossier(conn):
    o = offre_id(conn)
    d = dossier.ouvrir(conn, o)
    dossier.ajouter_version(conn, d, "x", None, None)
    conn.execute("DELETE FROM candidatures")
    conn.execute("DELETE FROM offres")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM dossiers").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM lettres_versions").fetchone()[0] == 0


def test_export_docx_et_signature(monkeypatch):
    from docx import Document
    import io
    contenu = dossier.exporter_docx("Objet : Stage\n\nMadame, Monsieur,\n\n[Prénom Nom]")
    paragraphes = [p.text for p in Document(io.BytesIO(contenu)).paragraphs]
    assert paragraphes[0] == "Objet : Stage" and paragraphes[-1] == "[Prénom Nom]"
    monkeypatch.setattr(cv, "nom_reel", lambda config: "Alex Martin")
    assert cv.signer("Bien à vous,\n[Prénom Nom]", CONFIG).endswith("Alex Martin")
