"""Offres affichées en vignettes (page Offres), de la plus intéressante à la moins intéressante.

Chaque vignette montre l'essentiel : note, entreprise, poste, lieu, durée, début, gratification,
télétravail, résumé en 2 lignes et date de publication. Le bouton « Voir la fiche » ouvre le détail
complet dans une fenêtre (avec Postuler, Pas intéressé, Lettre de motivation).
"""
import html
import re
from contextlib import closing
from datetime import date

import streamlit as st

from . import db, requetes
from .config import chemin_projet

PAR_PAGE = 24      # vignettes affichées d'un coup ; le bouton « Afficher plus » ajoute les suivantes

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]


# =========================================================================== mise en forme

def _e(texte) -> str:
    """Texte venu des sites d'offres : échappé avant d'être mis dans du HTML."""
    return html.escape(str(texte), quote=True)


def niveau_note(score) -> str:
    if score is None:
        return "attente"
    return "haute" if score >= 8 else "moyenne" if score >= 5 else "basse"


def lieu_court(lieu: str | None) -> str | None:
    """« Levallois-Perret, Ile-de-France, France » -> « Levallois-Perret »."""
    if not lieu:
        return None
    return lieu.split(",")[0].strip() or lieu


def debut_lisible(o: dict) -> str | None:
    """Date de début : « 2027-04-01 » -> « avril 2027 » ; sinon le texte trouvé par l'IA."""
    brut = o["date_debut"] or o["date_debut_ia"]
    if not brut:
        return None
    trouve = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", brut.strip())
    if trouve and 1 <= int(trouve[2]) <= 12:
        return f"{MOIS[int(trouve[2]) - 1]} {trouve[1]}"
    return brut


def anciennete(date_publication: str | None, aujourd_hui: date | None = None) -> str | None:
    if not date_publication:
        return None
    try:
        jours = ((aujourd_hui or date.today()) - date.fromisoformat(date_publication[:10])).days
    except ValueError:
        return None
    if jours <= 0:
        return "publiée aujourd'hui"
    if jours == 1:
        return "publiée hier"
    return f"publiée il y a {jours} j"


def _court(texte: str | None, longueur: int = 32) -> str | None:
    if not texte:
        return None
    texte = " ".join(texte.split())
    return texte if len(texte) <= longueur else texte[:longueur - 1].rstrip() + "…"


def html_vignette(o: dict, suivie: bool = False, aujourd_hui: date | None = None) -> str:
    """Contenu d'une vignette (sans les boutons)."""
    niveau = niveau_note(o["score"])
    note = (f'<b>{o["score"]}</b><span>/10</span>' if o["score"] is not None else "<b>—</b>")

    badges = []
    if not o["vue"]:
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
        f'<div class="v-pied">{_e(" · ".join(pied))}</div>'
        '</div>'
    )


# =========================================================================== affichage

def _slug(texte: str) -> str:
    """Clé utilisable comme nom de classe CSS (Streamlit en fait « st-key-<clé> »)."""
    return re.sub(r"[^a-z0-9]+", "_", texte.lower().encode("ascii", "ignore").decode()).strip("_")


def grille(conn, config: dict, offres: list[dict], cle: str, page_lettre=None) -> None:
    """Vignettes triées comme la liste reçue (par note décroissante).

    La grille est faite en CSS (style.py) : 3 ou 4 vignettes par rangée sur grand écran,
    2 sur une demi-fenêtre, 1 sur une fenêtre étroite.
    """
    if not offres:
        st.markdown('<div class="etape-vide">Aucune offre ici pour l’instant</div>', unsafe_allow_html=True)
        return
    cle = _slug(cle)
    suivies = {c["offre_id"] for c in requetes.candidatures(conn) if c["offre_id"]}
    nb = st.session_state.get(f"nb_{cle}", PAR_PAGE)

    a_ouvrir = None
    with st.container(key=f"grille_{cle}"):
        for o in offres[:nb]:
            with st.container(border=True, key=f"carte_offre_{cle}_{o['id']}"):
                st.markdown(html_vignette(o, o["id"] in suivies), unsafe_allow_html=True)
                boutons = st.columns(2)
                if boutons[0].button("Voir la fiche", key=f"fiche_{cle}_{o['id']}", width="stretch"):
                    a_ouvrir = o["id"]
                if o["lien"]:
                    boutons[1].link_button("Ouvrir l'offre ↗", o["lien"], width="stretch")
    if a_ouvrir is not None:  # fenêtre ouverte hors de la grille, pour ne pas y laisser une case vide
        fenetre_fiche(config, a_ouvrir, cle, page_lettre)

    if len(offres) > nb:
        reste = len(offres) - nb
        if st.button(f"Afficher plus ({reste} autre{'s' if reste > 1 else ''})", key=f"plus_{cle}",
                     width="stretch"):
            st.session_state[f"nb_{cle}"] = nb + PAR_PAGE
            st.rerun()


@st.dialog("Offre", width="large")
def fenetre_fiche(config: dict, offre_id: int, cle: str, page_lettre=None) -> None:
    # Connexion propre à la fenêtre : Streamlit la relance seule, dans un autre fil d'exécution.
    with closing(db.connecter(chemin_projet(config["general"]["base_de_donnees"]))) as conn:
        fiche(conn, offre_id, cle, page_lettre)


def fiche(conn, offre_id: int, cle: str, page_lettre=None) -> None:
    """Détail complet d'une offre, avec les boutons Postuler, Pas intéressé et Lettre."""
    o = requetes.offre(conn, offre_id)
    if o is None:
        st.warning("Cette offre n'existe plus.")
        return
    if not o["vue"]:
        requetes.marquer_vue(conn, o["id"])
        st.session_state.setdefault("ouvertes", set()).add(o["id"])

    haut = st.columns([5, 1])
    haut[0].subheader(o["titre"])
    haut[0].markdown(f"**{o['entreprise'] or 'Entreprise inconnue'}** — {o['lieu'] or 'lieu inconnu'}")
    if o["score"] is not None:
        haut[1].metric("Note IA", f"{o['score']} / 10", o["categorie"], delta_color="off")

    badges = []
    if o["type_contrat"] == "cdd":
        badges.append(":orange-badge[CDD]")
    if o["section"]:
        badges.append(f":blue-badge[{o['section']}]")
    if o["poste_ia_data"]:
        badges.append(":violet-badge[IA / data]")
    if badges:
        st.markdown(" ".join(badges))

    if o["resume"]:
        st.markdown(f"**Résumé** : {o['resume']}")
    if o["pourquoi"]:
        st.markdown(f"**Pourquoi cette note** : {o['pourquoi']}")
    if o["score"] is None:
        st.info("Pas encore notée par l'IA.")
    if o["exclusion_prefiltre"] or o["exclusion_ia"]:
        st.warning(f"Écartée : {o['exclusion_prefiltre'] or o['exclusion_ia']}")

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

    liens = st.columns(4)
    if o["lien"]:
        liens[0].link_button("Ouvrir l'offre ↗", o["lien"])
    for i, autre in enumerate(requetes.doublons_de(conn, o["id"])[:3], start=1):
        if autre["lien"]:
            liens[i].link_button(f"Aussi sur {autre['site_origine'] or autre['source']}", autre["lien"])

    if o["description"]:
        with st.expander("Description complète"):
            st.text(o["description"])

    actions = st.columns(3)
    candidature = requetes.candidature_de(conn, o["id"])
    with actions[0]:
        if candidature:
            st.success(f"Candidature suivie (statut : {candidature['statut']}).")
        elif st.button("✅ Postuler", key=f"postuler_{cle}_{o['id']}", type="primary"):
            requetes.creer_candidature(conn, offre_id=o["id"])
            st.toast("Ajoutée aux candidatures, statut « à postuler ».")
            st.rerun()
    with actions[1]:
        if o["pas_interesse"]:
            if st.button("Annuler « pas intéressé »", key=f"annuler_{cle}_{o['id']}"):
                requetes.annuler_pas_interesse(conn, o["id"])
                st.rerun()
        else:
            with st.popover("👎 Pas intéressé"):
                raison = st.text_input("Raison (facultatif)", key=f"raison_{cle}_{o['id']}",
                                       placeholder="ex. trop orienté finance, trop loin…")
                if st.button("Confirmer", key=f"pasint_{cle}_{o['id']}"):
                    requetes.marquer_pas_interesse(conn, o["id"], raison)
                    st.toast("Offre masquée. L'IA s'en servira d'exemple pour les prochaines notes.")
                    st.rerun()
    with actions[2]:
        if st.button("✍️ Lettre de motivation", key=f"lettre_{cle}_{o['id']}"):
            st.session_state["lettre_offre_id"] = o["id"]
            if page_lettre is not None:
                st.switch_page(page_lettre)
