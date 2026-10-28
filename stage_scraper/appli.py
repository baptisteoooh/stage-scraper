"""Appli locale, lancée par app.py (streamlit run app.py).

Pages : tableau de bord (offres + bouton de scrap), candidatures, réglages, journal.
L'export Excel est dans la barre de gauche, sur toutes les pages.
"""
import logging
from datetime import date

import pandas as pd
import streamlit as st

from stage_scraper import collecte, db, export, notifications, pipeline, reglages, requetes, traitement
from stage_scraper import config as parametres
from stage_scraper.config import chemin_projet, secret

# Ouverts à chaque affichage (Streamlit relance ce fichier à chaque clic).
CONFIG: dict = {}
CONN = None

ONGLET_ATTENTE = "En attente de note IA"


# =========================================================================== outils

def lien_cliquable(url: str | None, texte: str = "Ouvrir l'offre") -> None:
    if url:
        st.link_button(texte, url)


def tableau_offres(offres: list[dict]) -> pd.DataFrame:
    lignes = []
    for o in offres:
        lignes.append({
            "Note": o["score"],
            "Nouveau": "🆕" if not o["vue"] else "",
            "Titre": o["titre"],
            "Entreprise": o["entreprise"],
            "Contrat": "CDD" if o["type_contrat"] == "cdd" else "Stage",
            "Lieu": o["lieu"],
            "Durée": o["duree"] or o["duree_ia"],
            "Début": o["date_debut"] or o["date_debut_ia"],
            "Gratification": o["gratification"],
            "Publiée le": (o["date_publication"] or "")[:10],
            "Lien": o["lien"],
        })
    return pd.DataFrame(lignes)


COLONNES_TABLEAU = {
    "Note": st.column_config.NumberColumn(format="%d / 10", width="small"),
    "Nouveau": st.column_config.TextColumn(width="small"),
    "Titre": st.column_config.TextColumn(width="large"),
    "Lien": st.column_config.LinkColumn(display_text="Ouvrir", width="small"),
}


def fiche_offre(o: dict, cle: str) -> None:
    """Détail d'une offre, avec les boutons Postuler et Pas intéressé."""
    if not o["vue"]:
        requetes.marquer_vue(CONN, o["id"])
        st.session_state.setdefault("ouvertes", set()).add(o["id"])

    with st.container(border=True):
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
            "Début": o["date_debut"] or o["date_debut_ia"],
            "Gratification": o["gratification"],
            "Télétravail": o["teletravail"],
            "Publiée le": (o["date_publication"] or "")[:10] or None,
            "Contact": o["contact"],
            "Trouvée via": " / ".join(x for x in (o["source"], o["site_origine"]) if x),
        }
        st.markdown("  \n".join(f"**{k}** : {v}" for k, v in infos.items() if v))

        liens = st.columns(4)
        with liens[0]:
            lien_cliquable(o["lien"])
        for i, autre in enumerate(requetes.doublons_de(CONN, o["id"])[:3], start=1):
            with liens[i]:
                lien_cliquable(autre["lien"], f"Aussi sur {autre['site_origine'] or autre['source']}")

        if o["description"]:
            with st.expander("Description complète"):
                st.text(o["description"])

        actions = st.columns(2)
        candidature = requetes.candidature_de(CONN, o["id"])
        with actions[0]:
            if candidature:
                st.success(f"Candidature suivie (statut : {candidature['statut']}).")
            elif st.button("✅ Postuler", key=f"postuler_{cle}_{o['id']}", type="primary"):
                requetes.creer_candidature(CONN, offre_id=o["id"])
                st.toast("Ajoutée aux candidatures, statut « à postuler ».")
                st.rerun()
        with actions[1]:
            if o["pas_interesse"]:
                if st.button("Annuler « pas intéressé »", key=f"annuler_{cle}_{o['id']}"):
                    requetes.annuler_pas_interesse(CONN, o["id"])
                    st.rerun()
            else:
                with st.popover("👎 Pas intéressé"):
                    raison = st.text_input("Raison (facultatif)", key=f"raison_{cle}_{o['id']}",
                                           placeholder="ex. trop orienté finance, trop loin…")
                    if st.button("Confirmer", key=f"pasint_{cle}_{o['id']}"):
                        requetes.marquer_pas_interesse(CONN, o["id"], raison)
                        st.toast("Offre masquée. L'IA s'en servira d'exemple pour les prochaines notes.")
                        st.rerun()


def liste_avec_fiche(offres: list[dict], cle: str) -> None:
    """Tableau cliquable : la fiche de l'offre choisie s'affiche dessous."""
    if not offres:
        st.caption("Aucune offre ici.")
        return
    evenement = st.dataframe(tableau_offres(offres), hide_index=True, width="stretch",
                             column_config=COLONNES_TABLEAU, on_select="rerun",
                             selection_mode="single-row", key=f"tableau_{cle}")
    lignes = evenement.selection.rows
    if lignes and lignes[0] < len(offres):
        fiche_offre(offres[lignes[0]], cle)
    else:
        st.caption("Clique sur une ligne pour voir la fiche de l'offre.")


# =========================================================================== pages

def page_tableau_de_bord():
    st.title("🩺 Offres de stage")
    stats = requetes.statistiques(CONN)
    m = st.columns(4)
    m[0].metric("Offres gardées", stats["visibles"])
    m[1].metric("Pas encore vues", stats["non_vues"])
    m[2].metric("À postuler vite", stats["a_postuler_vite"])
    m[3].metric("Candidatures", stats["candidatures"])

    if stats["a_noter"] and not secret("ANTHROPIC_API_KEY"):
        st.info(f"{stats['a_noter']} offre(s) attendent la note de l'IA : ajoute ANTHROPIC_API_KEY dans le "
                "fichier .env, puis relance un scrap (ou `python run.py --noter`).")

    with st.expander("🚀 Lancer le scrap", expanded=False):
        actives = [n for n, r in CONFIG["sources"].items() if r.get("actif") and n in collecte.SOURCES]
        choix = st.multiselect(
            "Sources (laisser vide = toutes les sources actives, sauf Google Jobs réservé au passage de 8 h)",
            list(collecte.SOURCES), placeholder="Toutes les sources actives")
        st.caption("Actives : " + ", ".join(actives))
        if st.button("Lancer le scrap", type="primary"):
            lancer_scrap(choix or None)

    st.divider()
    filtre = st.segmented_control("Afficher", ["Nouvelles", "Dernier passage", "Toutes"], default="Nouvelles",
                                  key="filtre_offres") or "Nouvelles"
    if filtre == "Dernier passage":
        offres = requetes.offres_visibles(CONN, "passage", requetes.dernier_passage(CONN))
    else:
        offres = requetes.offres_visibles(CONN)
        if filtre == "Nouvelles":  # les offres ouvertes pendant cette visite restent affichées
            ouvertes = st.session_state.get("ouvertes", set())
            offres = [o for o in offres if not o["vue"] or o["id"] in ouvertes]

    par_section = {s: [o for o in offres if o["score"] is not None and o["section"] == s] for s in requetes.SECTIONS}
    par_section[ONGLET_ATTENTE] = [o for o in offres if o["score"] is None]
    onglets = st.tabs([f"{nom} ({len(liste)})" for nom, liste in par_section.items()])
    for onglet, (nom, liste) in zip(onglets, par_section.items()):
        with onglet:
            if nom == ONGLET_ATTENTE and liste:
                st.caption("Offres qui ont passé le pré-filtre mais que l'IA n'a pas encore notées.")
            liste_avec_fiche(liste, cle=f"{filtre}_{nom}")

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
    st.title("📋 Candidatures")
    st.caption("Modifie directement le tableau : statut, dates, notes. Ajoute une ligne en bas pour une "
               "candidature faite hors de l'outil ; sélectionne une ligne puis la corbeille pour la supprimer. "
               "Clique ensuite sur **Enregistrer**.")
    lignes = requetes.candidatures(CONN)
    colonnes = ["id", "entreprise", "poste", "statut", "date_candidature", "date_relance", "lien", "notes"]
    tableau = pd.DataFrame(lignes, columns=colonnes + ["date_creation"])
    for c in ("date_candidature", "date_relance"):
        tableau[c] = pd.to_datetime(tableau[c], errors="coerce").dt.date
    tableau["date_creation"] = tableau["date_creation"].fillna("").astype(str).str[:10]

    modifie = st.data_editor(
        tableau, key="editeur_candidatures", num_rows="dynamic", hide_index=True, width="stretch",
        disabled=["id", "date_creation"],
        column_order=["entreprise", "poste", "statut", "date_candidature", "date_relance", "lien", "notes",
                      "date_creation"],
        column_config={
            "entreprise": st.column_config.TextColumn("Entreprise"),
            "poste": st.column_config.TextColumn("Poste", width="large"),
            "statut": st.column_config.SelectboxColumn("Statut", options=requetes.STATUTS, required=True,
                                                       default="à postuler"),
            "date_candidature": st.column_config.DateColumn("Envoyée le", format="DD/MM/YYYY"),
            "date_relance": st.column_config.DateColumn("Relance le", format="DD/MM/YYYY"),
            "lien": st.column_config.LinkColumn("Lien"),
            "notes": st.column_config.TextColumn("Notes", width="large"),
            "date_creation": st.column_config.TextColumn("Créée le"),
        })
    if st.button("Enregistrer", type="primary"):
        bilan = requetes.enregistrer_candidatures(CONN, modifie.to_dict("records"))
        st.toast(f"{bilan['ajoutees']} ajoutée(s), {bilan['modifiees']} modifiée(s), "
                 f"{bilan['supprimees']} supprimée(s).")
        st.session_state.pop("editeur_candidatures", None)
        st.rerun()

    a_relancer = [c for c in lignes if c["date_relance"] and c["date_relance"] <= date.today().isoformat()
                  and c["statut"] in ("postulé", "relancé")]
    if a_relancer:
        st.warning("À relancer aujourd'hui : " + ", ".join(f"{c['entreprise']} ({c['poste']})" for c in a_relancer))


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
        bilan = traitement.traiter(CONN, parametres.charger_config(), tout=True)
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

def barre_laterale():
    with st.sidebar:
        st.download_button("📥 Exporter en Excel", export.classeur_excel(CONN),
                           file_name=f"stage_scraper_{date.today().isoformat()}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           width="stretch")


PAGES = {
    "tableau_de_bord": dict(titre="Tableau de bord", icone="🩺"),
    "candidatures": dict(titre="Candidatures", icone="📋"),
    "reglages": dict(titre="Réglages", icone="⚙️"),
    "journal": dict(titre="Journal", icone="📜"),
}


def main(page: str | None = None):
    """Affiche l'appli. `page` = afficher directement une seule page (utilisé par les tests)."""
    global CONFIG, CONN
    st.set_page_config(page_title="Stage Scraper", page_icon="🩺", layout="wide")
    CONFIG = parametres.charger_config()
    CONN = db.connecter(chemin_projet(CONFIG["general"]["base_de_donnees"]))
    try:
        db.initialiser(CONN)
        if page:
            globals()[f"page_{page}"]()
            return
        navigation = st.navigation([
            st.Page(globals()[f"page_{nom}"], title=p["titre"], icon=p["icone"], url_path=nom,
                    default=(nom == "tableau_de_bord"))
            for nom, p in PAGES.items()
        ])
        barre_laterale()
        navigation.run()
    finally:
        CONN.close()
