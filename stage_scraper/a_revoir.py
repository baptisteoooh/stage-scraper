"""« À revoir » : le profil apprend de ce que l'étudiant fait dans « À trier ».

Quand une même raison revient souvent dans les offres écartées (« Trop long (6 mois) », « Entreprise »…), ou que
ses critères font perdre beaucoup d'offres (zone réduite), on lui propose UN changement du profil, validé en un clic.
Rien n'est appliqué sans son « Oui » ; un « Non » est retenu (table a_revoir_ignores) et ne revient pas.
Les propositions sont de simples {champ: nouvelle valeur} : la page les applique par POST /api/profil (annulable).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from . import profil

JOURS = 30          # on regarde les décisions des 30 derniers jours
SEUIL_RAISON = 3    # une raison doit revenir au moins 3 fois
SEUIL_ENTREPRISE = 2
SEUIL_ZONE = 5      # offres d'Île-de-France perdues à cause d'une zone réduite
MAX_PROPOSITIONS = 3

# Mots de titre qui signalent un poste non technique, pour « Commercial / pas technique ».
POSTES_NON_TECHNIQUES = ["sales", "business developer", "business development", "commercial", "marketing", "growth",
                         "account manager", "key account", "vente", "achats", "communication", "ressources humaines",
                         "talent acquisition", "recrutement", "customer success", "partnerships", "trade marketing"]

TEXTES = {
    "fr": {
        "six_exclure": ("Tu as écarté {n} offres pour « Trop long (6 mois) » ce mois-ci.",
                        "Ne plus garder les offres de 6 mois, même chez tes entreprises suivies ?"),
        "six_duree": ("Tu as écarté {n} offres pour « Trop long (6 mois) » ce mois-ci.",
                      "Revenir à 5 mois au plus ?"),
        "entreprise": ("Tu as écarté {n} offres de {nom} pour « Entreprise ».", "Ne plus suivre {nom} ?"),
        "poste": ("Tu as écarté {n} offres « {mot} » comme pas techniques.", "Écarter d'office les postes « {mot} » ?"),
        "zone": ("Ta zone a écarté {n} offres ailleurs en Île-de-France ce mois-ci.",
                 "Chercher dans toute l'Île-de-France ?"),
    },
    "en": {
        "six_exclure": ("You rejected {n} offers as « Too long (6 months) » this month.",
                        "Stop keeping 6-month offers, even at your followed companies?"),
        "six_duree": ("You rejected {n} offers as « Too long (6 months) » this month.", "Go back to 5 months max?"),
        "entreprise": ("You rejected {n} offers from {nom} as « Company ».", "Stop following {nom}?"),
        "poste": ("You rejected {n} « {mot} » offers as not technical.", "Always rule out « {mot} » jobs?"),
        "zone": ("Your area ruled out {n} offers elsewhere in Île-de-France this month.",
                 "Search all of Île-de-France?"),
    },
}


def propositions(conn, p: dict, langue: str = "fr", maintenant: datetime | None = None) -> list[dict]:
    """Au plus 3 propositions [{cle, constat, question, valeurs}], les plus marquées d'abord."""
    depuis = ((maintenant or datetime.now()) - timedelta(days=JOURS)).strftime("%Y-%m-%d %H:%M:%S")
    ignorees = {l[0] for l in conn.execute("SELECT cle FROM a_revoir_ignores")}
    t = TEXTES.get(langue, TEXTES["fr"])
    trouvees = []   # (poids, proposition)

    def proposer(poids, cle, texte, valeurs, **champs):
        if cle in ignorees:
            return
        # espaces insécables dans les guillemets : « Entreprise » ne se coupe jamais en fin de ligne
        constat, question = (x.format(**champs).replace("« ", "«\u00a0").replace(" »", "\u00a0»") for x in texte)
        trouvees.append((poids, {"cle": cle, "constat": constat, "question": question, "valeurs": valeurs}))

    ecartees = [dict(l) for l in conn.execute(
        "SELECT f.raison, o.titre, o.entreprise FROM feedback f JOIN offres o ON o.id = f.offre_id "
        "WHERE f.raison IS NOT NULL AND f.date >= ?", (depuis,))]
    par_raison = {}
    for e in ecartees:
        par_raison.setdefault(e["raison"], []).append(e)

    # 1. Trop long (6 mois)
    n = len(par_raison.get("Trop long (6 mois)", []))
    if n >= SEUIL_RAISON:
        if p["duree_max"] >= 6:
            proposer(n, "duree_max:5", t["six_duree"], {"duree_max": 5}, n=n)
        elif p["six_mois"] == "a_negocier":
            proposer(n, "six_mois:exclure", t["six_exclure"], {"six_mois": "exclure"}, n=n)

    # 2. Une entreprise suivie écartée plusieurs fois pour « Entreprise »
    for ent in p["entreprises"]:
        noms = {ent["nom"].lower(), *(a.strip().lower() for a in (ent.get("alias") or "").split(",") if a.strip())}
        n = sum(1 for e in par_raison.get("Entreprise", []) if (e["entreprise"] or "").strip().lower() in noms)
        if n >= SEUIL_ENTREPRISE:
            reste = [e for e in p["entreprises"] if e is not ent]
            proposer(n, f"retirer:{ent['nom']}", t["entreprise"], {"entreprises": reste}, n=n, nom=ent["nom"])

    # 3. Postes pas techniques : le mot qui revient le plus dans les titres écartés
    exclus = [x.lower() for x in p["postes_exclus"]]
    comptes = {}
    for e in par_raison.get("Commercial / pas technique", []):
        titre = (e["titre"] or "").lower()
        for mot in POSTES_NON_TECHNIQUES:
            if re.search(rf"\b{re.escape(mot)}\b", titre) and not any(x in mot or mot in x for x in exclus):
                comptes[mot] = comptes.get(mot, 0) + 1
    if comptes:
        mot, n = max(comptes.items(), key=lambda x: x[1])
        if n >= SEUIL_RAISON:
            proposer(n, f"poste:{mot}", t["poste"], {"postes_exclus": p["postes_exclus"] + [mot]}, n=n, mot=mot)

    # 4. Zone réduite : offres d'Île-de-France écartées seulement parce que hors de la zone choisie
    if set(profil.DEPARTEMENTS) - set(p["departements"]):
        hors_zone = [c for c in profil.DEPARTEMENTS if c not in p["departements"]]
        n = conn.execute(
            f"SELECT COUNT(*) FROM offres WHERE doublon_de IS NULL AND exclusion_prefiltre LIKE 'lieu :%' "
            f"AND departement IN ({','.join('?' * len(hors_zone))}) AND date_collecte >= ?", (*hors_zone, depuis)).fetchone()[0]
        if n >= SEUIL_ZONE:
            cle = "zone:" + ",".join(sorted(p["departements"]))   # change de clé si la zone change
            proposer(n, cle, t["zone"], {"departements": list(profil.DEPARTEMENTS)}, n=n)

    trouvees.sort(key=lambda x: -x[0])
    return [prop for _, prop in trouvees[:MAX_PROPOSITIONS]]


def ignorer(conn, cle: str) -> None:
    """« Non » : la proposition ne revient plus."""
    conn.execute("INSERT OR IGNORE INTO a_revoir_ignores (cle) VALUES (?)", (cle[:200],))
    conn.commit()
