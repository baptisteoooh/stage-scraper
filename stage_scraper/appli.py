"""Appli locale, lancée par app.py (streamlit run app.py).

Pages (menu en haut) : offres en vignettes (+ bouton de scrap), chat sur les offres, candidatures, lettres,
réglages, journal.
L'export Excel est dans le menu « ⋯ » de la page Offres et en haut de la page Candidatures.
"""
import logging

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from stage_scraper import (chat_offres, collecte, db, expiration, lettre, notifications, pipeline, reglages, requetes,
                           style, suivi, vignettes)
from stage_scraper import config as parametres
from stage_scraper.config import chemin_projet, secret

# Ouverts à chaque affichage (Streamlit relance ce fichier à chaque clic).
CONFIG: dict = {}
CONN = None

ONGLET_TOUTES = "Toutes sections"
ONGLET_ATTENTE = "En attente de note IA"
FILTRE_FAVORIS = "★ Favoris"


# =========================================================================== pages

def page_tableau_de_bord():
    entete = st.columns([4, 1.1, 0.5], vertical_alignment="bottom")
    entete[0].title("🩺 Offres de stage")
    lancer = entete[1].button("Lancer le scrap", type="primary", width="stretch")
    with entete[2].popover("⋯", help="Sources du scrap et export Excel", width="stretch"):
        actives = [n for n, r in CONFIG["sources"].items() if r.get("actif") and n in collecte.SOURCES]
        choix = st.multiselect(
            "Sources (vide = toutes les sources actives, sauf Google Jobs réservé au passage de 8 h)",
            list(collecte.SOURCES), placeholder="Toutes les sources actives", key="sources_choisies")
        st.caption("Actives : " + ", ".join(actives))
        st.divider()
        suivi.bouton_export(CONN)
    if lancer:
        lancer_scrap(choix or None)

    stats = requetes.statistiques(CONN)
    m = st.columns(4)
    m[0].metric("Offres gardées", stats["visibles"])
    m[1].metric("Pas encore vues", stats["non_vues"])
    m[2].metric("À postuler vite", stats["a_postuler_vite"])
    m[3].metric("Candidatures", stats["candidatures"])

    if stats["a_noter"] and not secret("GEMINI_API_KEY"):
        st.info(f"{stats['a_noter']} offre(s) attendent la note de l'IA : ajoute GEMINI_API_KEY dans le "
                "fichier .env, puis relance un scrap (ou `python run.py --noter`).")

    st.markdown("")
    # « Toutes » par défaut : une offre ouverte une fois reste visible (l'étiquette « Nouvelle » repère les autres).
    choix = st.columns([3, 2], vertical_alignment="bottom")
    filtre = choix[0].segmented_control("Afficher", ["Toutes", "Nouvelles", "Dernier passage", FILTRE_FAVORIS],
                                        default="Toutes", key="filtre_offres") or "Toutes"
    # Tri retenu pour toute la visite (la clé du bouton est oubliée quand on change de page).
    tri = choix[1].segmented_control("Trier par", requetes.TRIS, key="tri_offres_bouton",
                                     default=st.session_state.get("tri_offres", requetes.TRIS[0]))
    tri = st.session_state["tri_offres"] = tri or st.session_state.get("tri_offres", requetes.TRIS[0])

    if filtre == FILTRE_FAVORIS:
        favoris = requetes.trier_offres(
            requetes.offres_favorites(CONN, st.session_state.get("favoris_retires", set())), tri)
        st.caption("Les offres gardées avec ☆ restent ici, même déjà vues ou expirées.")
        vignettes.grille(CONN, CONFIG, favoris, cle="favoris", page_lettre=PAGES_OBJETS.get("lettre"),
                         avec_section=True)
        offres = []
    else:
        if filtre == "Dernier passage":
            offres = requetes.offres_visibles(CONN, "passage", requetes.dernier_passage(CONN))
        else:
            offres = requetes.offres_visibles(CONN)
            if filtre == "Nouvelles":  # les offres ouvertes pendant cette visite restent affichées
                ouvertes = st.session_state.get("ouvertes", set())
                offres = [o for o in offres if not o["vue"] or o["id"] in ouvertes]
        offres = requetes.trier_offres(offres, tri)

        # Premier onglet : toutes les offres notées, dans l'ordre choisi (note ou date).
        par_section = {ONGLET_TOUTES: [o for o in offres if o["score"] is not None]}
        par_section.update({s: [o for o in offres if o["score"] is not None and o["section"] == s]
                            for s in requetes.SECTIONS})
        par_section[ONGLET_ATTENTE] = [o for o in offres if o["score"] is None]
        onglets = st.tabs([f"{nom} ({len(liste)})" for nom, liste in par_section.items()])
        for onglet, (nom, liste) in zip(onglets, par_section.items()):
            with onglet:
                if nom == ONGLET_ATTENTE and liste:
                    st.caption("Offres qui ont passé le pré-filtre mais que l'IA n'a pas encore notées.")
                vignettes.grille(CONN, CONFIG, liste, cle=f"{filtre}_{nom}",
                                 page_lettre=PAGES_OBJETS.get("lettre"), avec_section=(nom == ONGLET_TOUTES))

    if filtre == "Nouvelles" and offres:
        if st.button("Tout marquer comme vu"):
            CONN.executemany("UPDATE offres SET vue = 1 WHERE id = ?", [(o["id"],) for o in offres])
            CONN.commit()
            st.session_state["ouvertes"] = set()
            st.rerun()

    with st.expander("🔍 Offres écartées par le tri (pour vérifier qu'il ne se trompe pas)"):
        exclues = requetes.offres_exclues(CONN)
        st.dataframe(pd.DataFrame([{"Titre": o["titre"], "Entreprise": o["entreprise"], "Lieu": o["lieu"],
                                    "Raison": o["exclusion_prefiltre"] or o["exclusion_ia"], "Lien": o["lien"]}
                                   for o in exclues]),
                     hide_index=True, width="stretch",
                     column_config={"Lien": st.column_config.LinkColumn(display_text="Ouvrir")})

    expirees = expiration.expirees(CONN)
    with st.expander(f"⌛ Offres expirées ({len(expirees)})"):
        st.caption("Retirées du site de l'entreprise, trop anciennes ou signalées à la main. "
                   "Elles restent en base mais n'apparaissent plus dans les offres ni dans les mails.")
        for o in expirees[:100]:
            c = st.columns([6, 1])
            c[0].markdown(f"**{o['titre']}** — {o['entreprise'] or '?'}"
                          + (f" · {o['score']}/10" if o["score"] is not None else "")
                          + f" · _{expiration.raison(o)}_")
            if o["expiration"] == "manuelle" and c[1].button("Remettre", key=f"remettre_{o['id']}"):
                expiration.annuler(CONN, o["id"])
                st.rerun()


class JournalVersStreamlit(logging.Handler):
    """Affiche en direct, dans l'appli, les messages écrits pendant le scrap."""

    def __init__(self, zone):
        super().__init__(level=logging.INFO)
        self.zone, self.lignes = zone, []
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record):
        self.lignes.append(self.format(record))
        self.zone.code("\n".join(self.lignes[-25:]), language=None)


def lancer_scrap(sources: list[str] | None) -> None:
    with st.status("Scrap en cours… (quelques minutes)", expanded=True) as statut:
        zone = st.empty()
        journal = JournalVersStreamlit(zone)
        racine = logging.getLogger()
        racine.addHandler(journal)
        ancien_niveau = racine.level
        racine.setLevel(logging.INFO)
        try:
            bilan = pipeline.passage_complet(CONN, CONFIG, auto=False, sources=sources)
        finally:
            racine.removeHandler(journal)
            racine.setLevel(ancien_niveau)
        zone.code("\n".join(pipeline.resume_texte(bilan)), language=None)
        statut.update(label="Scrap terminé", state="complete")
    st.session_state["filtre_offres"] = "Dernier passage"


def page_candidatures():
    suivi.afficher(CONN, CONFIG)


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
    messages = st.session_state.setdefault("chat_offres", [])
    if messages and st.button("🧹 Nouvelle conversation"):
        messages.clear()
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
        messages.append({"role": "user", "texte": question})
        messages.append({"role": "assistant", "texte": r["reponse"] or "…", "lues": r["lues"],
                         "ids": [o["id"] for o in r["offres"]], "raisons": {o["id"]: o["raison"] for o in r["offres"]}})
        st.session_state["chat_defiler"] = True
        st.rerun()
    if st.session_state.pop("chat_defiler", False):
        defiler_en_bas(len(messages))


def liste_offres_chat(message: dict, cle: str, ouverte: bool) -> None:
    """Offres proposées par l'assistant : une ligne chacune, dans un bloc repliable."""
    offres = [o for oid in message["ids"] if (o := requetes.offre(CONN, oid))]
    a_ouvrir = None
    with st.expander(f"📋 {len(offres)} offre{'s' if len(offres) > 1 else ''} proposée{'s' if len(offres) > 1 else ''}",
                     expanded=ouverte):
        for o in offres:
            ligne = st.columns([8, 1.3, 0.6], vertical_alignment="center")
            note = f"**{o['score']}/10**" if o["score"] is not None else "—"
            lieu = vignettes.lieu_court(o["lieu"])
            ligne[0].markdown(f"{note} · **{o['titre']}** — {o['entreprise'] or '?'}" + (f" · {lieu}" if lieu else "")
                              + f"  \n<span class='chat-raison'>{vignettes._e(message['raisons'].get(o['id'], ''))}</span>",
                              unsafe_allow_html=True)
            if ligne[1].button("Fiche", key=f"{cle}_fiche_{o['id']}", width="stretch"):
                a_ouvrir = o["id"]
            vignettes.bouton_favori(CONN, o, f"{cle}_favori_{o['id']}", ligne[2], compact=True)
    if a_ouvrir is not None:
        vignettes.fenetre_fiche(CONFIG, a_ouvrir, cle, PAGES_OBJETS.get("lettre"))


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


def page_lettre():
    st.title("✍️ Lettre de motivation")
    st.caption("Claude rédige un brouillon à partir de l'offre, de ton profil et de ton CV (profil/cv.pdf, s'il "
               "existe). Il n'invente rien : les passages [à compléter : …] sont pour toi. Relis toujours avant d'envoyer.")

    # Offres proposées : celles de tes candidatures d'abord, puis les autres par note.
    offres = {o["id"]: o for o in requetes.offres_visibles(CONN)}
    suivies = [c["offre_id"] for c in requetes.candidatures(CONN) if c["offre_id"]]
    ordre = list(dict.fromkeys([i for i in suivies if requetes.offre(CONN, i)] + list(offres)))
    if not ordre:
        st.info("Aucune offre pour l'instant : lance d'abord un scrap.")
        return
    cache = {i: offres.get(i) or requetes.offre(CONN, i) for i in ordre}
    demandee = st.session_state.get("lettre_offre_id")
    choix = st.selectbox(
        "Offre", ordre, index=ordre.index(demandee) if demandee in ordre else 0,
        format_func=lambda i: (("📋 " if i in suivies else "")
                               + (f"{cache[i]['score']}/10 · " if cache[i]["score"] is not None else "")
                               + f"{cache[i]['titre']} — {cache[i]['entreprise'] or '?'}"))
    st.session_state["lettre_offre_id"] = choix
    o = cache[choix]
    if o["lien"]:
        st.link_button("Voir l'offre", o["lien"])

    candidature = requetes.candidature_de(CONN, choix)
    brouillons = st.session_state.setdefault("brouillons", {})
    versions = st.session_state.setdefault("versions_brouillons", {})
    if choix not in brouillons and candidature and candidature.get("lettre"):
        brouillons[choix] = candidature["lettre"]

    consignes = st.text_input("Consignes (facultatif)", placeholder="ex. insister sur mon projet de deep learning, "
                                                                    "ton plus direct, en anglais…")
    sans_cle = not secret("ANTHROPIC_API_KEY")
    if sans_cle:
        st.info("Ajoute ANTHROPIC_API_KEY dans le fichier .env pour rédiger des lettres.")
    if st.button("Rédiger le brouillon" if choix not in brouillons else "Rédiger un nouveau brouillon",
                 type="primary", disabled=sans_cle):
        with st.spinner("Rédaction en cours…"):
            try:
                resultat = lettre.rediger(CONN, CONFIG, o, consignes)
                brouillons[choix] = resultat["texte"]
                versions[choix] = versions.get(choix, 0) + 1  # nouvelle zone de texte avec le nouveau brouillon
                st.toast(f"Brouillon rédigé (coût : {resultat['cout_usd']:.4f} $).")
            except lettre.LettreImpossible as e:
                st.error(f"Lettre non rédigée : {e}")

    if choix in brouillons:
        texte = st.text_area("Brouillon (modifiable)", brouillons[choix], height=420,
                             key=f"zone_lettre_{choix}_{versions.get(choix, 0)}")
        brouillons[choix] = texte
        c = st.columns(2)
        nom_fichier = f"lettre_{(o['entreprise'] or 'offre').replace(' ', '_')}.txt"
        c[0].download_button("📥 Télécharger (.txt)", texte, file_name=nom_fichier, mime="text/plain")
        if c[1].button("💾 Garder dans la candidature"):
            requetes.enregistrer_lettre(CONN, choix, texte)
            st.toast("Lettre gardée dans la candidature (créée si besoin).")


def page_journal():
    st.title("📜 Journal des passages")
    couts = requetes.couts_ia(CONN)
    budget = CONFIG["scoring"]["budget_mensuel_usd"]
    m = st.columns(3)
    m[0].metric("Coût IA ce mois-ci", f"{couts['mois']:.3f} $", f"budget {budget:.2f} $", delta_color="off")
    m[1].metric("Coût IA cumulé", f"{couts['total']:.3f} $")
    m[2].metric("Offres en base", requetes.statistiques(CONN)["total"])

    runs = requetes.journal(CONN)
    if not runs:
        st.caption("Aucun passage pour l'instant.")
        return
    tableau = pd.DataFrame(runs)[["passage_id", "date_debut", "declenchement", "source", "nb_offres",
                                  "nb_nouvelles", "nb_requetes", "tokens_entree", "tokens_sortie", "cout_usd",
                                  "erreurs"]]
    st.dataframe(tableau, hide_index=True, width="stretch", column_config={
        "passage_id": "Passage", "date_debut": "Date", "declenchement": "Lancement", "source": "Source",
        "nb_offres": "Offres", "nb_nouvelles": "Nouvelles", "nb_requetes": "Requêtes",
        "tokens_entree": "Tokens entrée", "tokens_sortie": "Tokens sortie",
        "cout_usd": st.column_config.NumberColumn("Coût ($)", format="%.4f"),
        "erreurs": st.column_config.TextColumn("Erreurs", width="large"),
    })


# =========================================================================== lancement

PAGES = {
    "tableau_de_bord": dict(titre="Offres", icone="🩺"),
    "chat": dict(titre="Chercher", icone="💬"),
    "candidatures": dict(titre="Candidatures", icone="📋"),
    "lettre": dict(titre="Lettres", icone="✍️"),
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
