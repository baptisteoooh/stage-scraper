"""Lectures et écritures en base utilisées par l'appli (offres, candidatures, journal)."""
from datetime import datetime

STATUTS = ["à postuler", "postulé", "relancé", "entretien", "refus", "accepté"]
SECTIONS = ["Santé", "Hors santé mais intéressant", "À négocier"]

# Offre visible = ni doublon, ni exclue (pré-filtre ou IA), ni marquée « pas intéressé ».
VISIBLE = ("doublon_de IS NULL AND exclusion_prefiltre IS NULL AND exclusion_ia IS NULL "
           "AND pas_interesse = 0")


def maintenant() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


# --------------------------------------------------------------------------- offres

def dernier_passage(conn) -> int | None:
    """Dernier passage qui a ajouté au moins une offre."""
    return conn.execute("SELECT MAX(passage_id) FROM offres").fetchone()[0]


def offres_visibles(conn, filtre: str = "toutes", passage_id: int | None = None) -> list[dict]:
    """Offres gardées, triées par score (les offres pas encore notées à la fin).

    filtre : 'toutes', 'non_vues' ou 'passage' (offres trouvées par `passage_id`).
    """
    conditions, parametres = [VISIBLE], []
    if filtre == "non_vues":
        conditions.append("vue = 0")
    elif filtre == "passage":
        conditions.append("passage_id = ?")
        parametres.append(passage_id)
    lignes = conn.execute(
        f"SELECT * FROM offres WHERE {' AND '.join(conditions)} "
        "ORDER BY score IS NULL, score DESC, date_publication DESC, id DESC", parametres).fetchall()
    return [dict(l) for l in lignes]


def offres_exclues(conn) -> list[dict]:
    """Offres écartées par le pré-filtre ou l'IA (pour vérifier que le tri ne se trompe pas)."""
    lignes = conn.execute(
        "SELECT * FROM offres WHERE doublon_de IS NULL AND (exclusion_prefiltre IS NOT NULL "
        "OR exclusion_ia IS NOT NULL) ORDER BY date_collecte DESC, id DESC").fetchall()
    return [dict(l) for l in lignes]


def offre(conn, offre_id: int) -> dict | None:
    ligne = conn.execute("SELECT * FROM offres WHERE id = ?", (offre_id,)).fetchone()
    return dict(ligne) if ligne else None


def doublons_de(conn, offre_id: int) -> list[dict]:
    """Les autres annonces de la même offre (autres sites), pour afficher tous les liens."""
    return [dict(l) for l in conn.execute(
        "SELECT id, source, site_origine, lien FROM offres WHERE doublon_de = ? ORDER BY id", (offre_id,))]


def marquer_vue(conn, offre_id: int) -> None:
    conn.execute("UPDATE offres SET vue = 1 WHERE id = ?", (offre_id,))
    conn.commit()


def marquer_pas_interesse(conn, offre_id: int, raison: str | None = None) -> None:
    conn.execute("UPDATE offres SET pas_interesse = 1, vue = 1 WHERE id = ?", (offre_id,))
    conn.execute("INSERT INTO feedback (offre_id, raison) VALUES (?, ?)", (offre_id, (raison or "").strip() or None))
    conn.commit()


def annuler_pas_interesse(conn, offre_id: int) -> None:
    conn.execute("UPDATE offres SET pas_interesse = 0 WHERE id = ?", (offre_id,))
    conn.execute("DELETE FROM feedback WHERE offre_id = ?", (offre_id,))
    conn.commit()


def offres_pas_interesse(conn) -> list[dict]:
    return [dict(l) for l in conn.execute(
        "SELECT o.id, o.titre, o.entreprise, f.raison, f.date FROM feedback f JOIN offres o ON o.id = f.offre_id "
        "ORDER BY f.id DESC")]


# --------------------------------------------------------------------------- candidatures

def candidature_de(conn, offre_id: int) -> dict | None:
    ligne = conn.execute("SELECT * FROM candidatures WHERE offre_id = ?", (offre_id,)).fetchone()
    return dict(ligne) if ligne else None


def creer_candidature(conn, offre_id: int | None = None, entreprise: str | None = None,
                      poste: str | None = None, lien: str | None = None, statut: str = "à postuler",
                      notes: str | None = None) -> int:
    """Crée une candidature, liée à une offre (ses infos sont recopiées) ou ajoutée à la main."""
    if offre_id is not None:
        existante = candidature_de(conn, offre_id)
        if existante:
            return existante["id"]
        o = offre(conn, offre_id)
        entreprise, poste, lien = entreprise or o["entreprise"], poste or o["titre"], lien or o["lien"]
    curseur = conn.execute(
        "INSERT INTO candidatures (offre_id, entreprise, poste, lien, statut, notes, date_maj) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", (offre_id, entreprise, poste, lien, statut, notes, maintenant()))
    conn.commit()
    return curseur.lastrowid


def candidatures(conn) -> list[dict]:
    return [dict(l) for l in conn.execute("SELECT * FROM candidatures ORDER BY date_creation DESC, id DESC")]


CHAMPS_CANDIDATURE = ("entreprise", "poste", "lien", "statut", "date_candidature", "date_relance", "notes")


def enregistrer_candidatures(conn, lignes: list[dict]) -> dict:
    """Applique le tableau modifié dans l'appli : ajouts, modifications, suppressions."""
    existantes = {c["id"]: c for c in candidatures(conn)}
    vues, bilan = set(), {"ajoutees": 0, "modifiees": 0, "supprimees": 0}
    for ligne in lignes:
        valeurs = {c: _vide_en_none(ligne.get(c)) for c in CHAMPS_CANDIDATURE}
        if valeurs["statut"] not in STATUTS:
            valeurs["statut"] = "à postuler"
        identifiant = ligne.get("id")
        if identifiant in existantes:
            vues.add(identifiant)
            if any(valeurs[c] != _vide_en_none(existantes[identifiant][c]) for c in CHAMPS_CANDIDATURE):
                conn.execute(f"UPDATE candidatures SET {', '.join(f'{c} = ?' for c in valeurs)}, date_maj = ? "
                             "WHERE id = ?", [*valeurs.values(), maintenant(), identifiant])
                bilan["modifiees"] += 1
        elif valeurs["entreprise"] or valeurs["poste"]:
            conn.execute(f"INSERT INTO candidatures ({', '.join(valeurs)}, date_maj) VALUES "
                         f"({', '.join('?' for _ in valeurs)}, ?)", [*valeurs.values(), maintenant()])
            bilan["ajoutees"] += 1
    for identifiant in set(existantes) - vues:
        conn.execute("DELETE FROM candidatures WHERE id = ?", (identifiant,))
        bilan["supprimees"] += 1
    conn.commit()
    return bilan


def candidature(conn, candidature_id: int) -> dict | None:
    ligne = conn.execute("SELECT * FROM candidatures WHERE id = ?", (candidature_id,)).fetchone()
    return dict(ligne) if ligne else None


def modifier_candidature(conn, candidature_id: int, **champs) -> None:
    """Met à jour les champs donnés (entreprise, poste, lien, statut, dates, notes, lettre)."""
    valeurs = {c: _vide_en_none(v) for c, v in champs.items() if c in (*CHAMPS_CANDIDATURE, "lettre")}
    if "statut" in valeurs and valeurs["statut"] not in STATUTS:
        raise ValueError(f"statut inconnu : {valeurs['statut']}")
    if not valeurs:
        return
    conn.execute(f"UPDATE candidatures SET {', '.join(f'{c} = ?' for c in valeurs)}, date_maj = ? WHERE id = ?",
                 [*valeurs.values(), maintenant(), candidature_id])
    conn.commit()


def changer_statut(conn, candidature_id: int, statut: str, relance_jours: int = 7, aujourd_hui=None) -> dict:
    """Passe une candidature à l'étape suivante et remplit les dates utiles.

    Renvoie l'état d'avant, pour pouvoir annuler.
    """
    from datetime import date, timedelta
    avant = candidature(conn, candidature_id)
    jour = aujourd_hui or date.today()
    champs = {"statut": statut}
    if statut == "postulé":
        champs["date_candidature"] = avant["date_candidature"] or jour.isoformat()
        champs["date_relance"] = (jour + timedelta(days=relance_jours)).isoformat()
    elif statut == "relancé":
        champs["date_relance"] = (jour + timedelta(days=relance_jours)).isoformat()  # prochain rappel
    elif statut in ("entretien", "refus", "accepté"):
        champs["date_relance"] = None
    modifier_candidature(conn, candidature_id, **champs)
    return avant


def supprimer_candidature(conn, candidature_id: int) -> dict | None:
    """Supprime une candidature et la renvoie (pour pouvoir l'annuler)."""
    avant = candidature(conn, candidature_id)
    conn.execute("DELETE FROM candidatures WHERE id = ?", (candidature_id,))
    conn.commit()
    return avant


def restaurer_candidature(conn, ligne: dict) -> None:
    """Annule une modification ou une suppression : remet la candidature telle qu'elle était."""
    colonnes = [c for c in ligne if c != "id"]
    conn.execute(f"INSERT OR REPLACE INTO candidatures (id, {', '.join(colonnes)}) VALUES "
                 f"(?, {', '.join('?' for _ in colonnes)})", [ligne["id"], *(ligne[c] for c in colonnes)])
    conn.commit()


def _vide_en_none(valeur):
    if valeur is None:
        return None
    try:
        if valeur != valeur:  # case vide du tableau de l'appli (NaN, NaT)
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(valeur, "isoformat"):  # date choisie dans le calendrier de l'appli
        return valeur.isoformat()[:10]
    texte = str(valeur).strip()
    return texte or None


# --------------------------------------------------------------------------- journal

def journal(conn, limite: int = 200) -> list[dict]:
    return [dict(l) for l in conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limite,))]


def couts_ia(conn) -> dict:
    ia = "source IN ('scoring', 'lettre')"
    total = conn.execute(f"SELECT COALESCE(SUM(cout_usd), 0) FROM runs WHERE {ia}").fetchone()[0]
    mois = conn.execute(f"SELECT COALESCE(SUM(cout_usd), 0) FROM runs WHERE {ia} AND date_debut >= ?",
                        (datetime.now().strftime("%Y-%m-01"),)).fetchone()[0]
    return {"total": total, "mois": mois}


def enregistrer_lettre(conn, offre_id: int, texte: str) -> int:
    """Garde le brouillon de lettre dans la candidature de l'offre (créée si besoin)."""
    candidature_id = creer_candidature(conn, offre_id=offre_id)
    conn.execute("UPDATE candidatures SET lettre = ?, date_maj = ? WHERE id = ?", (texte, maintenant(), candidature_id))
    conn.commit()
    return candidature_id


def statistiques(conn) -> dict:
    une = lambda requete: conn.execute(requete).fetchone()[0]  # noqa: E731
    return {
        "total": une("SELECT COUNT(*) FROM offres"),
        "visibles": une(f"SELECT COUNT(*) FROM offres WHERE {VISIBLE}"),
        "non_vues": une(f"SELECT COUNT(*) FROM offres WHERE {VISIBLE} AND vue = 0"),
        "a_noter": une(f"SELECT COUNT(*) FROM offres WHERE {VISIBLE} AND score IS NULL"),
        "a_postuler_vite": une(f"SELECT COUNT(*) FROM offres WHERE {VISIBLE} AND categorie = 'À postuler vite'"),
        "candidatures": une("SELECT COUNT(*) FROM candidatures"),
    }
