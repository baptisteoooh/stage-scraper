"""Tests de l'anonymisation du CV, sur un faux CV (aucune donnée réelle)."""
from stage_scraper import cv

FAUX_CV = """Jeanne Exemple
Recherche de stage en data science
+33 6 12 34 56 78 | jeanne.exemple@ecole.fr | linkedin.com/in/jeanne-exemple | Ville-Test, France
Formation
´Ecole d’ing´enieurs (ENSX) Sept. 2023 - 2028
Exp´eriences
• Projet en Python ; contact : 01 23 45 67 89 ou https://github.com/jexemple
Langues
Fran¸cais : Langue maternelle ; Diplˆome ; Mati`ere"""


def test_reparer_accents():
    assert cv.reparer_accents("sup´erieure `a l’´etranger, Fran¸cais, Diplˆome, ´Ecole") == \
        "supérieure à l’étranger, Français, Diplôme, École"


def test_anonymiser_retire_coordonnees_et_nom():
    texte = cv.reparer_accents(FAUX_CV)
    nom = cv.nom_du_cv(texte)
    assert nom == "Jeanne Exemple"
    propre = cv.anonymiser(texte, nom)
    for interdit in ("Jeanne", "Exemple", "12 34", "@", "linkedin", "github", "01 23", "Ville-Test"):
        assert interdit.lower() not in propre.lower(), interdit
    assert propre.splitlines()[0] == cv.NOM_MASQUE
    assert cv.COORDONNEES_MASQUEES in propre
    assert "École d’ingénieurs (ENSX)" in propre and "Français" in propre


def test_signature_d_une_lettre():
    lettre = "Madame, Monsieur,\nJe candidate.\nCordialement,\nJeanne Exemple"
    assert cv.anonymiser(lettre, "Jeanne Exemple").endswith("Cordialement,\n" + cv.NOM_MASQUE)


def test_sans_fichier(tmp_path):
    config = {"profil": {"cv": str(tmp_path / "absent.pdf"), "modele_lettre": str(tmp_path / "absent.txt")}}
    assert cv.texte_cv(config) is None and cv.modele_lettre(config) is None
    assert cv.empreinte(None) is None and len(cv.empreinte("abc")) == 16
