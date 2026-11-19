"""Vignettes d'offres, fiche détaillée et décisions (page À trier, Assistant).

Chaque vignette montre l'essentiel : note, entreprise, poste, lieu, durée, début, gratification,
télétravail, résumé et date de publication. Trois décisions, en un clic, depuis la vignette ou la fiche :
✅ Je candidate (l'offre part dans Ma sélection), 👎 Pas pour moi (masquée ; la raison, facultative,
sert d'exemple à l'IA), ⏳ Plus tard (rangée à part). Un bandeau permet d'annuler la dernière décision.
"""
import html
import re
from contextlib import closing
from datetime import date
from pathlib import Path

import streamlit as st

from . import db, decisions, expiration, page_dossier, requetes, selection
from .config import chemin_projet
from .presentation import (  # noqa: F401  (réexportées : tests, autres pages)
    MOIS, SECTIONS_COURTES, SOURCES_EXTRAIT, _court, anciennete, debut_lisible, extrait, lieu_court, niveau_note)

PAR_PAGE = 24      # vignettes affichées d'un coup ; le bouton « Afficher plus » ajoute les suivantes

# =========================================================================== mise en forme

def _e(texte) -> str:
    """Texte venu des sites d'offres : échappé avant d'être mis dans du HTML."""
    return html.escape(str(texte), quote=True)


def html_vignette(o: dict, suivie: bool = False, aujourd_hui: date | None = None,
                  avec_section: bool = False, nouveau: bool | None = None, avec_extrait: bool = True) -> str:
    """Contenu d'une vignette (sans les boutons). `avec_section` : étiquette Santé / Hors santé / À négocier.

    `nouveau` : badge « Nouvelle » (par défaut : offre jamais ouverte). `avec_extrait` : début de l'annonce.
    """
    niveau = niveau_note(o["score"])
    note = (f'<b>{o["score"]}</b><span>/10</span>' if o["score"] is not None else "<b>—</b>")

    badges = []
    if o.get("expiration"):
        badges.append('<span class="v-badge v-expiree">Expirée</span>')
    if avec_section and o["section"]:
        badges.append(f'<span class="v-badge v-section">{_e(SECTIONS_COURTES.get(o["section"], o["section"]))}</span>')
    if (not o["vue"]) if nouveau is None else nouveau:
        badges.append('<span class="v-badge v-nouveau">Nouvelle</span>')
    if o["poste_ia_data"]:
        badges.append('<span class="v-badge v-ia">IA / data</span>')
    if o["type_contrat"] == "cdd":
        badges.append('<span class="v-badge v-cdd">CDD</span>')
    if suivie:
        badges.append('<span class="v-badge v-suivie">Dans mes candidatures</span>')

    # Infos clés : durée et début restent affichés même inconnus (ce sont les critères principaux).
    duree = o["duree"] or o["duree_ia"]
    debut = debut_lisible(o)
    infos = [
        ("📍", lieu_court(o["lieu"]) or "Lieu ?", not o["lieu"]),
        ("⏳", _court(duree, 26) or "Durée ?", not duree),
        ("📅", _court(debut, 26) or "Début ?", not debut),
    ]
    if o["teletravail"]:
        infos.append(("🏠", o["teletravail"].capitalize(), False))
    if o["gratification"]:
        infos.append(("💶", _court(o["gratification"], 28), False))
    puces = "".join(f'<span class="v-info{" v-inconnu" if inconnu else ""}">{icone} {_e(texte)}</span>'
                    for icone, texte, inconnu in infos)

    pied = [x for x in (anciennete(o["date_publication"], aujourd_hui), o["site_origine"] or o["source"]) if x]
    resume = o["resume"] or ("Pas encore notée par l'IA." if o["score"] is None else "")
    texte_annonce = extrait(o["description"]) if avec_extrait else None
    bloc_extrait = (f'<div class="v-extrait"><span class="v-label">Extrait de l’annonce</span>{_e(texte_annonce)}</div>'
                    if texte_annonce else "")

    return (
        '<div class="vignette">'
        '<div class="v-haut">'
        f'<div class="v-entreprise">{_e(o["entreprise"] or "Entreprise inconnue")}</div>'
        f'<div class="v-note v-note-{niveau}" title="{_e(o["categorie"] or "Note IA")}">{note}</div>'
        '</div>'
        f'<div class="v-titre" title="{_e(o["titre"])}">{_e(o["titre"])}</div>'
        f'<div class="v-badges">{"".join(badges)}</div>'
        f'<div class="v-infos">{puces}</div>'
        f'<div class="v-resume">{_e(resume)}</div>'
        f'{bloc_extrait}'
        f'<div class="v-pied">{_e(" · ".join(pied))}</div>'
        '</div>'
    )


# =========================================================================== affichage

def _slug(texte: str) -> str:
    """Clé utilisable comme nom de classe CSS (Streamlit en fait « st-key-<clé> »)."""
    return re.sub(r"[^a-z0-9]+", "_", texte.lower().encode("ascii", "ignore").decode()).strip("_")


# =========================================================================== décisions

RAISONS = decisions.RAISONS
TEXTES_DECISION = {**decisions.TEXTES, "candidate": "ajoutée à Ma sélection (en préparation)"}


def decider(conn, offre_id: int, action: str) -> None:
    """Applique une décision et la retient pour le bandeau (qui permet de l'annuler)."""
    st.session_state["derniere_decision"] = decisions.appliquer(conn, offre_id, action)


def _decider_depuis_vignette(chemin_base: str, offre_id: int, action: str) -> None:
    """Appelé juste après le clic, avant de réafficher la page : la vignette disparaît tout de suite."""
    with closing(db.connecter(Path(chemin_base))) as conn:
        decider(conn, offre_id, action)


def annuler_decision(conn, d: dict) -> None:
    decisions.annuler(conn, d)


def bandeau_decision(conn, page_fiche=None) -> None:
    """Dernière décision : rappel, raison facultative (« pas pour moi »), Ouvrir la fiche, Annuler."""
    d = st.session_state.get("derniere_decision")
    if not d:
        return
    nom = f"**{_e(d['titre'])}**" + (f" — {_e(d['entreprise'])}" if d["entreprise"] else "")
    icone = {"candidate": "✅", "ecarte": "👎", "plus_tard": "⏳", "remettre": "↩️"}[d["action"]]
    with st.container(border=True, key="bandeau_decision"):
        ligne = st.columns([6, 1.6, 1.1, 0.5], vertical_alignment="center")
        ligne[0].markdown(f"{icone} {nom} {TEXTES_DECISION[d['action']]}.", unsafe_allow_html=True)
        if d["action"] == "candidate" and ligne[1].button("📝 Ouvrir la fiche", type="primary", width="stretch",
                                                          help="Lettre de motivation, conseils CV, analyse de l'offre"):
            st.session_state.pop("derniere_decision", None)
            page_dossier.ouvrir_fiche(conn, d["offre_id"], page_fiche)
        if ligne[2].button("↩️ Annuler", width="stretch", key="annuler_decision"):
            annuler_decision(conn, d)
            st.session_state.pop("derniere_decision", None)
            st.rerun()
        if ligne[3].button("✕", key="fermer_decision", help="Fermer", type="tertiary"):
            st.session_state.pop("derniere_decision", None)
            st.rerun()
        if d["action"] == "ecarte":
            raison = st.pills("Pourquoi ? (facultatif : l'IA s'en servira pour mieux noter)", RAISONS,
                              key=f"raison_{d['offre_id']}")
            if raison != d.get("raison"):
                requetes.preciser_raison(conn, d["offre_id"], raison)
                d["raison"] = raison


def boutons_decision(chemin_base: str, o: dict, cle: str) -> bool:
    """Les 3 décisions + Détails, en 2 rangées. Renvoie vrai si BAP veut voir le détail."""
    haut, bas = st.columns(2), st.columns(2)
    args = lambda action: (chemin_base, o["id"], action)  # noqa: E731
    haut[0].button("✅ Je candidate", key=f"candidate_{cle}", type="primary", width="stretch",
                   on_click=_decider_depuis_vignette, args=args("candidate"),
                   help="L'offre part dans Ma sélection (en préparation) ; aucune IA ne se lance")
    haut[1].button("👎 Pas pour moi", key=f"ecarte_{cle}", width="stretch",
                   on_click=_decider_depuis_vignette, args=args("ecarte"))
    if o["favori"]:
        bas[0].button("↩️ À trier", key=f"remettre_{cle}", width="stretch", help="Remettre dans les offres à trier",
                      on_click=_decider_depuis_vignette, args=args("remettre"))
    else:
        bas[0].button("⏳ Plus tard", key=f"plus_tard_{cle}", width="stretch", help="Ranger à part pour y revenir",
                      on_click=_decider_depuis_vignette, args=args("plus_tard"))
    return bas[1].button("🔍 Détails", key=f"details_{cle}", width="stretch",
                         help="Description complète, pourquoi cette note, lien vers l'annonce")


@st.dialog("Offre", width="large")
def fenetre_fiche(config: dict, offre_id: int, cle: str, page_fiche=None) -> None:
    # Connexion propre à la fenêtre : Streamlit la relance seule, dans un autre fil d'exécution.
    with closing(db.connecter(chemin_projet(config["general"]["base_de_donnees"]))) as conn:
        fiche(conn, offre_id, cle, page_fiche)


def fiche(conn, offre_id: int, cle: str, page_fiche=None) -> None:
    """Détail complet d'une offre, avec les mêmes décisions que la vignette, en haut."""
    o = requetes.offre(conn, offre_id)
    if o is None:
        st.warning("Cette offre n'existe plus.")
        return

    haut = st.columns([5, 1])
    haut[0].subheader(o["titre"])
    haut[0].markdown(f"**{o['entreprise'] or 'Entreprise inconnue'}** — {o['lieu'] or 'lieu inconnu'}")
    if o["score"] is not None:
        haut[1].metric("Note IA", f"{o['score']} / 10", o["categorie"], delta_color="off")

    badges = []
    if o["favori"]:
        badges.append(":orange-badge[⏳ Plus tard]")
    if o["type_contrat"] == "cdd":
        badges.append(":orange-badge[CDD]")
    if o["section"]:
        badges.append(f":blue-badge[{o['section']}]")
    if o["poste_ia_data"]:
        badges.append(":violet-badge[IA / data]")
    if badges:
        st.markdown(" ".join(badges))
    actions_fiche(conn, o, cle, page_fiche)

    details_offre(conn, o)

    if o["expiration"] not in (None, "manuelle"):
        return
    with st.popover("⋯ Autres actions"):
        if o["expiration"] == "manuelle":
            if st.button("Remettre en ligne", key=f"remettre_ligne_{cle}_{o['id']}"):
                expiration.annuler(conn, o["id"])
                st.rerun()
        elif not o["expiration"] and st.button("⌛ Signaler l'offre comme expirée", key=f"expiree_{cle}_{o['id']}",
                                               help="L'offre n'est plus en ligne ou n'accepte plus de candidatures"):
            expiration.marquer_expiree(conn, o["id"])
            st.toast("Offre masquée (expirée).")
            st.rerun()


def details_offre(conn, o: dict) -> None:
    """Résumé, note, infos clés, autres annonces et description d'une offre."""
    if o["resume"]:
        st.markdown(f"**Résumé** : {o['resume']}")
    if o["pourquoi"]:
        st.markdown(f"**Pourquoi cette note** : {o['pourquoi']}")
    if o["score"] is None:
        st.info("Pas encore notée par l'IA.")
    if o["exclusion_prefiltre"] or o["exclusion_ia"]:
        st.warning(f"Écartée : {o['exclusion_prefiltre'] or o['exclusion_ia']}")
    if o["expiration"]:
        st.warning(f"Offre expirée : {expiration.raison(o)}.", icon="⌛")

    infos = {
        "Durée": o["duree"] or o["duree_ia"],
        "Début": debut_lisible(o),
        "Gratification": o["gratification"],
        "Télétravail": o["teletravail"],
        "Publiée le": (o["date_publication"] or "")[:10] or None,
        "Contact": o["contact"],
        "Trouvée via": " / ".join(x for x in (o["source"], o["site_origine"]) if x),
    }
    st.markdown("  \n".join(f"**{k}** : {v}" for k, v in infos.items() if v))

    autres = [a for a in requetes.doublons_de(conn, o["id"])[:3] if a["lien"]]
    if autres:
        liens = st.columns(4)
        for i, autre in enumerate(autres):
            liens[i].link_button(f"Aussi sur {autre['site_origine'] or autre['source']}", autre["lien"])

    st.markdown("**Description de l'annonce**")
    if not o["description"]:
        st.caption("Aucune description fournie par le site : ouvre l'offre pour la lire.")
    else:
        texte = f'<div class="fiche-description">{_e(o["description"].strip())}</div>'
        if len(o["description"]) > 1500:  # longue : dans un cadre qui défile
            with st.container(height=420, border=True):
                st.markdown(texte, unsafe_allow_html=True)
        else:
            st.markdown(texte, unsafe_allow_html=True)
        if o["source"] in SOURCES_EXTRAIT:
            st.caption(f"{o['source'].capitalize()} ne transmet qu'un extrait de l'annonce : "
                       "le texte complet est sur le site (bouton **Voir l'annonce ↗**).")


def actions_fiche(conn, o: dict, cle: str, page_fiche=None) -> None:
    """Décisions en haut de la fiche ; si l'offre est déjà dans Ma sélection, accès direct à sa fiche."""
    candidature = requetes.candidature_de(conn, o["id"])
    ligne = st.columns(4)
    if candidature:
        etape = selection.ETAPES[selection.etape_de(candidature["statut"])][0]
        ligne[0].success(f"Dans Ma sélection ({etape.lower()}).")
        if ligne[1].button("📝 Ouvrir la fiche", key=f"dossier_{cle}_{o['id']}", type="primary"):
            page_dossier.ouvrir_fiche(conn, o["id"], page_fiche)
    elif o["pas_interesse"]:
        ligne[0].info("Écartée (pas pour moi).")
        if ligne[1].button("↩️ Remettre à trier", key=f"annuler_{cle}_{o['id']}"):
            requetes.annuler_pas_interesse(conn, o["id"])
            st.rerun()
    else:
        choix = None
        if ligne[0].button("✅ Je candidate", key=f"candidate_fiche_{cle}_{o['id']}", type="primary", width="stretch"):
            choix = "candidate"
        if ligne[1].button("👎 Pas pour moi", key=f"ecarte_fiche_{cle}_{o['id']}", width="stretch"):
            choix = "ecarte"
        if o["favori"]:
            if ligne[2].button("↩️ À trier", key=f"remettre_fiche_{cle}_{o['id']}", width="stretch"):
                choix = "remettre"
        elif ligne[2].button("⏳ Plus tard", key=f"plus_tard_fiche_{cle}_{o['id']}", width="stretch"):
            choix = "plus_tard"
        if choix:
            decider(conn, o["id"], choix)
            st.rerun()   # ferme la fenêtre ; le bandeau de la page permet d'annuler
    if o["lien"]:
        ligne[3].link_button("Voir l'annonce ↗", o["lien"], width="stretch")
