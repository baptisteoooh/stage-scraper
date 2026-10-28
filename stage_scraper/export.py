"""Export Excel des offres et des candidatures."""
import io

import pandas as pd

from . import requetes

COLONNES_OFFRES = {
    "score": "Note", "categorie": "Catégorie", "section": "Section", "titre": "Titre", "entreprise": "Entreprise",
    "type_contrat": "Contrat", "lieu": "Lieu", "teletravail": "Télétravail", "duree": "Durée",
    "date_debut": "Début", "gratification": "Gratification", "date_publication": "Publiée le",
    "resume": "Résumé", "pourquoi": "Pourquoi cette note", "lien": "Lien", "source": "Source",
    "contact": "Contact",
}
COLONNES_CANDIDATURES = {
    "entreprise": "Entreprise", "poste": "Poste", "statut": "Statut", "date_creation": "Créée le",
    "date_candidature": "Candidature envoyée le", "date_relance": "Relance le", "lien": "Lien", "notes": "Notes",
}


def classeur_excel(conn) -> bytes:
    """Un fichier .xlsx avec deux feuilles : Offres (gardées) et Candidatures."""
    offres = pd.DataFrame(requetes.offres_visibles(conn), columns=list(COLONNES_OFFRES))
    candidatures = pd.DataFrame(requetes.candidatures(conn), columns=list(COLONNES_CANDIDATURES))
    tampon = io.BytesIO()
    with pd.ExcelWriter(tampon, engine="openpyxl") as classeur:
        for feuille, tableau, colonnes in (("Offres", offres, COLONNES_OFFRES),
                                           ("Candidatures", candidatures, COLONNES_CANDIDATURES)):
            tableau.rename(columns=colonnes).to_excel(classeur, sheet_name=feuille, index=False)
            page = classeur.sheets[feuille]
            page.freeze_panes = "A2"
            for colonne in page.columns:
                largeur = max((len(str(c.value)) for c in colonne if c.value is not None), default=8)
                page.column_dimensions[colonne[0].column_letter].width = min(max(10, largeur + 2), 60)
    return tampon.getvalue()
