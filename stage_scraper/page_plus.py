"""Pages du menu « Plus » : Réglages, Journal et Corbeille.

- Réglages : quatre onglets, Critères (ce qui est gardé ou écarté), Mes documents (CV, lettre modèle),
  Mails (alerte, récap, envoi) et Avancé (refaire le tri).
- Journal : une ligne par passage (scrap et notation), le crédit Claude, et le détail si besoin.
- Corbeille : les offres écartées par BAP, par le tri automatique, ou expirées, pour vérifier et rattraper.
"""
import io

import pandas as pd
import streamlit as st

from . import claude, expiration, notifications, pipeline, reglages, requetes, vignettes
from . import config as parametres
from . import cv as module_cv

TRIS_CORBEILLE = {"toi": "Écartées par toi", "tri": "Écartées par le tri", "expirees": "Expirées"}
PAR_PAGE = 50


# =========================================================================== réglages

def afficher_reglages(conn, config: dict) -> None:
    st.title("⚙️ Réglages")
    criteres, documents, mails, avance = st.tabs(["🎯 Critères", "📄 Mes documents", "✉️ Mails", "🛠️ Avancé"])
    with criteres:
        onglet_criteres()
    with documents:
        onglet_documents(config)
    with mails:
        onglet_mails(conn)
    with avance:
        onglet_avance(conn)


def _enregistrer(donnees, modifications: dict) -> None:
    changements = reglages.appliquer(donnees, modifications)
    if changements:
        reglages.ecrire(donnees)
        st.success("Enregistré : " + ", ".join(changements) + ".")
    else:
        st.info("Aucun changement.")


def onglet_criteres() -> None:
    st.caption("Ce que l'outil garde ou écarte. Enregistré dans config.yaml (l'ancienne version est gardée dans "
               "config.yaml.bak). Pour l'appliquer aux offres déjà collectées : onglet **Avancé › Refaire le tri**.")
    donnees = reglages.lire()
    with st.form("criteres"):
        anciennete = st.number_input("Ancienneté max d'une offre (jours)", 1, 365,
                                     int(donnees["general"]["anciennete_max_jours"]))
        st.markdown("**Exclusions** (un mot ou une expression par ligne)")
        e = st.columns(3)
        contrats = e[0].text_area("Types de contrat exclus", "\n".join(donnees["exclusions"]["contrats"]), height=250)
        postes = e[1].text_area("Postes exclus (dans le titre)", "\n".join(donnees["exclusions"]["postes"]),
                                height=250)
        niveaux = e[2].text_area("Niveaux trop élevés (dans le titre)", "\n".join(donnees["exclusions"]["niveaux"]),
                                 height=250)
        st.markdown("**Entreprises suivies**")
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
        _enregistrer(donnees, {
            "anciennete_max_jours": anciennete,
            "contrats": reglages.texte_en_liste(contrats), "postes": reglages.texte_en_liste(postes),
            "niveaux": reglages.texte_en_liste(niveaux),
            "entreprises_suivies": [{k: ("" if pd.isna(v) else v) for k, v in ligne.items()}
                                    for ligne in entreprises.to_dict("records")],
        })


def onglet_documents(config: dict) -> None:
    st.caption("Ton CV et une lettre que tu as écrite (modèle de style). Ils restent sur ton ordinateur, dans "
               "profil/ (ignoré par Git). Les IA ne reçoivent que leur texte, sans tes coordonnées ni ton nom.")
    c = st.columns(2)
    cv_pdf = c[0].file_uploader("CV (PDF)", type="pdf", key="depot_cv")
    modele = c[1].file_uploader("Lettre modèle (.txt ou .docx)", type=["txt", "docx"], key="depot_modele")
    if cv_pdf is not None and _deposer(module_cv.chemin_cv(config), cv_pdf.getvalue()):
        st.toast("CV enregistré. Les dossiers déjà analysés te proposeront de refaire l'analyse.")
    if modele is not None:
        contenu = modele.getvalue()
        if modele.name.lower().endswith(".docx"):
            from docx import Document
            contenu = "\n".join(p.text for p in Document(io.BytesIO(contenu)).paragraphs).encode("utf-8")
        if _deposer(module_cv.chemin_modele_lettre(config), contenu):
            st.toast("Lettre modèle enregistrée.")

    texte_cv, texte_modele = module_cv.texte_cv(config), module_cv.modele_lettre(config)
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


def onglet_mails(conn) -> None:
    donnees = reglages.lire()
    with st.form("mails"):
        seuil = st.number_input("Note qui déclenche une alerte immédiate (sur 10)", 0, 10,
                                int(donnees["notifications"]["alerte_seuil_score"]))
        envoi_actif = st.toggle("Envoyer vraiment les mails (sinon : aperçus seulement, ci-dessous)",
                                bool(donnees["notifications"].get("envoi_actif")))
        enregistrer = st.form_submit_button("Enregistrer", type="primary")
    if enregistrer:
        _enregistrer(donnees, {"alerte_seuil_score": seuil, "envoi_actif": envoi_actif})

    config = parametres.charger_config()  # relu : l'interrupteur vient peut-être d'être changé
    _, mot_de_passe, destinataire = notifications.adresses()
    actif = config["notifications"].get("envoi_actif")
    st.markdown(f"Envoi : **{'activé' if actif else 'désactivé (aperçus seulement)'}** · destinataire : "
                f"**{destinataire or 'GMAIL_ADRESSE manquant dans .env'}**")
    alerte, recap = notifications.offres_alerte(conn, config), notifications.offres_recap(conn, config)
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


def onglet_avance(conn) -> None:
    st.markdown("**Refaire le tri**")
    st.caption("Applique les critères actuels (pré-filtre et doublons) à toutes les offres déjà collectées. "
               "Les notes de l'IA déjà obtenues sont gardées.")
    if st.button("Refaire le tri de toutes les offres"):
        bilan = pipeline.retrier(conn, parametres.charger_config())
        st.success(pipeline.resume_tri(bilan).strip())
    st.markdown("**Autres paramètres**")
    st.caption("Les domaines (et leur ordre de priorité), les secteurs, les sources et les modèles d'IA se règlent "
               "dans le fichier config.yaml, à la racine du projet.")


# =========================================================================== journal

def afficher_journal(conn, config: dict) -> None:
    st.title("📜 Journal")
    r, d = claude.reglages(config), claude.depenses(conn, config)
    restant = max(r["credit_usd"] - d["total"], 0)
    dossiers_restants = int(restant / 0.08)   # ~8 centimes par dossier (analyse + lettre + 5 retouches)
    m = st.columns(3)
    m[0].metric("Crédit Claude restant (estimation)", f"{restant:.2f} $",
                f"≈ {dossiers_restants} dossiers · {d['total']:.3f} $ dépensés sur {r['credit_usd']:.2f} $",
                delta_color="off")
    m[1].metric("Claude ce mois-ci", f"{d['mois']:.3f} $", f"plafond {r['plafond_mensuel_usd']:.2f} $",
                delta_color="off")
    m[2].metric("Offres en base", requetes.statistiques(conn)["total"])
    st.caption(f"Claude ne sert qu'aux fiches de Ma sélection (analyse, lettre) ; le reste passe par Gemini "
               f"(gratuit). Au-delà de {r['plafond_mensuel_usd']:.2f} $ par mois ou {r['plafond_total_usd']:.2f} $ "
               "au total, Gemini prend le relais. Le solde exact est dans la console Anthropic (Billing).")

    st.subheader("Passages")
    passages = requetes.passages(conn)
    if not passages:
        st.caption("Aucun passage pour l'instant.")
    else:
        st.dataframe(pd.DataFrame([{
            "Date": p["date"][:16], "Lancement": "auto" if p["auto"] else "manuel", "Sources": p["sources"],
            "Trouvées": p["trouvees"], "Nouvelles": p["nouvelles"], "Gardées": p["gardees"], "Notées 8+": p["top"],
            "Notées par l'IA": p["notees"], "Coût ($)": p["cout_usd"],
            "Erreurs": " · ".join(f"{s} : {e}" for s, e in p["erreurs"].items()),
        } for p in passages]), hide_index=True, width="stretch", column_config={
            "Coût ($)": st.column_config.NumberColumn(format="%.4f"),
            "Erreurs": st.column_config.TextColumn(width="large"),
        })
        st.caption("Trouvées : offres reçues des sources · Nouvelles : jamais vues avant · Gardées : nouvelles qui "
                   "passent le tri (ni doublon, ni exclue, ni expirée).")

    appels = requetes.appels_ia(conn)
    with st.expander(f"Appels d'IA depuis l'appli ({len(appels)} : fiches et Assistant)"):
        st.dataframe(pd.DataFrame([{
            "Date": a["date_debut"][:16], "Où": "Assistant" if a["source"] == "chat" else "Fiche",
            "Modèle": a["modele"], "Coût ($)": a["cout_usd"], "Erreur": a["erreurs"]} for a in appels]),
            hide_index=True, width="stretch",
            column_config={"Coût ($)": st.column_config.NumberColumn(format="%.4f")})
    with st.expander("Détail brut, source par source"):
        runs = requetes.journal(conn)
        if runs:
            st.dataframe(pd.DataFrame(runs)[["passage_id", "date_debut", "declenchement", "source", "modele",
                                             "nb_offres", "nb_nouvelles", "nb_requetes", "tokens_entree",
                                             "tokens_sortie", "cout_usd", "erreurs"]],
                         hide_index=True, width="stretch")


# =========================================================================== corbeille

def afficher_corbeille(conn, config: dict) -> None:
    st.title("🗑️ Corbeille")
    st.caption("Les offres mises de côté. Rien n'est supprimé : tu peux vérifier que le tri ne se trompe pas, "
               "et remettre une offre dans À trier.")
    listes = {"toi": requetes.offres_pas_interesse(conn), "tri": requetes.offres_exclues(conn),
              "expirees": expiration.expirees(conn)}
    choix = st.segmented_control("Corbeille", list(TRIS_CORBEILLE), default="toi", key="choix_corbeille",
                                 format_func=lambda c: f"{TRIS_CORBEILLE[c]}  {len(listes[c])}",
                                 label_visibility="collapsed") or "toi"
    offres = listes[choix]
    if not offres:
        st.caption("Rien ici.")
        return
    if choix == "tri":
        st.caption("Écartées automatiquement (type de contrat, poste non technique, durée, lieu…) ou par l'IA. "
                   "Pour changer ce qui est écarté : **Réglages › Critères**.")
        st.dataframe(pd.DataFrame([{"Titre": o["titre"], "Entreprise": o["entreprise"], "Lieu": o["lieu"],
                                    "Raison": o["exclusion_prefiltre"] or o["exclusion_ia"], "Lien": o["lien"]}
                                   for o in offres]),
                     hide_index=True, width="stretch",
                     column_config={"Lien": st.column_config.LinkColumn(display_text="Ouvrir")})
        return

    nb = st.session_state.get(f"nb_corbeille_{choix}", PAR_PAGE)
    a_ouvrir = None
    for o in offres[:nb]:
        ligne = st.columns([6, 1.3, 1], vertical_alignment="center")
        note = f" · {o['score']}/10" if o.get("score") is not None else ""
        if choix == "toi":
            detail = f"_{o['raison']}_" if o["raison"] else "sans raison"
            ligne[0].markdown(f"**{vignettes._e(o['titre'])}** — {vignettes._e(o['entreprise'] or '?')}{note} · {detail}")
            if ligne[1].button("↩️ Remettre à trier", key=f"retablir_{o['id']}", width="stretch"):
                requetes.annuler_pas_interesse(conn, o["id"])
                st.toast("Offre remise dans À trier.")
                st.rerun()
        else:
            ligne[0].markdown(f"**{vignettes._e(o['titre'])}** — {vignettes._e(o['entreprise'] or '?')}{note} · "
                              f"_{expiration.raison(o)}_")
            if o["expiration"] == "manuelle" and ligne[1].button("↩️ Remettre en ligne", key=f"remettre_{o['id']}",
                                                                  width="stretch"):
                expiration.annuler(conn, o["id"])
                st.rerun()
        if ligne[2].button("🔍 Détails", key=f"corbeille_details_{o['id']}", width="stretch"):
            a_ouvrir = o["id"]
    if a_ouvrir is not None:
        vignettes.fenetre_fiche(config, a_ouvrir, "corbeille")
    if len(offres) > nb and st.button(f"Afficher plus ({len(offres) - nb} autres)", key=f"plus_corbeille_{choix}"):
        st.session_state[f"nb_corbeille_{choix}"] = nb + PAR_PAGE
        st.rerun()
