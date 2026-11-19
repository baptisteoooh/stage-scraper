"""Page « Candidater » : tout le dossier d'une offre sur un seul écran.

À gauche, trois onglets : la lettre (modifiable, versions, export Word), les conseils CV et
l'analyse de l'offre (exigences, alertes). À droite, la conversation avec l'IA, gardée en base :
on peut fermer l'appli et reprendre plus tard.

Rien ne part tout seul vers l'IA payante : l'analyse et le premier jet se lancent avec le bouton
« Préparer avec l'IA », qui affiche son prix. Les modifications faites à la main dans la lettre sont
gardées automatiquement.
"""
import html
import re

import streamlit as st

from . import claude
from . import cv as module_cv
from . import dossier, requetes

COULEURS_ADEQUATION = {"forte": "green", "partielle": "orange", "faible": "red"}
ICONES_COUVERTURE = {"couverte": "✅", "partielle": "🟡", "absente": "❌"}
LIBELLES_ACTION = {"reformuler": "Reformuler", "deplacer": "Déplacer", "retirer": "Retirer", "ajouter": "Mettre en avant"}
DEMANDE_PREMIER_JET = "Rédige une première version de la lettre."
CENTIMES_ANALYSE = 4      # mesuré : ~3,6 c avec Sonnet (novembre 2026)
CENTIMES_PREMIER_JET = 4  # estimation : même modèle, réponse de taille voisine
NOMS_MODELES = {"claude-sonnet-5-5": "Claude Sonnet", "claude-haiku-5-5": "Claude Haiku"}


def libelle_appel(donnees: dict) -> str | None:
    """« Claude Sonnet · 0,61 centime » ou « Gemini (gratuit) » sous une réponse de l'IA."""
    modele = donnees.get("modele")
    if not modele:
        return None
    if not claude.est_claude(modele):
        return "Gemini (gratuit)"
    centimes = (donnees.get("cout") or 0) * 100
    return f"{NOMS_MODELES.get(modele, modele)} · {centimes:.2f} centime".replace(".", ",")


def prix(conn, config: dict, centimes: int, cle_modeles: str) -> str:
    """« ≈ 4 c » si Claude répondra, « gratuit » si Gemini prend le relais (plafond, pas de clé, config)."""
    modeles = config.get("dossier", {}).get(cle_modeles) or dossier.MODELES_PAR_DEFAUT
    if claude.blocage(conn, config) or not claude.est_claude(modeles[0]):
        return "gratuit, Gemini"
    return f"≈ {centimes} c"


def _e(texte) -> str:
    return html.escape(str(texte or ""))


def ouvrir_depuis(conn, offre_id: int, page) -> None:
    """Bouton « Préparer ma candidature » : crée le dossier (et la candidature) puis ouvre la page."""
    dossier.ouvrir(conn, offre_id)
    st.session_state["dossier_offre_id"] = offre_id
    if page is not None:
        st.switch_page(page)


# =========================================================================== page

def afficher(conn, config: dict) -> None:
    st.title("📝 Candidater")
    existants = dossier.tous(conn)
    choisi = st.session_state.get("dossier_offre_id")
    if not existants:
        st.info("Aucun dossier pour l'instant. Ouvre une offre (page Offres ou Assistant) et clique sur "
                "**📝 Préparer ma candidature** : l'IA analyse l'offre face à ton CV, propose des retouches de CV "
                "et rédige un premier jet de lettre, que tu ajustes ensuite en lui parlant.")
        return
    if not module_cv.texte_cv(config):
        st.warning("Dépose d'abord ton CV dans **Réglages › Mes documents** : l'IA s'appuie uniquement dessus.")
    blocage = claude.blocage(conn, config)
    if blocage:
        st.info(f"Claude en pause ({blocage}) : Gemini (gratuit) prend le relais.", icon="ℹ️")

    ids = [d["offre_id"] for d in existants]
    if choisi not in ids:
        choisi = ids[0]
    choisi = st.selectbox("Dossier", ids, index=ids.index(choisi), label_visibility="collapsed",
                          format_func=lambda i: next(f"{d['titre']} — {d['entreprise'] or '?'}"
                                                     for d in existants if d["offre_id"] == i))
    st.session_state["dossier_offre_id"] = choisi

    o = requetes.offre(conn, choisi)
    d = dossier.ouvrir(conn, choisi)
    entete(conn, config, o)
    preparer(conn, config, d)

    gauche, droite = st.columns([3, 2], gap="large")
    with gauche:
        lettre, conseils, analyse = st.tabs(["✉️ Lettre", "📄 Conseils CV", "🔎 Analyse de l'offre"])
        with lettre:
            onglet_lettre(conn, config, d, o)
        with conseils:
            onglet_conseils(d)
        with analyse:
            onglet_analyse(conn, config, d)
    with droite:
        conversation(conn, config, d)


def entete(conn, config: dict, o: dict) -> None:
    c = requetes.candidature_de(conn, o["id"])
    ligne = st.columns([5, 1.3, 1.3], vertical_alignment="center")
    ligne[0].markdown(f"**{_e(o['titre'])}** — {_e(o['entreprise'] or '?')}"
                      + (f" · {o['score']}/10" if o["score"] is not None else "")
                      + (f"  \n<span class='chat-raison'>Candidature : {_e(c['statut'])}</span>" if c else ""),
                      unsafe_allow_html=True)
    if o["lien"]:
        ligne[1].link_button("Voir l'offre ↗", o["lien"], width="stretch")
    if c and c["statut"] == "à postuler" and ligne[2].button("📨 J'ai postulé", width="stretch",
                                                            help="Passe la candidature à « postulé » (relance proposée)"):
        requetes.changer_statut(conn, c["id"], "postulé", int(config.get("candidatures", {}).get("relance_jours", 7)))
        st.toast("Candidature passée à « postulé ».")
        st.rerun()


def preparer(conn, config: dict, d: dict) -> None:
    """Bouton « Préparer avec l'IA » : analyse puis premier jet, seulement ce qui manque, sur demande."""
    manque_analyse, manque_lettre = not d.get("diagnostic"), not dossier.version_courante(conn, d)
    if not (manque_analyse or manque_lettre) or not module_cv.texte_cv(config):
        return
    centimes = CENTIMES_ANALYSE * manque_analyse + CENTIMES_PREMIER_JET * manque_lettre
    a_faire = " et ".join(t for t, m in (("analyse l'offre face à ton CV", manque_analyse),
                                         ("rédige un premier jet de lettre", manque_lettre)) if m)
    with st.container(border=True):
        ligne = st.columns([3, 1.4], vertical_alignment="center")
        ligne[0].markdown(f"L'IA {a_faire}. Ensuite, tu ajustes la lettre en lui parlant (≈ 0,1 c par retouche).")
        if not ligne[1].button(f"✨ Préparer avec l'IA ({prix(conn, config, centimes, 'modeles')})",
                               type="primary", width="stretch"):
            return
    try:
        if manque_analyse:
            with st.spinner("J'analyse l'offre face à ton CV (environ 20 secondes)…"):
                dossier.diagnostiquer(conn, config, d)
        if manque_lettre:
            with st.spinner("Je rédige un premier jet de lettre…"):
                dossier.discuter(conn, config, d, DEMANDE_PREMIER_JET)
    except dossier.DossierImpossible as e:
        st.error(f"L'IA n'a pas pu terminer : {e}")
        return
    st.rerun()


# =========================================================================== lettre

def _cle_zone(d: dict) -> str:
    return f"zone_lettre_{d['id']}_{d.get('version_courante') or 0}"


def garder_modifs(conn, d: dict) -> bool:
    """Garde ce que BAP a tapé dans la zone de texte (sans bouton). Vrai si quelque chose a changé."""
    texte = st.session_state.get(_cle_zone(d))
    return texte is not None and dossier.modifier_a_la_main(conn, d, texte)


def onglet_lettre(conn, config: dict, d: dict, o: dict) -> None:
    if garder_modifs(conn, d):   # ce que BAP a tapé depuis le dernier affichage
        st.toast("Modifications de la lettre enregistrées.")
    courante = dossier.version_courante(conn, d)
    if not courante:
        st.caption("Pas encore de lettre : clique sur « Préparer avec l'IA » en haut, ou demande-la dans la conversation.")
        return

    toutes = dossier.versions(conn, d["id"])
    auteur = "toi" if courante["modele"] is None else "l'IA"
    texte = st.text_area("Lettre (modifiable)", courante["texte"], height=480, key=_cle_zone(d),
                         label_visibility="collapsed")
    st.caption(f"Version {courante['numero']}/{len(toutes)} · écrite par {auteur} · {len(texte.split())} mots "
               "(250 à 350 conseillés) · tes modifications sont gardées toutes seules · "
               "[Prénom Nom] est remplacé par ton nom dans le fichier Word.")
    if dossier.lettre_figee(conn, d):
        st.caption("📨 Candidature envoyée : la lettre gardée dans ta candidature ne change plus, "
                   "même si tu modifies celle-ci.")
    if courante["alertes"]:
        st.warning("**Non retrouvé dans ton CV** (à vérifier ou à retirer) :\n\n"
                   + "\n".join(f"- {a}" for a in courante["alertes"]))

    b = st.columns(3)
    if b[0].button("↩️ Annuler", disabled=courante["numero"] <= 1, width="stretch",
                   help="Revenir à la version précédente"):
        dossier.choisir_version(conn, d, courante["numero"] - 1)
        st.rerun()
    nom = re.sub(r"\W+", "_", o["entreprise"] or "offre").strip("_")
    signee = module_cv.signer(texte, config)
    b[1].download_button("📥 Word", dossier.exporter_docx(signee), file_name=f"Lettre_{nom}.docx",
                         mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                         width="stretch")
    b[2].download_button("📥 Texte", signee, file_name=f"Lettre_{nom}.txt", mime="text/plain", width="stretch")

    if len(toutes) > 1:
        with st.expander("Historique des versions"):
            for v in reversed(toutes):
                ligne = st.columns([5, 1], vertical_alignment="center")
                ligne[0].markdown(f"**v{v['numero']}** · {_e(v['date'][5:16])} · "
                                  f"{'toi' if v['modele'] is None else 'IA'} — <span class='chat-raison'>"
                                  f"{_e((v['demande'] or '')[:90])}</span>", unsafe_allow_html=True)
                if v["numero"] != courante["numero"] and ligne[1].button("Reprendre", key=f"version_{d['id']}_{v['numero']}"):
                    dossier.choisir_version(conn, d, v["numero"])
                    st.rerun()


# =========================================================================== conseils CV

def onglet_conseils(d: dict) -> None:
    diag = d.get("diagnostic")
    if not diag:
        st.caption("Les conseils apparaissent une fois l'offre analysée (onglet Analyse de l'offre).")
        return
    st.caption("Retouches de ton CV pour cette offre, à partir de ce qui y figure déjà. "
               "Rien n'est modifié automatiquement : à toi de les reporter dans ton CV.")
    for c in diag.get("conseils_cv", []):
        with st.container(border=True):
            st.markdown(f"**{_e(LIBELLES_ACTION.get(c['action'], c['action']))}** · {_e(c['section'])}"
                        + ("  ⚠️ <span class='chat-raison'>à vérifier : je ne retrouve pas sa source dans ton CV"
                           "</span>" if c.get("a_verifier") else ""), unsafe_allow_html=True)
            if c.get("avant"):
                st.markdown(f"<span class='chat-raison'>Avant :</span> <s>{_e(c['avant'])}</s>", unsafe_allow_html=True)
            if c.get("apres"):
                st.markdown(f"<span class='chat-raison'>Après :</span> <b>{_e(c['apres'])}</b>", unsafe_allow_html=True)
            details = _e(c.get("justification"))
            if c.get("mots_cles"):
                details += " · mots de l'offre : " + ", ".join(f"« {_e(m)} »" for m in c["mots_cles"])
            st.markdown(f"<span class='chat-raison'>{details}</span>", unsafe_allow_html=True)
    if diag.get("conseils_ecartes"):
        st.caption(f"{diag['conseils_ecartes']} conseil(s) écarté(s) : ils citaient une ligne absente de ton CV.")
    if diag.get("a_apprendre"):
        st.markdown("**À travailler avant l'entretien** (absent de ton CV, à ne pas y ajouter sans l'avoir fait)")
        st.markdown("\n".join(f"- {_e(a)}" for a in diag["a_apprendre"]))


# =========================================================================== analyse

def onglet_analyse(conn, config: dict, d: dict) -> None:
    diag = d.get("diagnostic")
    if dossier.a_refaire(d, config):
        st.info("Ton CV a changé depuis cette analyse : refais-la pour en tenir compte.")
    if diag:
        couleur = COULEURS_ADEQUATION.get(diag.get("adequation"), "gray")
        st.markdown(f":{couleur}-badge[Adéquation {_e(diag.get('adequation'))}] {_e(diag.get('synthese'))}",
                    unsafe_allow_html=True)
        cols = st.columns(2)
        cols[0].markdown("**Pour**\n" + "\n".join(f"- {_e(p)}" for p in diag.get("pour", [])))
        cols[1].markdown("**Contre**\n" + "\n".join(f"- {_e(p)}" for p in diag.get("contre", [])))
        for a in diag.get("alertes", []):
            st.warning(f"{a['alerte']}\n\n**Question à poser** : {a['question_recruteur']}")
        st.markdown("**Exigences de l'offre**")
        for e in diag.get("exigences", []):
            preuve = (f"ton CV : « {_e(e['preuve_cv'])} »" if e.get("preuve_cv")
                      else "absent de ton CV" + (" (preuve proposée par l'IA introuvable)" if e.get("preuve_retiree") else ""))
            st.markdown(f"{ICONES_COUVERTURE.get(e['couverture'], '•')} **{_e(e['exigence'])}**"
                        + ("" if e.get("obligatoire") else " <span class='chat-raison'>(souhaité)</span>")
                        + f"  \n<span class='chat-raison'>{preuve} · {_e(e.get('action'))}</span>",
                        unsafe_allow_html=True)
        st.caption(f"Analyse du {d['date_diagnostic'][:16]} ({d['modele_diagnostic']}).")
    else:
        st.caption("Offre pas encore analysée : clique sur « Préparer avec l'IA » en haut.")
        return
    with st.popover("🔄 Refaire l'analyse"):
        st.caption("Utile si ton CV ou l'offre a changé. L'analyse actuelle sera remplacée.")
        confirmer = st.button(f"Refaire ({prix(conn, config, CENTIMES_ANALYSE, 'modeles')})", type="primary")
    if confirmer:
        with st.spinner("J'analyse l'offre face à ton CV (environ 20 secondes)…"):
            try:
                dossier.diagnostiquer(conn, config, d)
            except dossier.DossierImpossible as e:
                st.error(f"Analyse impossible : {e}")
                return
        st.rerun()


# =========================================================================== conversation

def conversation(conn, config: dict, d: dict) -> None:
    nom = dossier.conversation_de(d)
    with st.container(height=560, border=True):
        historique = dossier.messages(conn, nom)
        if not historique:
            st.caption("La conversation apparaîtra ici. Tu peux demander une lettre, une retouche (« plus court », "
                       "« insiste sur mon projet Parkinson ») ou poser une question sur l'offre.")
        for m in historique:
            with st.chat_message("user" if m["role"] == "user" else "assistant"):
                st.markdown(m["texte"])
                details = [f"✉️ Lettre mise à jour (version {m['donnees']['version']})"] if m["donnees"].get(
                    "version") else []
                if m["role"] == "assistant" and libelle_appel(m["donnees"]):
                    details.append(libelle_appel(m["donnees"]))
                if details:
                    st.caption(" · ".join(details))
    demande = st.chat_input("Demande une retouche ou pose une question…", key=f"chat_dossier_{d['id']}")
    st.caption("Ex. « plus court », « insiste sur mon projet Parkinson », « que répondre sur la durée ? ». "
               "L'IA ne s'appuie que sur ton CV et l'offre.")
    if demande:
        if garder_modifs(conn, d):
            st.toast("Tes modifications de la lettre sont gardées (nouvelle version).")
        with st.spinner("…"):
            try:
                dossier.discuter(conn, config, d, demande)
            except dossier.DossierImpossible as e:
                st.error(f"Pas de réponse : {e}")
                return
        st.rerun()
