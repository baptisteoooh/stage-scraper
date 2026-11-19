"""Lectures et écritures en base utilisées par l'appli (offres, candidatures, journal)."""
from datetime import datetime

STATUTS = ["à postuler", "postulé", "relancé", "entretien", "refus", "accepté"]
SECTIONS = ["Santé", "Hors santé mais intéressant", "À négocier"]

# Offre visible = ni doublon, ni exclue (pré-filtre ou IA), ni marquée « pas intéressé », ni expirée.
VISIBLE = ("doublon_de IS NULL AND exclusion_prefiltre IS NULL AND exclusion_ia IS NULL "
           "AND pas_interesse = 0 AND expiration IS NULL")


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


def offres_a_trier(conn) -> list[dict]:
    """Offres gardées sur lesquelles BAP n'a pas encore décidé : ni candidature, ni « pas pour moi ».

    Les offres rangées « plus tard » (colonne favori) en font partie : la page À trier les met à part.
    """
    lignes = conn.execute(
        f"SELECT * FROM offres WHERE {VISIBLE} AND source != 'manuel' AND id NOT IN "
        "(SELECT offre_id FROM candidatures WHERE offre_id IS NOT NULL)").fetchall()
    return [dict(l) for l in lignes]


SOURCES_HORS_SCRAP = ("dossier", "chat", "lettre", "scoring")   # lignes du journal qui ne sont pas une collecte


def dernier_scrap(conn) -> dict | None:
    """Le dernier scrap (même sans nouvelle offre) : date, mode, offres gardées, sources en erreur."""
    marques = ", ".join("?" * len(SOURCES_HORS_SCRAP))
    passage = conn.execute(f"SELECT MAX(passage_id) FROM runs WHERE source NOT IN ({marques})",
                           SOURCES_HORS_SCRAP).fetchone()[0]
    if passage is None:
        return None
    lignes = [dict(l) for l in conn.execute(
        f"SELECT * FROM runs WHERE passage_id = ? AND source NOT IN ({marques}) ORDER BY id",
        (passage, *SOURCES_HORS_SCRAP))]
    compte = lambda condition: conn.execute(  # noqa: E731
        f"SELECT COUNT(*) FROM offres WHERE passage_id = ? AND {VISIBLE}{condition}", (passage,)).fetchone()[0]
    return {"passage_id": passage, "date": min(l["date_debut"] for l in lignes),
            "auto": any(l["declenchement"] == "auto" for l in lignes),
            "nouvelles": compte(""), "top": compte(" AND score >= 8"),
            "en_erreur": [l["source"] for l in lignes if l["erreurs"]]}


def preciser_raison(conn, offre_id: int, raison: str | None) -> None:
    """Raison d'un « pas pour moi », choisie après coup (elle sert d'exemple à l'IA)."""
    conn.execute("UPDATE feedback SET raison = ? WHERE offre_id = ?", ((raison or "").strip() or None, offre_id))
    conn.commit()


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
        "SELECT o.id, o.titre, o.entreprise, o.lieu, o.score, o.lien, f.raison, f.date "
        "FROM feedback f JOIN offres o ON o.id = f.offre_id ORDER BY f.id DESC")]


def completer_annonce(conn, offre_id: int, description: str | None) -> None:
    """Texte de l'annonce d'une offre trouvée ailleurs, collé par BAP (l'IA en a besoin pour l'analyse)."""
    conn.execute("UPDATE offres SET description = ? WHERE id = ? AND source = 'manuel'",
                 ((description or "").strip() or None, offre_id))
    conn.commit()


def basculer_favori(conn, offre_id: int) -> bool:
    """Ajoute l'offre aux favoris, ou l'en retire si elle y était. Renvoie le nouvel état."""
    conn.execute("UPDATE offres SET favori = 1 - favori, "
                 "date_favori = CASE WHEN favori = 0 THEN ? ELSE NULL END WHERE id = ?", (maintenant(), offre_id))
    conn.commit()
    ligne = conn.execute("SELECT favori FROM offres WHERE id = ?", (offre_id,)).fetchone()
    return bool(ligne and ligne[0])


def offres_favorites(conn, aussi: set[int] | frozenset = frozenset()) -> list[dict]:
    """Offres gardées en favori, même déjà vues, expirées ou écartées par le tri (sauf « pas intéressé »).

    `aussi` : offres retirées des favoris pendant la visite, gardées à l'écran pour pouvoir annuler.
    """
    marques = ", ".join("?" * len(aussi))
    condition = f"(favori = 1 OR id IN ({marques}))" if aussi else "favori = 1"
    lignes = conn.execute(
        f"SELECT * FROM offres WHERE {condition} AND pas_interesse = 0 "
        "ORDER BY score IS NULL, score DESC, date_publication DESC, id DESC", list(aussi)).fetchall()
    return [dict(l) for l in lignes]


TRIS = ["Meilleure note", "Plus récentes"]


def trier_offres(offres: list[dict], tri: str = "Meilleure note") -> list[dict]:
    """« Meilleure note » : note décroissante (non notées à la fin), puis les plus récentes.
    « Plus récentes » : date de publication (ou, à défaut, de collecte) décroissante, puis la note."""
    def jour(o):
        return (o.get("date_publication") or o.get("date_collecte") or "")[:10]

    def note(o):
        return -1 if o.get("score") is None else o["score"]

    if tri == "Plus récentes":
        cle = lambda o: (jour(o), note(o), o["id"])  # noqa: E731
    else:
        cle = lambda o: (o.get("score") is not None, note(o), jour(o), o["id"])  # noqa: E731
    return sorted(offres, key=cle, reverse=True)


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
        conn.execute("UPDATE offres SET vue = 1 WHERE id = ?", (offre_id,))
    curseur = conn.execute(
        "INSERT INTO candidatures (offre_id, entreprise, poste, lien, statut, notes, date_maj) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", (offre_id, entreprise, poste, lien, statut, notes, maintenant()))
    conn.commit()
    return curseur.lastrowid


def candidatures(conn) -> list[dict]:
    return [dict(l) for l in conn.execute("SELECT * FROM candidatures ORDER BY date_creation DESC, id DESC")]


CHAMPS_CANDIDATURE = ("entreprise", "poste", "lien", "statut", "date_candidature", "date_relance", "notes")


def candidature(conn, candidature_id: int) -> dict | None:
    ligne = conn.execute("SELECT * FROM candidatures WHERE id = ?", (candidature_id,)).fetchone()
    return dict(ligne) if ligne else None


def ajouter_a_la_main(conn, entreprise: str | None, poste: str | None, lien: str | None, statut: str,
                      notes: str | None, envoyee=None, relance_jours: int = 7, description: str | None = None,
                      lieu: str | None = None) -> int:
    """Offre trouvée hors de l'outil : elle devient une offre (source « manuel ») avec sa candidature.

    Elle a donc une fiche comme les autres ; avec le texte de l'annonce (`description`), l'IA peut
    l'analyser et écrire la lettre. Déjà envoyée : date d'envoi et date de relance remplies.
    """
    import uuid
    from datetime import date, timedelta
    curseur = conn.execute(
        "INSERT INTO offres (source, source_id, titre, entreprise, lien, lieu, description, vue, notifiee, empreinte) "
        "VALUES ('manuel', ?, ?, ?, ?, ?, ?, 1, 1, 'manuel')",
        (f"manuel-{uuid.uuid4().hex[:12]}", poste or entreprise or "Candidature", entreprise, lien, lieu,
         (description or "").strip() or None))
    identifiant = creer_candidature(conn, offre_id=curseur.lastrowid, entreprise=entreprise, poste=poste, lien=lien,
                                    statut=statut, notes=notes)
    if statut != "à postuler":
        envoyee = envoyee or date.today()
        champs = {"date_candidature": envoyee.isoformat()}
        if statut in ("postulé", "relancé"):
            champs["date_relance"] = (envoyee + timedelta(days=relance_jours)).isoformat()
        modifier_candidature(conn, identifiant, **champs)
    return identifiant


def modifier_candidature(conn, candidature_id: int, **champs) -> None:
    """Met à jour les champs donnés (entreprise, poste, lien, statut, dates, notes, lettre)."""
    valeurs = {c: _vide_en_none(v) for c, v in champs.items()
               if c in (*CHAMPS_CANDIDATURE, "lettre", "date_entretien")}
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


APPELS_IA = ("dossier", "chat", "lettre")   # appels d'IA faits depuis l'appli (pas pendant un scrap)


def passages(conn, limite: int = 60) -> list[dict]:
    """Une ligne par passage (scrap et notation) : sources, offres, erreurs, coût de la notation."""
    marques = ", ".join("?" * len(APPELS_IA))
    lignes = [dict(l) for l in conn.execute(
        f"SELECT * FROM runs WHERE source NOT IN ({marques}) AND passage_id IN (SELECT DISTINCT passage_id FROM runs "
        f"WHERE source NOT IN ({marques}) ORDER BY passage_id DESC LIMIT ?) ORDER BY id",
        (*APPELS_IA, *APPELS_IA, limite))]
    par_passage: dict[int, list[dict]] = {}
    for l in lignes:
        par_passage.setdefault(l["passage_id"], []).append(l)
    resultat = []
    for passage_id, runs in sorted(par_passage.items(), reverse=True):
        collecte = [r for r in runs if r["source"] != "scoring"]
        compte = lambda condition: conn.execute(  # noqa: E731
            f"SELECT COUNT(*) FROM offres WHERE passage_id = ? AND {VISIBLE}{condition}", (passage_id,)).fetchone()[0]
        resultat.append({
            "passage_id": passage_id, "date": min(r["date_debut"] for r in runs),
            "auto": any(r["declenchement"] == "auto" for r in runs),
            "sources": len(collecte),
            "trouvees": sum(r["nb_offres"] for r in collecte),
            "nouvelles": sum(r["nb_nouvelles"] for r in collecte),
            "gardees": compte(""), "top": compte(" AND score >= 8"),
            "notees": sum(r["nb_offres"] for r in runs if r["source"] == "scoring"),
            "cout_usd": sum(r["cout_usd"] for r in runs),
            "en_erreur": [r["source"] for r in runs if r["erreurs"]],
            "erreurs": {r["source"]: r["erreurs"] for r in runs if r["erreurs"]},
        })
    return resultat


def appels_ia(conn, limite: int = 200) -> list[dict]:
    """Appels d'IA faits depuis l'appli : fiches de Ma sélection (dossier, lettre) et Assistant (chat)."""
    marques = ", ".join("?" * len(APPELS_IA))
    return [dict(l) for l in conn.execute(
        f"SELECT * FROM runs WHERE source IN ({marques}) ORDER BY id DESC LIMIT ?", (*APPELS_IA, limite))]


def couts_ia(conn) -> dict:
    ia = "source IN ('scoring', 'lettre', 'chat', 'dossier')"
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
