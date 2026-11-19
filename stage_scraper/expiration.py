"""Offres expirées : masquées dans l'appli et les mails, mais gardées en base.

On ne les efface pas : une candidature déjà liée garde son offre, et une offre effacée
reviendrait comme « nouvelle » au passage suivant. Trois façons d'expirer :
- 'retiree'  : l'offre n'est plus sur la page carrières de l'entreprise (vérifié à chaque
               passage, seulement quand la liste de l'entreprise a été lue en entier) ;
- 'ancienne' : publiée il y a plus de `general.anciennete_max_jours` jours. Ne concerne pas
               les pages carrières, où l'on sait si l'offre est encore en ligne ;
- 'manuelle' : bouton « Offre expirée » dans la fiche.

Les annonces en double (même offre vue sur un autre site) suivent leur offre principale.
"""
from datetime import date, datetime, timedelta

RAISONS = {
    "retiree": "retirée du site de l'entreprise",
    "ancienne": "publiée il y a trop longtemps",
    "manuelle": "signalée expirée à la main",
}
SOURCES_VERIFIEES = ("carrieres",)  # sources dont on relit la liste complète à chaque passage


def raison(offre: dict) -> str | None:
    """Texte affiché dans l'appli, ou None si l'offre n'est pas expirée."""
    if not offre.get("expiration"):
        return None
    jour = (offre.get("date_expiration") or "")[:10]
    return RAISONS.get(offre["expiration"], offre["expiration"]) + (f" (le {jour})" if jour else "")


def retirees_du_site(conn, source: str, listes_completes: dict[str, set[str]]) -> dict:
    """Expire les offres absentes d'une liste complète, et rétablit celles qui y sont revenues.

    listes_completes : {préfixe de source_id (ex. 'ashby:doctolib:'): source_id vus ce passage}.
    """
    bilan = {"expirees": 0, "retablies": 0}
    for prefixe, vus in listes_completes.items():
        motif = _echapper_like(prefixe) + "%"
        connues = conn.execute(
            "SELECT id, source_id, expiration FROM offres WHERE source = ? AND source_id LIKE ? ESCAPE '\\'",
            (source, motif)).fetchall()
        for ligne in connues:
            if ligne["source_id"] not in vus and ligne["expiration"] is None:
                _expirer(conn, ligne["id"], "retiree")
                bilan["expirees"] += 1
            elif ligne["source_id"] in vus and ligne["expiration"] == "retiree":
                _retablir(conn, ligne["id"], "retiree")
                bilan["retablies"] += 1
    conn.commit()
    return bilan


def trop_anciennes(conn, config: dict, aujourd_hui: date | None = None) -> int:
    """Expire les offres trop anciennes (hors pages carrières). Renvoie le nombre d'offres expirées.

    Recalculé à chaque passage : si l'ancienneté max augmente, les offres redeviennent visibles.
    """
    aujourd_hui = aujourd_hui or date.today()
    limite = (aujourd_hui - timedelta(days=config["general"].get("anciennete_max_jours", 90))).isoformat()
    jour = "substr(COALESCE(date_publication, date_collecte), 1, 10)"
    exclues = ", ".join("?" * len(SOURCES_VERIFIEES))
    conn.execute(f"UPDATE offres SET expiration = NULL, date_expiration = NULL "
                 f"WHERE expiration = 'ancienne' AND {jour} >= ?", (limite,))
    # Pas d'expiration par l'âge quand une annonce en double vient d'une page carrières :
    # c'est elle qui dit si l'offre est encore en ligne.
    curseur = conn.execute(
        f"UPDATE offres SET expiration = 'ancienne', date_expiration = ? "
        f"WHERE expiration IS NULL AND {jour} < ? AND source NOT IN ({exclues}) "
        f"AND id NOT IN (SELECT doublon_de FROM offres WHERE doublon_de IS NOT NULL AND source IN ({exclues}))",
        (_maintenant(), limite, *SOURCES_VERIFIEES, *SOURCES_VERIFIEES))
    conn.commit()
    return curseur.rowcount


def marquer_expiree(conn, offre_id: int) -> None:
    _expirer(conn, offre_id, "manuelle")
    conn.commit()


def annuler(conn, offre_id: int) -> None:
    """Remet en ligne une offre signalée expirée à la main (et ses doublons)."""
    _retablir(conn, offre_id, "manuelle")
    conn.commit()


def expirees(conn) -> list[dict]:
    """Offres principales expirées, les plus récentes d'abord."""
    return [dict(l) for l in conn.execute(
        "SELECT * FROM offres WHERE expiration IS NOT NULL AND doublon_de IS NULL "
        "AND exclusion_prefiltre IS NULL AND exclusion_ia IS NULL "
        "ORDER BY date_expiration DESC, id DESC")]


def _principale(conn, offre_id: int) -> int:
    """L'offre affichée dans l'appli : elle-même, ou celle dont elle est le doublon."""
    ligne = conn.execute("SELECT doublon_de FROM offres WHERE id = ?", (offre_id,)).fetchone()
    return (ligne["doublon_de"] if ligne else None) or offre_id


def _expirer(conn, offre_id: int, code: str) -> None:
    principale = _principale(conn, offre_id)
    conn.execute("UPDATE offres SET expiration = ?, date_expiration = ? "
                 "WHERE (id = ? OR doublon_de = ?) AND expiration IS NULL",
                 (code, _maintenant(), principale, principale))


def _retablir(conn, offre_id: int, code: str) -> None:
    principale = _principale(conn, offre_id)
    conn.execute("UPDATE offres SET expiration = NULL, date_expiration = NULL "
                 "WHERE (id = ? OR doublon_de = ?) AND expiration = ?", (principale, principale, code))


def _echapper_like(texte: str) -> str:
    antislash = chr(92)
    return texte.replace(antislash, antislash * 2).replace("%", antislash + "%").replace("_", antislash + "_")


def _maintenant() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")
