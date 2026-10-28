"""Page « Candidatures » : un tableau de bord en colonnes, une colonne par étape.

Chaque candidature est une carte. Un bouton fait passer à l'étape suivante (les dates se
remplissent seules), « Détails » ouvre une fenêtre pour tout modifier. Toute action peut être
annulée juste après (bouton « Annuler » en haut de la page).
"""
import html
from collections import Counter
from contextlib import closing
from datetime import date

import pandas as pd
import streamlit as st

from . import db, export, requetes
from .config import chemin_projet

# (clé, titre, symbole) ; « terminé » regroupe refus et accepté.
ETAPES = [
    ("à postuler", "À postuler", "📝"),
    ("postulé", "Postulé", "📨"),
    ("relancé", "Relancé", "🔔"),
    ("entretien", "Entretien", "💬"),
    ("terminé", "Terminé", "🏁"),
]
# Action principale proposée sur la carte, selon l'étape.
ACTION_SUIVANTE = {
    "à postuler": ("J'ai postulé", "postulé"),
    "postulé": ("J'ai relancé", "relancé"),
    "relancé": ("Entretien obtenu", "entretien"),
    "entretien": ("Accepté 🎉", "accepté"),
}
LIBELLES_STATUT = {"à postuler": "À postuler", "postulé": "Postulé", "relancé": "Relancé",
                   "entretien": "Entretien", "refus": "Refus", "accepté": "Accepté"}


def bouton_export(conn) -> None:
    """Bouton « Exporter en Excel » (offres + candidatures), utilisé dans les en-têtes de page."""
    st.download_button("📥 Exporter en Excel", export.classeur_excel(conn),
                       file_name=f"stage_scraper_{date.today().isoformat()}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       width="stretch")


def _jour(texte: str | None) -> date | None:
    try:
        return date.fromisoformat(str(texte)[:10]) if texte else None
    except ValueError:
        return None


def _date_courte(texte: str | None) -> str:
    jour = _jour(texte)
    return jour.strftime("%d/%m") if jour else ""


def relance_due(c: dict, aujourd_hui: date | None = None) -> bool:
    jour = _jour(c.get("date_relance"))
    return bool(jour) and c["statut"] in ("postulé", "relancé") and jour <= (aujourd_hui or date.today())


def etape(c: dict) -> str:
    return "terminé" if c["statut"] in ("refus", "accepté") else c["statut"]


def correspond(c: dict, recherche: str) -> bool:
    recherche = recherche.strip().lower()
    if not recherche:
        return True
    return any(recherche in (c.get(champ) or "").lower() for champ in ("entreprise", "poste", "notes"))


# =========================================================================== page

def afficher(conn, config: dict) -> None:
    relance_jours = int(config.get("candidatures", {}).get("relance_jours", 7))
    st.title("📋 Candidatures")

    _bandeau_annulation(conn)

    toutes = requetes.candidatures(conn)
    haut = st.columns([3, 1.1, 0.9], vertical_alignment="bottom")
    recherche = haut[0].text_input("Rechercher", placeholder="Rechercher une entreprise, un poste ou une note…",
                                   label_visibility="collapsed", key="recherche_candidatures")
    if haut[1].button("＋ Nouvelle candidature", type="primary", width="stretch"):
        fenetre_nouvelle(config)
    with haut[2]:
        bouton_export(conn)

    if not toutes:
        st.markdown("")
        with st.container(border=True, key="carte_vide"):
            st.markdown("#### Aucune candidature pour l'instant")
            st.markdown("Ouvre une offre de la page **Offres** et clique **Postuler**, ou ajoute une candidature "
                        "faite ailleurs avec **＋ Nouvelle candidature**.")
        return

    dues = [c for c in toutes if relance_due(c)]
    if dues:
        compte = Counter(c["entreprise"] or c["poste"] or "?" for c in dues)
        noms = ", ".join(nom + (f" ×{n}" if n > 1 else "") for nom, n in compte.items())
        st.info(f"🔔 **{len(dues)} relance(s) à faire** : {noms}")

    visibles = [c for c in toutes if correspond(c, recherche)]
    if recherche and not visibles:
        st.caption("Aucune candidature ne correspond à cette recherche.")

    # Les 4 étapes en cours, en colonnes larges ; les candidatures terminées sont rangées dessous.
    en_cours = [e for e in ETAPES if e[0] != "terminé"]
    colonnes = st.columns(len(en_cours), gap="medium")
    for colonne, (cle, titre, symbole) in zip(colonnes, en_cours):
        cartes = [c for c in visibles if etape(c) == cle]
        with colonne:
            with st.container(key=f"colonne_{cle.replace(' ', '_')}"):
                st.markdown(f'<div class="etape-titre">{symbole} {titre} '
                            f'<span class="etape-compte">{len(cartes)}</span></div>', unsafe_allow_html=True)
                if not cartes:
                    st.markdown('<div class="etape-vide">Rien ici pour l’instant</div>', unsafe_allow_html=True)
                for c in cartes:
                    carte(conn, config, c, relance_jours)

    terminees = [c for c in visibles if etape(c) == "terminé"]
    st.markdown("")
    if terminees:
        acceptees = sum(c["statut"] == "accepté" for c in terminees)
        with st.expander(f"🏁 Terminées ({len(terminees)} · {acceptees} acceptée(s), "
                         f"{len(terminees) - acceptees} refus)"):
            grille = st.columns(4, gap="medium")
            for i, c in enumerate(terminees):
                with grille[i % 4]:
                    carte(conn, config, c, relance_jours)

    with st.expander("Vue tableau (pour modifier beaucoup de lignes d'un coup)"):
        vue_tableau(conn, toutes)


def carte(conn, config: dict, c: dict, relance_jours: int) -> None:
    e = html.escape
    with st.container(border=True, key=f"carte_{c['id']}"):
        st.markdown(f'<div class="carte-entreprise">{e(c["entreprise"] or "Entreprise ?")}</div>'
                    f'<div class="carte-poste">{e(c["poste"] or "")}</div>', unsafe_allow_html=True)

        infos = []
        if c["date_candidature"]:
            infos.append(f"envoyée le {_date_courte(c['date_candidature'])}")
        if c["date_relance"] and c["statut"] in ("postulé", "relancé") and not relance_due(c):
            infos.append(f"relance le {_date_courte(c['date_relance'])}")
        if infos:
            st.markdown(f'<div class="carte-meta">{e(" · ".join(infos))}</div>', unsafe_allow_html=True)

        badges = []
        if relance_due(c):
            badges.append(":orange-badge[Relance à faire]")
        if c["statut"] == "accepté":
            badges.append(":green-badge[Accepté]")
        elif c["statut"] == "refus":
            badges.append(":gray-badge[Refus]")
        if c.get("lettre"):
            badges.append(":blue-badge[Lettre prête]")
        if badges:
            st.markdown(" ".join(badges))

        action = ACTION_SUIVANTE.get(c["statut"])
        if action:
            libelle, suivant = action
            if st.button(libelle, key=f"avancer_{c['id']}", type="primary", width="stretch"):
                avant = requetes.changer_statut(conn, c["id"], suivant, relance_jours)
                _retenir(f"{c['entreprise'] or 'Candidature'} : {LIBELLES_STATUT[suivant]}", avant)
                st.rerun()
        if st.button("Détails", key=f"details_{c['id']}", type="tertiary", width="stretch"):
            fenetre_details(config, c["id"], relance_jours)


# =========================================================================== annulation

def _retenir(message: str, avant: dict) -> None:
    st.session_state["derniere_action"] = {"message": message, "avant": avant}


def _bandeau_annulation(conn) -> None:
    action = st.session_state.get("derniere_action")
    if not action:
        return
    c = st.columns([5, 1], vertical_alignment="center")
    c[0].success(action["message"])
    if c[1].button("↩︎ Annuler", width="stretch"):
        requetes.restaurer_candidature(conn, action["avant"])
        st.session_state.pop("derniere_action")
        st.rerun()


# =========================================================================== fenêtres

def _connexion(config: dict):
    """Connexion propre à une fenêtre (Streamlit relance les fenêtres seules, dans un autre fil d'exécution)."""
    return closing(db.connecter(chemin_projet(config["general"]["base_de_donnees"])))


@st.dialog("Nouvelle candidature")
def fenetre_nouvelle(config: dict) -> None:
    with _connexion(config) as conn:
        _nouvelle(conn)


def _nouvelle(conn) -> None:
    entreprise = st.text_input("Entreprise")
    poste = st.text_input("Poste")
    lien = st.text_input("Lien de l'offre (facultatif)", placeholder="https://…")
    c = st.columns(2)
    statut = c[0].selectbox("Étape", requetes.STATUTS, index=1, format_func=LIBELLES_STATUT.get)
    envoyee = c[1].date_input("Envoyée le", value=date.today() if statut != "à postuler" else None,
                              format="DD/MM/YYYY")
    notes = st.text_area("Notes (facultatif)", placeholder="Contact, référence, impressions…")
    if st.button("Ajouter", type="primary", width="stretch"):
        if not (entreprise.strip() or poste.strip()):
            st.error("Indique au moins l'entreprise ou le poste.")
            return
        identifiant = requetes.creer_candidature(conn, entreprise=entreprise.strip() or None,
                                                 poste=poste.strip() or None, lien=lien.strip() or None,
                                                 statut=statut, notes=notes.strip() or None)
        if envoyee:
            requetes.modifier_candidature(conn, identifiant, date_candidature=envoyee)
        st.rerun()


@st.dialog("Candidature", width="large")
def fenetre_details(config: dict, candidature_id: int, relance_jours: int) -> None:
    with _connexion(config) as conn:
        _details(conn, candidature_id, relance_jours)


def _details(conn, candidature_id: int, relance_jours: int) -> None:
    c = requetes.candidature(conn, candidature_id)
    if not c:
        st.caption("Cette candidature n'existe plus.")
        return
    entreprise = st.text_input("Entreprise", c["entreprise"] or "")
    poste = st.text_input("Poste", c["poste"] or "")
    statut = st.segmented_control("Étape", requetes.STATUTS, default=c["statut"], format_func=LIBELLES_STATUT.get,
                                  key=f"etape_{candidature_id}") or c["statut"]
    d = st.columns(2)
    envoyee = d[0].date_input("Envoyée le", value=_jour(c["date_candidature"]), format="DD/MM/YYYY")
    relance = d[1].date_input("Relancer le", value=_jour(c["date_relance"]), format="DD/MM/YYYY",
                              help=f"Proposé automatiquement {relance_jours} jours après l'envoi.")
    lien = st.text_input("Lien de l'offre", c["lien"] or "")
    notes = st.text_area("Notes", c["notes"] or "", height=120)
    if c["lien"]:
        st.link_button("Voir l'offre", c["lien"])
    if c.get("lettre"):
        with st.expander("✉️ Lettre de motivation gardée"):
            st.text(c["lettre"])
            st.download_button("Télécharger (.txt)", c["lettre"], file_name="lettre.txt", mime="text/plain")

    st.markdown("")
    b = st.columns([2, 1])
    if b[0].button("Enregistrer", type="primary", width="stretch"):
        _retenir(f"{entreprise or 'Candidature'} : modifications enregistrées", c)
        requetes.modifier_candidature(conn, candidature_id, entreprise=entreprise, poste=poste, statut=statut,
                                      date_candidature=envoyee, date_relance=relance, lien=lien, notes=notes)
        st.rerun()
    if b[1].button("Supprimer", width="stretch"):
        avant = requetes.supprimer_candidature(conn, candidature_id)
        _retenir(f"{c['entreprise'] or 'Candidature'} supprimée", avant)
        st.rerun()


# =========================================================================== vue tableau

def vue_tableau(conn, lignes: list[dict]) -> None:
    st.caption("Modifie les cases, ajoute une ligne en bas ou supprime-en une, puis clique **Enregistrer le tableau**.")
    colonnes = ["id", "entreprise", "poste", "statut", "date_candidature", "date_relance", "lien", "notes"]
    tableau = pd.DataFrame(lignes, columns=colonnes)
    for c in ("date_candidature", "date_relance"):
        tableau[c] = pd.to_datetime(tableau[c], errors="coerce").dt.date
    modifie = st.data_editor(
        tableau, key="editeur_candidatures", num_rows="dynamic", hide_index=True, width="stretch",
        disabled=["id"], column_order=colonnes[1:],
        column_config={
            "entreprise": st.column_config.TextColumn("Entreprise"),
            "poste": st.column_config.TextColumn("Poste", width="large"),
            "statut": st.column_config.SelectboxColumn("Étape", options=requetes.STATUTS, required=True,
                                                       default="à postuler"),
            "date_candidature": st.column_config.DateColumn("Envoyée le", format="DD/MM/YYYY"),
            "date_relance": st.column_config.DateColumn("Relance le", format="DD/MM/YYYY"),
            "lien": st.column_config.LinkColumn("Lien"),
            "notes": st.column_config.TextColumn("Notes", width="large"),
        })
    if st.button("Enregistrer le tableau"):
        bilan = requetes.enregistrer_candidatures(conn, modifie.to_dict("records"))
        st.toast(f"{bilan['ajoutees']} ajoutée(s), {bilan['modifiees']} modifiée(s), "
                 f"{bilan['supprimees']} supprimée(s).")
        st.session_state.pop("editeur_candidatures", None)
        st.rerun()
