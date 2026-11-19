"""Appli locale, lancée par app.py (streamlit run app.py).

Pages (menu en haut) : À trier (nouvelles offres + bouton de scrap), assistant (chat sur les offres),
candidater (dossier d'une offre : analyse, conseils CV, lettre), candidatures, réglages, journal.
L'export Excel est en haut de la page Candidatures.
"""

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from stage_scraper import (chat_offres, claude, db, dossier, notifications, page_a_trier, page_dossier, pipeline,
                           reglages, requetes, style, suivi, vignettes)
from stage_scraper import cv as module_cv
from stage_scraper import config as parametres
from stage_scraper.config import chemin_projet

# Ouverts à chaque affichage (Streamlit relance ce fichier à chaque clic).
CONFIG: dict = {}
CONN = None

# =========================================================================== pages

def page_tableau_de_bord():
    page_a_trier.afficher(CONN, CONFIG, PAGES_OBJETS.get("candidater"))


def page_candidatures():
    suivi.afficher(CONN, CONFIG, PAGES_OBJETS.get("candidater"))


def page_candidater():
    page_dossier.afficher(CONN, CONFIG)


def page_reglages():
    st.title("⚙️ Réglages")
    st.caption("Ces réglages sont enregistrés dans config.yaml (une copie de l'ancienne version est gardée "
               "dans config.yaml.bak).")
    donnees = reglages.lire()

    with st.form("reglages"):
        c = st.columns(2)
        anciennete = c[0].number_input("Ancienneté max d'une offre (jours)", 1, 365,
                                       int(donnees["general"]["anciennete_max_jours"]))
        seuil = c[1].number_input("Note qui déclenche une alerte immédiate (sur 10)", 0, 10,
                                  int(donnees["notifications"]["alerte_seuil_score"]))
        envoi_actif = st.toggle("Envoyer vraiment les mails (sinon : aperçus seulement, voir plus bas)",
                                bool(donnees["notifications"].get("envoi_actif")))

        st.subheader("Mots-clés par domaine")
        st.caption("Séparés par des virgules. Domaines classés par priorité (1 = le plus intéressant).")
        mots_cles = {}
        for d in donnees["domaines"]:
            mots_cles[d["nom"]] = st.text_area(f"{d['priorite']}. {d['nom']}", ", ".join(d["mots_cles"]),
                                               height=68)

        st.subheader("Exclusions (un mot ou une expression par ligne)")
        e = st.columns(3)
        contrats = e[0].text_area("Types de contrat exclus", "\n".join(donnees["exclusions"]["contrats"]), height=250)
        postes = e[1].text_area("Postes exclus (dans le titre)", "\n".join(donnees["exclusions"]["postes"]),
                                height=250)
        niveaux = e[2].text_area("Niveaux trop élevés (dans le titre)", "\n".join(donnees["exclusions"]["niveaux"]),
                                 height=250)

        st.subheader("Entreprises suivies")
        st.caption("Groupe : priorite_absolue, grand_groupe, scale_up ou ecosysteme. Outil carrières : ashby "
                   "(avec l'identifiant de la page) ou workday (avec l'adresse complète). Laisser vide si inconnu.")
        entreprises = st.data_editor(
            pd.DataFrame(reglages.entreprises_en_lignes(donnees)), num_rows="dynamic", hide_index=True,
            width="stretch", key="editeur_entreprises",
            column_config={
                "nom": st.column_config.TextColumn("Nom", required=True),
                "groupe": st.column_config.SelectboxColumn(
                    "Groupe", options=["priorite_absolue", "grand_groupe", "scale_up", "ecosysteme"],
                    default="scale_up"),
                "alias": st.column_config.TextColumn("Autres noms (virgules)"),
                "outil": st.column_config.SelectboxColumn("Outil carrières", options=["", "ashby", "workday"]),
                "adresse_ou_id": st.column_config.TextColumn("Adresse ou identifiant", width="large"),
            })
        enregistrer = st.form_submit_button("Enregistrer", type="primary")

    if enregistrer:
        changements = reglages.appliquer(donnees, {
            "anciennete_max_jours": anciennete, "alerte_seuil_score": seuil, "envoi_actif": envoi_actif,
            "contrats": reglages.texte_en_liste(contrats), "postes": reglages.texte_en_liste(postes),
            "niveaux": reglages.texte_en_liste(niveaux),
            "mots_cles": {nom: reglages.texte_en_liste(texte, ",") for nom, texte in mots_cles.items()},
            "entreprises_suivies": [{k: ("" if pd.isna(v) else v) for k, v in ligne.items()}
                                    for ligne in entreprises.to_dict("records")],
        })
        if changements:
            reglages.ecrire(donnees)
            st.success("Enregistré : " + ", ".join(changements) + ". Pense à refaire le tri ci-dessous "
                       "pour l'appliquer aux offres déjà collectées.")
        else:
            st.info("Aucun changement.")

    section_documents()
    section_mails()

    st.subheader("Refaire le tri")
    st.caption("Applique les réglages actuels (pré-filtre et doublons) à toutes les offres déjà collectées. "
               "Les notes de l'IA déjà obtenues sont gardées.")
    if st.button("Refaire le tri de toutes les offres"):
        bilan = pipeline.retrier(CONN, parametres.charger_config())
        st.success(pipeline.resume_tri(bilan).strip())

    st.subheader("Offres marquées « pas intéressé »")
    pas_interesse = requetes.offres_pas_interesse(CONN)
    if not pas_interesse:
        st.caption("Aucune pour l'instant.")
    for p in pas_interesse:
        c = st.columns([6, 1])
        c[0].markdown(f"**{p['titre']}** — {p['entreprise'] or '?'}" + (f" · _{p['raison']}_" if p["raison"] else ""))
        if c[1].button("Rétablir", key=f"retablir_{p['id']}"):
            requetes.annuler_pas_interesse(CONN, p["id"])
            st.rerun()


def section_documents():
    st.subheader("Mes documents")
    st.caption("Ton CV et une lettre que tu as écrite (modèle de style). Ils restent sur ton ordinateur, dans "
               "profil/ (ignoré par Git). Les IA ne reçoivent que leur texte, sans tes coordonnées ni ton nom.")
    c = st.columns(2)
    cv_pdf = c[0].file_uploader("CV (PDF)", type="pdf", key="depot_cv")
    modele = c[1].file_uploader("Lettre modèle (.txt ou .docx)", type=["txt", "docx"], key="depot_modele")
    if cv_pdf is not None and _deposer(module_cv.chemin_cv(CONFIG), cv_pdf.getvalue()):
        st.toast("CV enregistré. Les dossiers déjà analysés te proposeront de refaire l'analyse.")
    if modele is not None:
        contenu = modele.getvalue()
        if modele.name.lower().endswith(".docx"):
            import io
            from docx import Document
            contenu = "\n".join(p.text for p in Document(io.BytesIO(contenu)).paragraphs).encode("utf-8")
        if _deposer(module_cv.chemin_modele_lettre(CONFIG), contenu):
            st.toast("Lettre modèle enregistrée.")

    texte_cv, texte_modele = module_cv.texte_cv(CONFIG), module_cv.modele_lettre(CONFIG)
    c[0].markdown("✅ CV présent" if texte_cv else "❌ Pas encore de CV")
    c[1].markdown("✅ Lettre modèle présente" if texte_modele else "➖ Pas de lettre modèle (facultatif)")
    if texte_cv:
        if module_cv.NOM_MASQUE not in texte_cv:
            st.warning("Ton nom n'a pas été reconnu en tête du CV : vérifie dans l'aperçu qu'il n'apparaît pas.")
        with st.expander("Ce que l'IA reçoit : CV anonymisé"):
            st.text(texte_cv)
    if texte_modele:
        with st.expander("Ce que l'IA reçoit : lettre modèle anonymisée"):
            st.text(texte_modele)


def _deposer(chemin, contenu: bytes) -> bool:
    """Écrit le fichier déposé s'il est nouveau. Vrai s'il a changé."""
    if chemin.exists() and chemin.read_bytes() == contenu:
        return False
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)
    return True


def section_mails():
    st.subheader("Mails")
    config = parametres.charger_config()  # relu : l'interrupteur vient peut-être d'être changé
    _, mot_de_passe, destinataire = notifications.adresses()
    actif = config["notifications"].get("envoi_actif")
    st.markdown(f"Envoi : **{'activé' if actif else 'désactivé (aperçus seulement)'}** · destinataire : "
                f"**{destinataire or 'GMAIL_ADRESSE manquant dans .env'}**")
    alerte, recap = notifications.offres_alerte(CONN, config), notifications.offres_recap(CONN, config)
    st.caption(f"En attente d'envoi : {len(alerte)} offre(s) pour l'alerte immédiate, {len(recap)} pour le "
               "récap du matin (offres déjà notées par l'IA et jamais envoyées).")
    c = st.columns(3)
    apercu = None
    if c[0].button("Aperçu de l'alerte", disabled=not alerte):
        apercu = notifications.construire("alerte", alerte, config)
    if c[1].button("Aperçu du récap", disabled=not recap):
        apercu = notifications.construire("recap", recap, config)
    if c[2].button("Envoyer un mail de test", disabled=not (destinataire and mot_de_passe)):
        try:
            notifications.mail_de_test()
            st.success(f"Mail de test envoyé à {destinataire}.")
        except RuntimeError as e:
            st.error(f"Mail de test non envoyé : {e}")
    if apercu:
        sujet, _, page = apercu
        with st.container(border=True):
            st.markdown(f"**Sujet** : {sujet}")
            st.html(page)


def page_chat():
    st.title("💬 Assistant stage")
    st.caption("Demande-lui des offres (« un stage en computer vision sur l'imagerie médicale »), ou pose une "
               "question sur une offre (« quelles compétences pour le stage deep learning de GE ? », « compare "
               "ces deux offres »), ou sur tes candidatures. Il lit les annonces en entier avant de répondre.")
    vignettes.bandeau_decision(CONN, PAGES_OBJETS.get("candidater"))
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
        vignettes.fenetre_fiche(CONFIG, a_ouvrir, cle, PAGES_OBJETS.get("candidater"))


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


def page_journal():
    st.title("📜 Journal des passages")
    r, d = claude.reglages(CONFIG), claude.depenses(CONN, CONFIG)
    restant = max(r["credit_usd"] - d["total"], 0)
    dossiers_restants = int(restant / 0.08)   # ~8 centimes par dossier (analyse + lettre + 5 retouches)
    m = st.columns(3)
    m[0].metric("Crédit Claude restant (estimation)", f"{restant:.2f} $",
                f"≈ {dossiers_restants} dossiers · {d['total']:.3f} $ dépensés sur {r['credit_usd']:.2f} $",
                delta_color="off")
    m[1].metric("Claude ce mois-ci", f"{d['mois']:.3f} $", f"plafond {r['plafond_mensuel_usd']:.2f} $",
                delta_color="off")
    m[2].metric("Offres en base", requetes.statistiques(CONN)["total"])
    st.caption(f"Claude ne sert qu'à la page Candidater ; le reste passe par Gemini (gratuit). Au-delà de "
               f"{r['plafond_mensuel_usd']:.2f} $ par mois ou {r['plafond_total_usd']:.2f} $ au total, Gemini prend "
               "le relais. Le solde exact est dans la console Anthropic (Billing).")

    runs = requetes.journal(CONN)
    if not runs:
        st.caption("Aucun passage pour l'instant.")
        return
    tableau = pd.DataFrame(runs)[["passage_id", "date_debut", "declenchement", "source", "modele", "nb_offres",
                                  "nb_nouvelles", "nb_requetes", "tokens_entree", "tokens_sortie", "cout_usd",
                                  "erreurs"]]
    st.dataframe(tableau, hide_index=True, width="stretch", column_config={
        "passage_id": "Passage", "date_debut": "Date", "declenchement": "Lancement", "source": "Source",
        "modele": "Modèle IA",
        "nb_offres": "Offres", "nb_nouvelles": "Nouvelles", "nb_requetes": "Requêtes",
        "tokens_entree": "Tokens entrée", "tokens_sortie": "Tokens sortie",
        "cout_usd": st.column_config.NumberColumn("Coût ($)", format="%.4f"),
        "erreurs": st.column_config.TextColumn("Erreurs", width="large"),
    })


# =========================================================================== lancement

PAGES = {
    "tableau_de_bord": dict(titre="À trier", icone="📥"),
    "chat": dict(titre="Assistant", icone="💬"),
    "candidater": dict(titre="Candidater", icone="📝"),
    "candidatures": dict(titre="Candidatures", icone="📋"),
    "reglages": dict(titre="Réglages", icone="⚙️"),
    "journal": dict(titre="Journal", icone="📜"),
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
                         default=(nom == "tableau_de_bord"))
            for nom, p in PAGES.items()
        })
        # Navigation en haut de page : toute la largeur reste au contenu.
        navigation = st.navigation(list(PAGES_OBJETS.values()), position="top")
        navigation.run()
    finally:
        CONN.close()
