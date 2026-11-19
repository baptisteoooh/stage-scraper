"""Pages « Ma sélection » : les offres gardées, rangées par étape, et la fiche de chacune.

La liste : un onglet par étape (En préparation, Envoyées, Entretien, Terminées) ; dans chaque étape,
les offres qui demandent une action passent en premier, avec un bouton pour la faire.
La fiche : où en est l'offre (étape, dates), puis l'offre, la lettre, les conseils CV, l'analyse
et les notes, avec la conversation avec l'IA à côté.

Mise en forme volontairement simple : le style des pages viendra plus tard.
"""
import zlib
from contextlib import closing
from datetime import date, time

import streamlit as st

from . import claude, db, dossier, export, page_dossier, requetes, selection, vignettes
from . import cv as module_cv
from .config import chemin_projet

LIBELLES_ACTION = {"preparer": "✨ Préparer", "envoyer": "📨 Finir et envoyer", "relancer": "🔔 J'ai relancé",
                   "entretien": "💬 Préparer l'entretien"}
ETAPES_FICHE = {"preparation": "En préparation", "envoyee": "Envoyée", "entretien": "Entretien",
                "terminee": "Terminée"}
RESULTATS = {"refus": "Refus", "accepté": "Accepté"}
CLE_ETAPE = "etape_selection"


def relance_jours(config: dict) -> int:
    return int(config.get("candidatures", {}).get("relance_jours", 7))


def _empreinte(valeur) -> int:
    """Petit numéro qui change avec la valeur : sert dans les clés des champs gardés tout seuls,
    pour qu'ils repartent de la base après une modification (ou une annulation)."""
    return zlib.crc32(str(valeur).encode("utf-8"))


def _jour(texte: str | None) -> date | None:
    try:
        return date.fromisoformat(str(texte)[:10]) if texte else None
    except ValueError:
        return None


def _connexion(config: dict):
    """Connexion propre à une fenêtre (Streamlit la relance seule, dans un autre fil d'exécution)."""
    return closing(db.connecter(chemin_projet(config["general"]["base_de_donnees"])))


def bouton_export(conn) -> None:
    st.download_button("📥 Exporter en Excel", export.classeur_excel(conn),
                       file_name=f"stage_scraper_{date.today().isoformat()}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       width="stretch", help="Offres et candidatures, dans un fichier Excel")


# =========================================================================== annulation

def _retenir(message: str, avant: dict | None) -> None:
    if avant:
        st.session_state["derniere_action_selection"] = {"message": message, "avant": avant}


def bandeau_annulation(conn) -> None:
    action = st.session_state.get("derniere_action_selection")
    if not action:
        return
    ligne = st.columns([6, 1.1, 0.5], vertical_alignment="center")
    ligne[0].success(action["message"])
    if ligne[1].button("↩️ Annuler", width="stretch", key="annuler_selection"):
        selection.annuler(conn, action["avant"])
        st.session_state.pop("derniere_action_selection")
        st.rerun()
    if ligne[2].button("✕", key="fermer_selection", help="Fermer", type="tertiary"):
        st.session_state.pop("derniere_action_selection")
        st.rerun()


# =========================================================================== liste

def afficher_liste(conn, config: dict, page_fiche=None) -> None:
    entete = st.columns([4, 1.5, 1.3], vertical_alignment="bottom")
    entete[0].title("⭐ Ma sélection")
    if entete[1].button("＋ Offre trouvée ailleurs", width="stretch",
                        help="Une offre vue hors de l'outil : elle aura sa fiche comme les autres"):
        fenetre_nouvelle(config, page_fiche)
    with entete[2]:
        bouton_export(conn)
    bandeau_annulation(conn)

    rangees = selection.par_etape(conn)
    if not any(rangees.values()):
        st.info("Rien dans ta sélection pour l'instant. Dans **À trier**, clique **✅ Je candidate** sur une offre : "
                "elle arrive ici, à l'étape « En préparation ».")
        return

    def libelle(nom: str) -> str:
        liste = rangees[nom]
        a_faire = sum(1 for f in liste if f["action"])
        return f"{selection.ETAPES[nom][0]}  {len(liste)}" + (f" · {a_faire} à faire" if a_faire else "")

    # Étape retenue pour toute la visite (la clé du bouton est oubliée quand on change de page).
    choix = st.segmented_control("Étape", list(selection.ETAPES), format_func=libelle, label_visibility="collapsed",
                                 key=f"{CLE_ETAPE}_bouton", default=st.session_state.get(CLE_ETAPE, "preparation"))
    etape = st.session_state[CLE_ETAPE] = choix or st.session_state.get(CLE_ETAPE, "preparation")

    fiches = rangees[etape]
    if not fiches:
        st.caption("Rien à cette étape pour l'instant.")
        return
    colonnes = st.columns(3, gap="medium")
    for i, f in enumerate(fiches):
        with colonnes[i % 3]:
            carte(conn, config, f, page_fiche)


def carte(conn, config: dict, f: dict, page_fiche=None) -> None:
    with st.container(border=True, key=f"carte_selection_{f['id']}"):
        note = f" · **{f['score']}/10**" if f["score"] is not None else ""
        st.markdown(f"**{vignettes._e(f['entreprise'] or 'Entreprise ?')}**{note}  \n{vignettes._e(f['titre'])}")
        st.caption(selection.situation(f))
        if f["action"]:
            st.markdown(f":orange-badge[À faire : {selection.ACTIONS[f['action']].lower()}]")
        boutons = st.columns(2) if f["action"] else [st.container()]
        if f["action"] == "relancer":
            if boutons[0].button(LIBELLES_ACTION["relancer"], key=f"agir_{f['id']}", type="primary", width="stretch"):
                avant = selection.noter_relance(conn, f["id"], relance_jours(config))
                _retenir(f"{f['entreprise'] or 'Candidature'} : relance notée.", avant)
                st.rerun()
        elif f["action"] and boutons[0].button(LIBELLES_ACTION[f["action"]], key=f"agir_{f['id']}", type="primary",
                                               width="stretch"):
            page_dossier.ouvrir_fiche(conn, f["offre_id"], page_fiche)
            st.rerun()
        if boutons[-1].button("Ouvrir la fiche" if not f["action"] else "Ouvrir", key=f"ouvrir_{f['id']}",
                              width="stretch"):
            page_dossier.ouvrir_fiche(conn, f["offre_id"], page_fiche)
            st.rerun()


@st.dialog("Offre trouvée ailleurs")
def fenetre_nouvelle(config: dict, page_fiche=None) -> None:
    with _connexion(config) as conn:
        _nouvelle(conn, config, page_fiche)


def _nouvelle(conn, config: dict, page_fiche=None) -> None:
    entreprise = st.text_input("Entreprise")
    poste = st.text_input("Poste")
    c = st.columns(2)
    lien = c[0].text_input("Lien de l'annonce (facultatif)", placeholder="https://…")
    lieu = c[1].text_input("Lieu (facultatif)")
    annonce = st.text_area("Texte de l'annonce (facultatif)", height=150,
                           help="Colle-le pour que l'IA puisse analyser l'offre et écrire la lettre.")
    deja = st.toggle("Candidature déjà envoyée")
    envoyee = st.date_input("Envoyée le", value=date.today(), format="DD/MM/YYYY") if deja else None
    if st.button("Ajouter à Ma sélection", type="primary", width="stretch"):
        if not (entreprise.strip() or poste.strip()):
            st.error("Indique au moins l'entreprise ou le poste.")
            return
        identifiant = requetes.ajouter_a_la_main(
            conn, entreprise.strip() or None, poste.strip() or None, lien.strip() or None,
            "postulé" if deja else "à postuler", None, envoyee, relance_jours(config),
            description=annonce, lieu=lieu.strip() or None)
        page_dossier.ouvrir_fiche(conn, requetes.candidature(conn, identifiant)["offre_id"], page_fiche)
        st.rerun()


# =========================================================================== fiche

def offre_ouverte() -> int | None:
    """Offre dont la fiche est demandée (gardée en mémoire, ou dans l'adresse de la page)."""
    valeur = st.session_state.get(page_dossier.CLE_FICHE) or st.query_params.get("offre")
    try:
        return int(valeur) if valeur is not None else None
    except ValueError:
        return None


def afficher_fiche(conn, config: dict, page_liste=None) -> None:
    if st.button("← Ma sélection", type="tertiary", key="retour_selection") and page_liste is not None:
        st.switch_page(page_liste)
    offre_id = offre_ouverte()
    c = requetes.candidature_de(conn, offre_id) if offre_id is not None else None
    if c is None:
        st.info("Cette offre n'est pas (ou plus) dans ta sélection.")
        bandeau_annulation(conn)
        return
    st.session_state[page_dossier.CLE_FICHE] = offre_id
    st.query_params["offre"] = str(offre_id)   # la fiche reste ouverte si on recharge la page
    f = selection.fiche(conn, c["id"])
    o = requetes.offre(conn, offre_id)
    d = dossier.ouvrir(conn, offre_id)

    bandeau_annulation(conn)
    entete(conn, config, f)
    etape_et_dates(conn, config, f)

    if not module_cv.texte_cv(config):
        st.warning("Dépose d'abord ton CV dans **Plus › Réglages › Mes documents** : l'IA s'appuie uniquement dessus.")
    blocage = claude.blocage(conn, config)
    if blocage:
        st.info(f"Claude en pause ({blocage}) : Gemini (gratuit) prend le relais.", icon="ℹ️")
    if f["etape"] in ("preparation", "entretien"):
        page_dossier.preparer(conn, config, d, avec_lettre=(f["etape"] == "preparation"))

    gauche, droite = st.columns([3, 2], gap="large")
    with gauche:
        onglets = ["📄 L'offre", "✉️ Lettre", "🧾 Conseils CV", "🔎 Analyse", "🗒️ Notes"]
        offre, lettre, conseils, analyse, notes = st.tabs(
            onglets, default="✉️ Lettre" if f["etape"] == "preparation" and f["lettre_prete"] else None)
        with offre:
            onglet_offre(conn, f, o)
        with lettre:
            page_dossier.onglet_lettre(conn, config, d, o)
        with conseils:
            page_dossier.onglet_conseils(d)
        with analyse:
            page_dossier.onglet_analyse(conn, config, d)
        with notes:
            onglet_notes(conn, config, f)
    with droite:
        page_dossier.conversation(conn, config, d)


def entete(conn, config: dict, f: dict) -> None:
    st.title(f["titre"])
    infos = [f["entreprise"] or "Entreprise ?", f["lieu"], f"note {f['score']}/10" if f["score"] is not None else None,
             "offre trouvée ailleurs" if f["trouvee_ailleurs"] else None]
    st.caption(" · ".join(i for i in infos if i))
    ligne = st.columns([1.3, 1.3, 4], vertical_alignment="center")
    if f["etape"] == "preparation" and ligne[0].button(
            "📨 C'est envoyé", type="primary", width="stretch",
            help=f"Range l'offre dans « Envoyées » et prévoit une relance dans {relance_jours(config)} jours"):
        avant = selection.changer_etape(conn, f["id"], "envoyee", relance_jours(config))
        _retenir(f"{f['entreprise'] or 'Candidature'} : candidature envoyée, relance prévue.", avant)
        st.rerun()
    if f["relance_due"] and ligne[0].button("🔔 J'ai relancé", type="primary", width="stretch"):
        avant = selection.noter_relance(conn, f["id"], relance_jours(config))
        _retenir(f"{f['entreprise'] or 'Candidature'} : relance notée.", avant)
        st.rerun()
    if f["lien"]:
        ligne[1].link_button("Voir l'annonce ↗", f["lien"], width="stretch")


def etape_et_dates(conn, config: dict, f: dict) -> None:
    """Barre des étapes (cliquable), résultat, date d'entretien et situation en une phrase."""
    # Clés qui changent avec le statut : après un changement ou une annulation, la barre repart de la base.
    choix = st.segmented_control("Où en est cette offre ?", list(ETAPES_FICHE), default=f["etape"],
                                 format_func=ETAPES_FICHE.get, key=f"etape_fiche_{f['id']}_{f['statut']}")
    if choix and choix != f["etape"]:
        avant = selection.changer_etape(conn, f["id"], choix, relance_jours(config))
        _retenir(f"{f['entreprise'] or 'Candidature'} : étape « {ETAPES_FICHE[choix]} ».", avant)
        st.rerun()
    if f["etape"] == "terminee":
        resultat = st.segmented_control("Résultat", list(RESULTATS), default=f["statut"], format_func=RESULTATS.get,
                                        key=f"resultat_{f['id']}_{f['statut']}")
        if resultat and resultat != f["statut"]:
            avant = selection.changer_etape(conn, f["id"], "terminee", resultat=resultat)
            _retenir(f"{f['entreprise'] or 'Candidature'} : {RESULTATS[resultat].lower()}.", avant)
            st.rerun()
    if f["etape"] == "entretien":
        date_entretien(conn, f)
    st.caption(selection.situation(f))


def date_entretien(conn, f: dict) -> None:
    actuel = f["date_entretien"]
    heure = None
    if actuel and len(actuel) >= 16:
        try:
            heure = time.fromisoformat(actuel[11:16])
        except ValueError:
            pass
    c = st.columns([1, 1, 3])
    cle = f"{f['id']}_{_empreinte(actuel)}"
    jour = c[0].date_input("Date de l'entretien", value=_jour(actuel), format="DD/MM/YYYY", key=f"entretien_j_{cle}")
    moment = c[1].time_input("Heure", value=heure, step=900, key=f"entretien_h_{cle}")
    nouveau = (f"{jour.isoformat()} {moment:%H:%M}" if moment else jour.isoformat()) if jour else None
    if nouveau != actuel:
        requetes.modifier_candidature(conn, f["id"], date_entretien=nouveau)
        st.rerun()


def onglet_offre(conn, f: dict, o: dict) -> None:
    if not f["trouvee_ailleurs"]:
        vignettes.details_offre(conn, o)
        return
    st.caption("Offre trouvée hors de l'outil. Colle le texte de l'annonce : l'IA en a besoin pour l'analyse et "
               "la lettre. Il est gardé tout seul.")
    texte = st.text_area("Texte de l'annonce", o["description"] or "", height=320,
                         key=f"annonce_{o['id']}_{_empreinte(o['description'])}")
    if texte.strip() != (o["description"] or "").strip():
        requetes.completer_annonce(conn, o["id"], texte)
        st.toast("Texte de l'annonce gardé.")
        st.rerun()


def onglet_notes(conn, config: dict, f: dict) -> None:
    """Dates et notes, gardées toutes seules ; et « Retirer de ma sélection »."""
    c = st.columns(2)
    envoyee = c[0].date_input("Envoyée le", value=_jour(f["date_candidature"]), format="DD/MM/YYYY",
                              key=f"envoi_{f['id']}_{_empreinte(f['date_candidature'])}")
    relance = c[1].date_input("Relancer le", value=_jour(f["date_relance"]), format="DD/MM/YYYY",
                              key=f"relance_{f['id']}_{_empreinte(f['date_relance'])}",
                              help=f"Prévu {relance_jours(config)} jours après l'envoi ou la dernière relance.")
    notes = st.text_area("Notes", f["notes"] or "", height=160, placeholder="Contact, référence, impressions…",
                         key=f"notes_{f['id']}_{_empreinte(f['notes'])}")
    modifs = {}
    if envoyee != _jour(f["date_candidature"]):
        modifs["date_candidature"] = envoyee
    if relance != _jour(f["date_relance"]):
        modifs["date_relance"] = relance
    if notes.strip() != (f["notes"] or "").strip():
        modifs["notes"] = notes
    if modifs:
        requetes.modifier_candidature(conn, f["id"], **modifs)
        st.toast("Gardé.")
        st.rerun()
    st.caption("Tout ce qui est modifié ici est gardé tout seul.")

    if f.get("lettre") and f["etape"] != "preparation":
        with st.expander("✉️ Lettre envoyée (telle que le recruteur l'a lue)"):
            st.text(f["lettre"])

    st.divider()
    quoi = "supprimée" if f["trouvee_ailleurs"] else "remise dans À trier"
    if st.button("🗑️ Retirer de ma sélection", key=f"retirer_{f['id']}",
                 help=f"L'offre est {quoi} ; l'analyse et la lettre sont gardées. Annulable juste après."):
        avant = selection.retirer(conn, f["id"])
        _retenir(f"{f['entreprise'] or 'Candidature'} retirée de ta sélection ({quoi}).", avant)
        st.session_state.pop(page_dossier.CLE_FICHE, None)
        st.rerun()
