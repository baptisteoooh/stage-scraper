"""Page « À trier » : les offres sur lesquelles BAP n'a pas encore décidé, comme une boîte de réception.

Chaque offre se règle en un clic (✅ Je candidate, 👎 Pas pour moi, ⏳ Plus tard) puis quitte la liste.
Les plus récentes d'abord ; les offres « Bof » (note < 5) sont masquées sauf si on les demande.
Le but de chaque visite : « Tout est trié ».
"""
import logging
from datetime import datetime

import streamlit as st

from . import collecte, pipeline, requetes, vignettes
from .config import secret

FILTRES = {"Toutes": None, "Santé": "Santé", "Hors santé": "Hors santé mais intéressant", "À négocier": "À négocier"}
PLUS_TARD = "⏳ Plus tard"
TRIS = ["Plus récentes", "Meilleure note"]
SEUIL_BOF = 5
PAR_PAGE = 24
CHAMPS_RECHERCHE = ("titre", "entreprise", "lieu", "resume", "description")


# =========================================================================== petites fonctions (testées)

def est_bof(o: dict) -> bool:
    return o["score"] is not None and o["score"] < SEUIL_BOF


def correspond(o: dict, recherche: str) -> bool:
    mots = recherche.lower().split()
    texte = " ".join(str(o.get(c) or "") for c in CHAMPS_RECHERCHE).lower()
    return all(m in texte for m in mots)


def phrase_scrap(s: dict | None, maintenant: datetime | None = None) -> str:
    """« Dernier scrap aujourd'hui à 8h02 (automatique) : 12 nouvelles offres, dont 2 notées 8 ou plus. »"""
    if not s:
        return "Aucun scrap pour l'instant : clique sur « Lancer le scrap »."
    quand = datetime.fromisoformat(s["date"])
    jours = ((maintenant or datetime.now()).date() - quand.date()).days
    jour = {0: "aujourd'hui", 1: "hier"}.get(jours, f"le {quand:%d/%m}")
    texte = (f"Dernier scrap {jour} à {quand:%H}h{quand:%M} ({'automatique' if s['auto'] else 'manuel'}) : "
             + (f"{s['nouvelles']} nouvelle{'s' if s['nouvelles'] > 1 else ''} offre{'s' if s['nouvelles'] > 1 else ''}"
                if s["nouvelles"] else "aucune nouvelle offre"))
    if s["top"]:
        texte += f", dont {s['top']} notée{'s' if s['top'] > 1 else ''} 8 ou plus"
    if s["en_erreur"]:
        texte += f" · ⚠️ en erreur : {', '.join(s['en_erreur'])} (détail dans Journal)"
    return texte + "."


# =========================================================================== page

def afficher(conn, config: dict, page_fiche=None) -> None:
    entete = st.columns([4, 1.2, 0.5], vertical_alignment="bottom")
    entete[0].title("📥 À trier")
    lancer = entete[1].button("🔄 Lancer le scrap", type="primary", width="stretch")
    with entete[2].popover("⋯", help="Choisir les sources du scrap", width="stretch"):
        actives = [n for n, r in config["sources"].items() if r.get("actif") and n in collecte.SOURCES]
        sources = st.multiselect("Sources (vide = toutes les sources actives, sauf Google Jobs réservé au passage "
                                 "de 8 h)", list(collecte.SOURCES), placeholder="Toutes les sources actives",
                                 key="sources_choisies")
        st.caption("Actives : " + ", ".join(actives))
    if lancer:
        lancer_scrap(conn, config, sources or None)

    scrap = requetes.dernier_scrap(conn)
    st.caption(phrase_scrap(scrap))
    vignettes.bandeau_decision(conn, page_fiche)

    toutes = requetes.offres_a_trier(conn)
    if any(o["score"] is None for o in toutes) and not secret("GEMINI_API_KEY"):
        st.info("Des offres attendent la note de l'IA : ajoute GEMINI_API_KEY dans le fichier .env, "
                "puis relance un scrap.")

    # Recherche, tri, offres Bof
    reglage = st.columns([3, 2, 1.6], vertical_alignment="center")
    recherche = reglage[0].text_input("Rechercher", placeholder="🔎 Rechercher (poste, entreprise, lieu, mot de "
                                      "l'annonce…)", label_visibility="collapsed", key="recherche_a_trier")
    # Tri retenu pour toute la visite (la clé du bouton est oubliée quand on change de page).
    tri = reglage[1].segmented_control("Trier", TRIS, key="tri_a_trier_bouton", label_visibility="collapsed",
                                       default=st.session_state.get("tri_a_trier", TRIS[0]))
    tri = st.session_state["tri_a_trier"] = tri or st.session_state.get("tri_a_trier", TRIS[0])
    if recherche.strip():
        toutes = [o for o in toutes if correspond(o, recherche)]
    nb_bof = sum(1 for o in toutes if est_bof(o) and not o["favori"])
    voir_bof = reglage[2].toggle(f"Voir les « Bof » ({nb_bof})", key="voir_bof",
                                 help=f"Offres notées moins de {SEUIL_BOF}/10, masquées par défaut")
    if not voir_bof:
        toutes = [o for o in toutes if not est_bof(o) or o["favori"]]

    plus_tard = [o for o in toutes if o["favori"]]
    a_trier = [o for o in toutes if not o["favori"]]
    comptes = {nom: sum(1 for o in a_trier if section is None or o["section"] == section)
               for nom, section in FILTRES.items()}
    comptes[PLUS_TARD] = len(plus_tard)
    choix = st.segmented_control("Afficher", list(comptes), default="Toutes", key="filtre_a_trier",
                                 format_func=lambda nom: f"{nom}  {comptes[nom]}", label_visibility="collapsed")
    choix = choix or "Toutes"

    if choix == PLUS_TARD:
        liste = plus_tard
        vide = "Rien de rangé « plus tard »."
    else:
        liste = [o for o in a_trier if FILTRES[choix] is None or o["section"] == FILTRES[choix]]
        vide = ("Aucune offre ne correspond à ta recherche." if recherche.strip()
                else "🎉 Tout est trié ! Les nouvelles offres arriveront au prochain scrap (tous les jours à 8 h, "
                     "ou avec « Lancer le scrap »)." if not a_trier else "Aucune offre dans cette section.")
    nouveau = scrap["passage_id"] if scrap else None
    grille(conn, config, requetes.trier_offres(liste, "Plus récentes" if tri == TRIS[0] else "Meilleure note"),
           cle=choix, nouveau=nouveau, vide=vide, avec_section=(choix in ("Toutes", PLUS_TARD)),
           page_fiche=page_fiche)



def grille(conn, config: dict, offres: list[dict], cle: str, nouveau: int | None, vide: str,
           avec_section: bool, page_fiche=None) -> None:
    """Vignettes (grille CSS : 3 ou 4 par rangée sur grand écran, 1 sur fenêtre étroite)."""
    if not offres:
        st.markdown(f'<div class="etape-vide">{vignettes._e(vide)}</div>', unsafe_allow_html=True)
        return
    cle = vignettes._slug(cle) or "toutes"
    nb = st.session_state.get(f"nb_{cle}", PAR_PAGE)
    chemin_base = conn.execute("PRAGMA database_list").fetchone()["file"]
    a_ouvrir = None
    with st.container(key=f"grille_{cle}"):
        for o in offres[:nb]:
            with st.container(border=True, key=f"carte_offre_{cle}_{o['id']}"):
                st.markdown(vignettes.html_vignette(o, avec_section=avec_section, avec_extrait=False,
                                                    nouveau=nouveau is not None and o["passage_id"] == nouveau),
                            unsafe_allow_html=True)
                if vignettes.boutons_decision(chemin_base, o, f"{cle}_{o['id']}"):
                    a_ouvrir = o["id"]
    if a_ouvrir is not None:   # fenêtre ouverte hors de la grille, pour ne pas y laisser une case vide
        vignettes.fenetre_fiche(config, a_ouvrir, cle, page_fiche)
    if len(offres) > nb:
        reste = len(offres) - nb
        if st.button(f"Afficher plus ({reste} autre{'s' if reste > 1 else ''})", key=f"plus_{cle}", width="stretch"):
            st.session_state[f"nb_{cle}"] = nb + PAR_PAGE
            st.rerun()


# =========================================================================== scrap

class JournalVersStreamlit(logging.Handler):
    """Affiche en direct, dans l'appli, les messages écrits pendant le scrap."""

    def __init__(self, zone):
        super().__init__(level=logging.INFO)
        self.zone, self.lignes = zone, []
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record):
        self.lignes.append(self.format(record))
        self.zone.code("\n".join(self.lignes[-25:]), language=None)


def lancer_scrap(conn, config: dict, sources: list[str] | None) -> None:
    with st.status("Scrap en cours… (quelques minutes)", expanded=True) as statut:
        zone = st.empty()
        journal = JournalVersStreamlit(zone)
        racine = logging.getLogger()
        racine.addHandler(journal)
        ancien_niveau = racine.level
        racine.setLevel(logging.INFO)
        try:
            bilan = pipeline.passage_complet(conn, config, auto=False, sources=sources)
        finally:
            racine.removeHandler(journal)
            racine.setLevel(ancien_niveau)
        zone.code("\n".join(pipeline.resume_texte(bilan)), language=None)
        statut.update(label="Scrap terminé", state="complete", expanded=False)
