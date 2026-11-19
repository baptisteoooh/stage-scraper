"""Appli locale, lancée par app.py (streamlit run app.py).

Menu en haut :
- À trier : les nouvelles offres, une décision en un clic (et le bouton de scrap) ;
- Ma sélection : les offres gardées, par étape, avec la fiche de chacune (lettre, conseils CV, notes) ;
  l'export Excel est en haut de cette page ;
- Assistant : conversation sur les offres et les candidatures ;
- Plus : Réglages, Journal, Corbeille.
"""

import streamlit as st
import streamlit.components.v1 as components

from stage_scraper import chat_offres, db, dossier, page_plus, requetes, style, vignettes
from stage_scraper import config as parametres
from stage_scraper import page_a_trier as module_a_trier
from stage_scraper import page_selection as page_selection_module
from stage_scraper.config import chemin_projet

# Ouverts à chaque affichage (Streamlit relance ce fichier à chaque clic).
CONFIG: dict = {}
CONN = None

# =========================================================================== pages

def page_a_trier():
    module_a_trier.afficher(CONN, CONFIG, PAGES_OBJETS.get("fiche"))


def page_selection():
    page_selection_module.afficher_liste(CONN, CONFIG, PAGES_OBJETS.get("fiche"))


def page_fiche():
    page_selection_module.afficher_fiche(CONN, CONFIG, PAGES_OBJETS.get("selection"))


def page_reglages():
    page_plus.afficher_reglages(CONN, CONFIG)


def page_journal():
    page_plus.afficher_journal(CONN, CONFIG)


def page_corbeille():
    page_plus.afficher_corbeille(CONN, CONFIG)


def page_chat():
    st.title("💬 Assistant stage")
    st.caption("Demande-lui des offres (« un stage en computer vision sur l'imagerie médicale »), ou pose une "
               "question sur une offre (« quelles compétences pour le stage deep learning de GE ? », « compare "
               "ces deux offres »), ou sur tes candidatures. Il lit les annonces en entier avant de répondre.")
    vignettes.bandeau_decision(CONN, PAGES_OBJETS.get("fiche"))
    messages = messages_assistant()
    if messages and st.button("🧹 Nouvelle conversation", help="Efface cette conversation (les offres restent)"):
        dossier.effacer_conversation(CONN, CONVERSATION_ASSISTANT)
        st.rerun()

    for i, m in enumerate(messages):
        with st.chat_message("user" if m["role"] == "user" else "assistant"):
            if m.get("lues"):
                st.caption("📖 Lu : " + " · ".join(m["lues"]))
            st.markdown(m["texte"])
            if m.get("ids"):
                liste_offres_chat(m, cle=f"chat_{i}", ouverte=(i == len(messages) - 1))

    question = st.chat_input("Écris ta demande…")
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            defiler_en_bas(len(messages))
            with st.spinner("Je réfléchis…"):
                try:
                    r = chat_offres.demander(CONN, CONFIG, question, messages)
                except chat_offres.ChatImpossible as e:
                    st.error(f"Pas de réponse : {e}")
                    return
        dossier.ajouter_message(CONN, CONVERSATION_ASSISTANT, "user", question)
        dossier.ajouter_message(CONN, CONVERSATION_ASSISTANT, "assistant", r["reponse"] or "…", {
            "lues": r["lues"], "ids": [o["id"] for o in r["offres"]],
            "raisons": {str(o["id"]): o["raison"] for o in r["offres"]}})
        st.session_state["chat_defiler"] = True
        st.rerun()
    if st.session_state.pop("chat_defiler", False):
        defiler_en_bas(len(messages))


CONVERSATION_ASSISTANT = "assistant"


def messages_assistant() -> list[dict]:
    """La conversation de l'assistant, gardée en base (on la retrouve en relançant l'appli)."""
    return [{"role": m["role"], "texte": m["texte"], "lues": m["donnees"].get("lues"),
             "ids": m["donnees"].get("ids"),
             "raisons": {int(k): v for k, v in (m["donnees"].get("raisons") or {}).items()}}
            for m in dossier.messages(CONN, CONVERSATION_ASSISTANT)]


def liste_offres_chat(message: dict, cle: str, ouverte: bool) -> None:
    """Offres proposées par l'assistant : une ligne chacune, dans un bloc repliable."""
    offres = [o for oid in message["ids"] if (o := requetes.offre(CONN, oid))]
    a_ouvrir = None
    with st.expander(f"📋 {len(offres)} offre{'s' if len(offres) > 1 else ''} proposée{'s' if len(offres) > 1 else ''}",
                     expanded=ouverte):
        for o in offres:
            ligne = st.columns([8, 1.3], vertical_alignment="center")
            note = f"**{o['score']}/10**" if o["score"] is not None else "—"
            lieu = vignettes.lieu_court(o["lieu"])
            ligne[0].markdown(f"{note} · **{o['titre']}** — {o['entreprise'] or '?'}" + (f" · {lieu}" if lieu else "")
                              + f"  \n<span class='chat-raison'>{vignettes._e(message['raisons'].get(o['id'], ''))}</span>",
                              unsafe_allow_html=True)
            if ligne[1].button("🔍 Détails", key=f"{cle}_fiche_{o['id']}", width="stretch"):
                a_ouvrir = o["id"]
    if a_ouvrir is not None:
        vignettes.fenetre_fiche(CONFIG, a_ouvrir, cle, PAGES_OBJETS.get("fiche"))


def defiler_en_bas(repere: int) -> None:
    """Fait défiler la page jusqu'en bas (dernier message du chat)."""
    components.html(f"""<script>/* {repere} */
      const d = window.parent.document;
      const bas = () => {{
        d.querySelectorAll('[data-testid="stMain"], [data-testid="stAppViewContainer"], section.main')
          .forEach(e => e.scrollTo({{top: e.scrollHeight, behavior: "smooth"}}));
        window.parent.scrollTo({{top: d.body.scrollHeight, behavior: "smooth"}});
      }};
      setTimeout(bas, 50); setTimeout(bas, 400); setTimeout(bas, 1200);
    </script>""", height=0)


# =========================================================================== lancement

# Menu : les trois pages principales, puis « Plus ». La fiche d'une offre n'est pas dans le menu :
# on l'ouvre depuis Ma sélection (ou depuis une offre, avec « Je candidate »).
PAGES = {
    "a_trier": dict(titre="À trier", icone="📥", menu=""),
    "selection": dict(titre="Ma sélection", icone="⭐", menu=""),
    "chat": dict(titre="Assistant", icone="💬", menu=""),
    "fiche": dict(titre="Fiche", icone="📝", menu="", cachee=True),
    "reglages": dict(titre="Réglages", icone="⚙️", menu="Plus"),
    "journal": dict(titre="Journal", icone="📜", menu="Plus"),
    "corbeille": dict(titre="Corbeille", icone="🗑️", menu="Plus"),
}
PAGES_OBJETS: dict = {}  # rempli au lancement, pour passer d'une page à l'autre


def main(page: str | None = None):
    """Affiche l'appli. `page` = afficher directement une seule page (utilisé par les tests)."""
    global CONFIG, CONN
    st.set_page_config(page_title="Stage Scraper", page_icon="🩺", layout="wide")
    style.appliquer()
    CONFIG = parametres.charger_config()
    CONN = db.connecter(chemin_projet(CONFIG["general"]["base_de_donnees"]))
    try:
        db.initialiser(CONN)
        if page:
            globals()[f"page_{page}"]()
            return
        PAGES_OBJETS.clear()
        PAGES_OBJETS.update({
            nom: st.Page(globals()[f"page_{nom}"], title=p["titre"], icon=p["icone"], url_path=nom,
                         default=(nom == "a_trier"), visibility="hidden" if p.get("cachee") else "visible")
            for nom, p in PAGES.items()
        })
        menu: dict[str, list] = {}
        for nom, p in PAGES.items():
            menu.setdefault(p["menu"], []).append(PAGES_OBJETS[nom])
        # Navigation en haut de page (« Plus » devient un menu déroulant) : toute la largeur reste au contenu.
        navigation = st.navigation(menu, position="top")
        navigation.run()
    finally:
        CONN.close()
