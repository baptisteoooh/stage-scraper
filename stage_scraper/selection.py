"""« Ma sélection » : les offres gardées depuis À trier (ou trouvées ailleurs), suivies jusqu'à la réponse.

Une offre gardée a une candidature (table candidatures). Son étape vient du statut de la candidature :

    En préparation (à postuler) → Envoyée (postulé, relancé) → Entretien → Terminée (refus, accepté)

Chaque fiche réunit l'offre, la candidature et l'état du dossier (analyse de l'IA, lettre), et dit
quelle est la prochaine action : préparer, envoyer, relancer, préparer l'entretien.
Ce module ne fait que lire et écrire en base : l'affichage viendra plus tard.
"""
from datetime import date

from . import requetes

ETAPES = {
    "preparation": ("En préparation", ("à postuler",)),
    "envoyee": ("Envoyées", ("postulé", "relancé")),
    "entretien": ("Entretien", ("entretien",)),
    "terminee": ("Terminées", ("refus", "accepté")),
}
RESULTATS = ("refus", "accepté")
ACTIONS = {
    "preparer": "Préparer la candidature",
    "envoyer": "Envoyer la candidature",
    "relancer": "Relancer",
    "entretien": "Préparer l'entretien",
}

# Champs de l'offre et du dossier repris dans chaque fiche (la candidature est reprise en entier).
_REQUETE = """
SELECT c.*,
       o.titre AS titre_offre, o.entreprise AS entreprise_offre, o.lieu, o.score, o.categorie, o.section,
       o.resume, o.pourquoi, o.duree, o.duree_ia, o.date_debut, o.date_debut_ia, o.gratification, o.teletravail,
       o.type_contrat, o.poste_ia_data, o.source, o.lien AS lien_offre, o.expiration, o.description,
       d.id AS dossier_id, d.diagnostic IS NOT NULL AS analyse_faite, d.version_courante,
       (SELECT COUNT(*) FROM lettres_versions v WHERE v.dossier_id = d.id) AS nb_versions
FROM candidatures c
LEFT JOIN offres o ON o.id = c.offre_id
LEFT JOIN dossiers d ON d.offre_id = c.offre_id
"""


def etape_de(statut: str) -> str:
    return next(nom for nom, (_, statuts) in ETAPES.items() if statut in statuts)


def relance_due(c: dict, aujourd_hui: date | None = None) -> bool:
    return (c["statut"] in ("postulé", "relancé") and bool(c["date_relance"])
            and c["date_relance"][:10] <= (aujourd_hui or date.today()).isoformat())


def prochaine_action(f: dict, aujourd_hui: date | None = None) -> str | None:
    """Ce qu'il y a à faire sur cette offre maintenant (clé de ACTIONS), ou None s'il faut attendre."""
    etape = etape_de(f["statut"])
    if etape == "preparation":
        return "envoyer" if f.get("version_courante") else "preparer"
    if etape == "envoyee":
        return "relancer" if relance_due(f, aujourd_hui) else None
    if etape == "entretien":
        jour = (aujourd_hui or date.today()).isoformat()
        return "entretien" if not f.get("date_entretien") or f["date_entretien"][:10] >= jour else None
    return None


def _completer(f: dict, aujourd_hui: date | None) -> dict:
    f["titre"] = f["poste"] or f["titre_offre"] or "Candidature"
    f["entreprise"] = f["entreprise"] or f["entreprise_offre"]
    f["lien"] = f["lien"] or f["lien_offre"]
    f["etape"] = etape_de(f["statut"])
    f["relance_due"] = relance_due(f, aujourd_hui)
    f["action"] = prochaine_action(f, aujourd_hui)
    f["lettre_prete"] = bool(f["version_courante"])
    f["trouvee_ailleurs"] = f["source"] == "manuel"
    return f


def fiches(conn, aujourd_hui: date | None = None) -> list[dict]:
    """Toutes les offres de la sélection : d'abord celles qui demandent une action, puis les plus récentes."""
    lignes = [_completer(dict(l), aujourd_hui) for l in conn.execute(_REQUETE + " ORDER BY c.id DESC")]
    urgence = {"relancer": 0, "entretien": 1, "envoyer": 2, "preparer": 3, None: 4}
    return sorted(lignes, key=lambda f: urgence[f["action"]])   # tri stable : récentes d'abord à égalité


def par_etape(conn, aujourd_hui: date | None = None) -> dict[str, list[dict]]:
    """{'preparation': [...], 'envoyee': [...], 'entretien': [...], 'terminee': [...]}, chacune triée."""
    rangees = {nom: [] for nom in ETAPES}
    for f in fiches(conn, aujourd_hui):
        rangees[f["etape"]].append(f)
    return rangees


def fiche(conn, candidature_id: int, aujourd_hui: date | None = None) -> dict | None:
    """Une fiche complète : offre (texte de l'annonce gardé), candidature, dossier, lettre courante."""
    ligne = conn.execute(_REQUETE + " WHERE c.id = ?", (candidature_id,)).fetchone()
    if not ligne:
        return None
    f = _completer(dict(ligne), aujourd_hui)
    f["lettre_courante"] = None
    if f["version_courante"]:
        v = conn.execute("SELECT texte FROM lettres_versions WHERE dossier_id = ? AND numero = ?",
                         (f["dossier_id"], f["version_courante"])).fetchone()
        f["lettre_courante"] = v["texte"] if v else None
    return f


def changer_etape(conn, candidature_id: int, etape: str, relance_jours: int = 7, resultat: str = "refus",
                  aujourd_hui: date | None = None) -> dict:
    """Range l'offre dans une autre étape (dates d'envoi et de relance remplies). Renvoie l'état d'avant.

    Terminée : `resultat` dit si c'est un refus ou une acceptation. Rester dans la même étape ne change rien
    (une candidature relancée reste « relancée »).
    """
    avant = requetes.candidature(conn, candidature_id)
    if etape == "terminee":
        if resultat not in RESULTATS:
            raise ValueError(f"résultat inconnu : {resultat}")
        statut = resultat
    else:
        statut = ETAPES[etape][1][0]
    if etape != "terminee" and etape_de(avant["statut"]) == etape:
        return avant
    requetes.changer_statut(conn, candidature_id, statut, relance_jours, aujourd_hui)
    return avant


def noter_relance(conn, candidature_id: int, relance_jours: int = 7, aujourd_hui: date | None = None) -> dict:
    """« J'ai relancé » : prochain rappel dans `relance_jours` jours. Renvoie l'état d'avant."""
    return requetes.changer_statut(conn, candidature_id, "relancé", relance_jours, aujourd_hui)


def fixer_entretien(conn, candidature_id: int, quand: str | None, relance_jours: int = 7) -> dict:
    """Date de l'entretien (AAAA-MM-JJ, éventuellement avec l'heure) ; range l'offre dans « Entretien »."""
    avant = changer_etape(conn, candidature_id, "entretien", relance_jours)
    requetes.modifier_candidature(conn, candidature_id, date_entretien=quand)
    return avant


def annuler(conn, avant: dict) -> None:
    """Remet la candidature dans l'état renvoyé par changer_etape, noter_relance ou fixer_entretien."""
    requetes.restaurer_candidature(conn, avant)


def compter(conn) -> dict[str, int]:
    """Nombre d'offres par étape, et nombre d'actions à faire (pour les compteurs de l'interface)."""
    toutes = fiches(conn)
    return {**{nom: sum(1 for f in toutes if f["etape"] == nom) for nom in ETAPES},
            "actions": sum(1 for f in toutes if f["action"])}
