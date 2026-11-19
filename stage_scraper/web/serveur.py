"""Serveur du site : pages (HTML/CSS/JS du dossier « statique ») et API JSON lue par ces pages.

Lancement : python site_web.py (ouvre http://127.0.0.1:8000). Le serveur n'écoute que sur l'ordinateur
lui-même (127.0.0.1) : personne d'autre sur le réseau ne peut s'y connecter.

API
- GET  /api/a-trier            offres à trier (cartes), compteurs, dernier scrap
- GET  /api/offres/{id}        détail d'une offre (annonce complète, liens)
- POST /api/decision           {offre_id, action} : candidate | ecarte | plus_tard | remettre
- POST /api/annuler            la décision renvoyée par /api/decision
- POST /api/raison             {offre_id, raison} : pourquoi « pas pour moi » (facultatif)
- POST /api/scrap  /  GET /api/scrap   lancer un scrap manuel / suivre son avancement
- GET  /api/selection          Ma sélection : fiches rangées par étape, compteurs
- GET  /api/selection/{id}     une fiche (dates, notes, lettre)
- POST /api/selection/{id}/etape | /relance | /dates | /retirer   changements (renvoient un jeton d'annulation)
- POST /api/selection/annuler  {jeton} : remet la candidature comme avant
- POST /api/selection/nouvelle offre trouvée ailleurs
- GET  /api/journal            passages (scraps), coût de l'IA, crédit Claude restant
- GET  /api/corbeille          offres écartées (par BAP, par le tri) et expirées
- POST /api/corbeille/remettre {offre_id, liste} : remet une offre dans À trier
"""
import logging
import os
import secrets
import threading
from contextlib import asynccontextmanager, closing
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import claude, db, decisions, expiration, presentation, requetes, selection
from ..config import charger_config, chemin_projet, secret

STATIQUE = Path(__file__).parent / "statique"
SEUIL_BOF = 5



@asynccontextmanager
async def _demarrage(_app):
    with connexion() as conn:   # crée ou met à jour les tables avant la première page
        db.initialiser(conn)
    yield


app = FastAPI(title="Stage Scraper", docs_url=None, redoc_url=None, lifespan=_demarrage)
app.mount("/statique", StaticFiles(directory=STATIQUE), name="statique")


# =========================================================================== base

def chemin_base() -> Path:
    """Base de config.yaml, sauf si la variable STAGE_SCRAPER_BASE en désigne une autre (tests, essais)."""
    autre = os.getenv("STAGE_SCRAPER_BASE")
    return Path(autre) if autre else chemin_projet(charger_config()["general"]["base_de_donnees"])


def connexion():
    conn = db.connecter(chemin_base())
    return closing(conn)


# =========================================================================== pages

@app.get("/", include_in_schema=False)
def page_accueil():
    return FileResponse(STATIQUE / "accueil.html")


def page_appli(nom: str) -> HTMLResponse:
    """Page de l'appli avec le menu de gauche (un seul fichier, _menu.html), la page en cours marquée."""
    page = (STATIQUE / f"{nom}.html").read_text(encoding="utf-8")
    menu = (STATIQUE / "_menu.html").read_text(encoding="utf-8")
    lien = f'<a href="/{nom}">'
    menu = menu.replace(lien, f'<a class="on" href="/{nom}" aria-current="page">')
    return HTMLResponse(page.replace("<!-- menu -->", menu), headers={"Cache-Control": "no-cache"})


@app.get("/a-trier", include_in_schema=False)
def page_a_trier():
    return page_appli("a-trier")


@app.get("/selection", include_in_schema=False)
def page_selection():
    return page_appli("selection")


@app.get("/journal", include_in_schema=False)
def page_journal():
    return page_appli("journal")


@app.get("/corbeille", include_in_schema=False)
def page_corbeille():
    return page_appli("corbeille")


# =========================================================================== mise en forme

def _lieu(o: dict) -> str:
    morceaux = [presentation.lieu_court(o["lieu"]) or "Lieu non précisé"]
    if o["teletravail"]:
        morceaux.append(o["teletravail"].capitalize())
    return " · ".join(morceaux)


def _puces(o: dict) -> list[dict]:
    """Petites étiquettes de la carte : IA / data, CDD, durée, début, gratification."""
    puces = []
    if o["poste_ia_data"]:
        puces.append({"texte": "IA / data", "type": "ia"})
    if o["type_contrat"] == "cdd":
        puces.append({"texte": "CDD", "type": "cdd"})
    duree = presentation._court(o["duree"] or o["duree_ia"], 22)
    debut = presentation.debut_lisible(o)
    puces.append({"texte": duree or "Durée ?", "type": "" if duree else "inconnu"})
    puces.append({"texte": presentation._court(debut, 22).capitalize() if debut else "Début ?",
                  "type": "" if debut else "inconnu"})
    if o["gratification"]:
        puces.append({"texte": presentation._court(o["gratification"], 26), "type": ""})
    return puces


def carte(o: dict, nouveau_passage: int | None = None, aujourd_hui: date | None = None) -> dict:
    """Ce que la page affiche d'une offre (pas la description complète : elle vient avec /api/offres/{id})."""
    entreprise = (o["entreprise"] or "Entreprise inconnue").strip()
    return {
        "id": o["id"],
        "entreprise": entreprise,
        "initiale": next((c for c in entreprise if c.isalnum()), "?").upper(),
        "lieu": _lieu(o),
        "score": o["score"],
        "titre": o["titre"],
        "puces": _puces(o),
        "resume": o["resume"] or ("Pas encore notée par l'IA." if o["score"] is None else ""),
        "pourquoi": o["pourquoi"],
        "lien": o["lien"],
        "section": o["section"],
        "plus_tard": bool(o["favori"]),
        "bof": o["score"] is not None and o["score"] < SEUIL_BOF,
        "nouvelle": nouveau_passage is not None and o["passage_id"] == nouveau_passage,
        "date": (o["date_publication"] or o["date_collecte"] or "")[:10],
        "anciennete": presentation.anciennete(o["date_publication"], aujourd_hui),
        "site": o["site_origine"] or o["source"],
    }


def phrase_scrap(s: dict | None, maintenant: datetime | None = None) -> dict | None:
    """{'titre': 'Dernier scrap aujourd'hui à 12 h 11', 'texte': '10 nouvelles offres, dont 4 notées 8 ou plus.'}"""
    if not s:
        return None
    quand = datetime.fromisoformat(s["date"])
    jours = ((maintenant or datetime.now()).date() - quand.date()).days
    jour = {0: "aujourd'hui", 1: "hier"}.get(jours, f"le {quand:%d/%m}")
    n = s["nouvelles"]
    texte = f"{n} nouvelle{'s' if n > 1 else ''} offre{'s' if n > 1 else ''}" if n else "Aucune nouvelle offre"
    if s["top"]:
        texte += f", dont {s['top']} notée{'s' if s['top'] > 1 else ''} 8 ou plus"
    texte += "."
    if s["en_erreur"]:
        texte += f" En erreur : {', '.join(s['en_erreur'])}."
    return {"titre": f"Dernier scrap {jour} à {quand.hour} h {quand:%M}", "texte": texte, "auto": s["auto"]}


# =========================================================================== API : lecture

@app.get("/api/a-trier")
def api_a_trier():
    with connexion() as conn:
        scrap = requetes.dernier_scrap(conn)
        nouveau = scrap["passage_id"] if scrap else None
        offres = [carte(o, nouveau) for o in requetes.offres_a_trier(conn)]
        nb_selection = len(selection.fiches(conn))
    return {"offres": offres, "selection": nb_selection, "scrap": phrase_scrap(scrap),
            "ia_manquante": not secret("GEMINI_API_KEY") and any(o["score"] is None for o in offres)}


@app.get("/api/offres/{offre_id}")
def api_offre(offre_id: int):
    with connexion() as conn:
        o = requetes.offre(conn, offre_id)
        if o is None:
            raise HTTPException(404, "Offre introuvable")
        autres = requetes.doublons_de(conn, offre_id)
    return {**carte(o), "description": o["description"], "contact": o["contact"],
            "categorie": o["categorie"], "exclusion": o["exclusion_ia"],
            "extrait_seulement": o["source"] in presentation.SOURCES_EXTRAIT,
            "liens": [{"site": o["site_origine"] or o["source"], "lien": o["lien"]}]
                     + [{"site": a["site_origine"] or a["source"], "lien": a["lien"]} for a in autres if a["lien"]]}


# =========================================================================== API : décisions

class Decision(BaseModel):
    offre_id: int
    action: str


class Annulation(BaseModel):
    action: str
    offre_id: int
    candidature_id: int | None = None


class Raison(BaseModel):
    offre_id: int
    raison: str | None = None


@app.post("/api/decision")
def api_decision(d: Decision):
    with connexion() as conn:
        try:
            return decisions.appliquer(conn, d.offre_id, d.action)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e


@app.post("/api/annuler")
def api_annuler(a: Annulation):
    with connexion() as conn:
        decisions.annuler(conn, a.model_dump())
    return {"ok": True}


@app.post("/api/raison")
def api_raison(r: Raison):
    with connexion() as conn:
        requetes.preciser_raison(conn, r.offre_id, r.raison)
    return {"ok": True}


# =========================================================================== API : Ma sélection

ETAPES_FICHE = {"preparation": "En préparation", "envoyee": "Envoyée", "entretien": "Entretien", "terminee": "Terminée"}
# Ce que dit le bouton de la prochaine action (selection.ACTIONS), sur la carte.
BOUTON_ACTION = {"preparer": "Préparer", "envoyer": "Finir et envoyer", "relancer": "J'ai relancé",
                 "entretien": "Préparer l'entretien"}

# États d'avant, gardés côté serveur le temps de pouvoir annuler : la page n'envoie qu'un jeton.
_annulations: dict[str, dict] = {}


def _jeton(avant: dict | None) -> str | None:
    if not avant:
        return None
    jeton = secrets.token_urlsafe(9)
    _annulations[jeton] = avant
    for vieux in list(_annulations)[:-50]:   # on ne garde que les 50 dernières
        del _annulations[vieux]
    return jeton


def relance_jours() -> int:
    return int(charger_config().get("candidatures", {}).get("relance_jours", 7))


def fiche_carte(f: dict) -> dict:
    """Ce que la page affiche d'une offre de la sélection."""
    entreprise = (f["entreprise"] or "Entreprise ?").strip()
    return {
        "id": f["id"], "offre_id": f["offre_id"], "entreprise": entreprise,
        "initiale": next((c for c in entreprise if c.isalnum()), "?").upper(),
        "titre": f["titre"], "lieu": presentation.lieu_court(f["lieu"]) or "", "score": f["score"],
        "etape": f["etape"], "statut": f["statut"], "situation": selection.situation(f),
        "action": f["action"], "bouton": BOUTON_ACTION.get(f["action"]),
        "a_faire": selection.ACTIONS.get(f["action"]),
        "relance_due": f["relance_due"], "lettre_prete": f["lettre_prete"],
        "trouvee_ailleurs": f["trouvee_ailleurs"], "lien": f["lien"],
    }


@app.get("/api/selection")
def api_selection():
    with connexion() as conn:
        fiches = [fiche_carte(f) for f in selection.fiches(conn)]
        a_trier = nb_a_trier(conn)
        scrap = requetes.dernier_scrap(conn)
    return {"fiches": fiches, "etapes": [{"cle": k, "nom": selection.ETAPES[k][0]} for k in selection.ETAPES],
            "a_trier": a_trier, "scrap": phrase_scrap(scrap)}


def _fiche_ou_404(conn, candidature_id: int) -> dict:
    f = selection.fiche(conn, candidature_id)
    if f is None:
        raise HTTPException(404, "Cette offre n'est pas (ou plus) dans ta sélection")
    return f


@app.get("/api/selection/{candidature_id}")
def api_fiche_selection(candidature_id: int):
    with connexion() as conn:
        f = _fiche_ou_404(conn, candidature_id)
        o = requetes.offre(conn, f["offre_id"]) if f["offre_id"] else None
    return {**fiche_carte(f), "puces": _puces(o) if o else [], "resume": f["resume"], "pourquoi": f["pourquoi"],
            "description": f["description"], "notes": f["notes"] or "",
            "date_candidature": (f["date_candidature"] or "")[:10], "date_relance": (f["date_relance"] or "")[:10],
            "date_entretien": f["date_entretien"] or "", "lettre": f["lettre_courante"] or f.get("lettre") or "",
            "analyse_faite": bool(f["analyse_faite"]), "relance_jours": relance_jours()}


class Etape(BaseModel):
    etape: str
    resultat: str = "refus"


class Dates(BaseModel):
    date_candidature: str | None = None
    date_relance: str | None = None
    date_entretien: str | None = None
    notes: str | None = None
    annonce: str | None = None


class Jeton(BaseModel):
    jeton: str


class Nouvelle(BaseModel):
    entreprise: str = ""
    poste: str = ""
    lien: str = ""
    lieu: str = ""
    annonce: str = ""
    envoyee: str | None = None   # AAAA-MM-JJ si la candidature est déjà partie


@app.post("/api/selection/{candidature_id}/etape")
def api_changer_etape(candidature_id: int, e: Etape):
    if e.etape not in selection.ETAPES:
        raise HTTPException(400, f"étape inconnue : {e.etape}")
    with connexion() as conn:
        _fiche_ou_404(conn, candidature_id)
        try:
            avant = selection.changer_etape(conn, candidature_id, e.etape, relance_jours(), e.resultat)
        except ValueError as err:
            raise HTTPException(400, str(err)) from err
    return {"jeton": _jeton(avant)}


@app.post("/api/selection/{candidature_id}/relance")
def api_relance(candidature_id: int):
    with connexion() as conn:
        _fiche_ou_404(conn, candidature_id)
        return {"jeton": _jeton(selection.noter_relance(conn, candidature_id, relance_jours()))}


@app.post("/api/selection/{candidature_id}/dates")
def api_dates(candidature_id: int, d: Dates):
    """Dates, notes, et texte de l'annonce d'une offre trouvée ailleurs : seuls les champs envoyés changent."""
    champs = d.model_dump(exclude_unset=True)
    with connexion() as conn:
        f = _fiche_ou_404(conn, candidature_id)
        avant = requetes.candidature(conn, candidature_id)
        if "annonce" in champs:
            requetes.completer_annonce(conn, f["offre_id"], champs.pop("annonce"))
        if champs.get("date_entretien") and f["etape"] != "entretien":
            selection.changer_etape(conn, candidature_id, "entretien", relance_jours())
        if champs:
            requetes.modifier_candidature(conn, candidature_id, **champs)
    return {"jeton": _jeton(avant)}


@app.post("/api/selection/{candidature_id}/retirer")
def api_retirer(candidature_id: int):
    with connexion() as conn:
        _fiche_ou_404(conn, candidature_id)
        return {"jeton": _jeton(selection.retirer(conn, candidature_id))}


@app.post("/api/selection/annuler")
def api_annuler_selection(j: Jeton):
    avant = _annulations.pop(j.jeton, None)
    if avant is None:
        raise HTTPException(410, "Trop tard pour annuler")
    with connexion() as conn:
        selection.annuler(conn, avant)
    return {"ok": True}


@app.post("/api/selection/nouvelle")
def api_nouvelle(n: Nouvelle):
    if not (n.entreprise.strip() or n.poste.strip()):
        raise HTTPException(400, "Indique au moins l'entreprise ou le poste.")
    envoyee = None
    if n.envoyee:
        try:
            envoyee = date.fromisoformat(n.envoyee)
        except ValueError as err:
            raise HTTPException(400, "Date d'envoi invalide") from err
    with connexion() as conn:
        identifiant = requetes.ajouter_a_la_main(
            conn, n.entreprise.strip() or None, n.poste.strip() or None, n.lien.strip() or None,
            "postulé" if envoyee else "à postuler", None, envoyee, relance_jours(),
            description=n.annonce, lieu=n.lieu.strip() or None)
    return {"id": identifiant}


# =========================================================================== API : journal et corbeille

COUT_DOSSIER = 0.08   # ~8 centimes par dossier Claude (analyse + lettre + quelques retouches)
MAX_CORBEILLE = 400   # au-delà, la page proposerait trop de lignes d'un coup


def nb_a_trier(conn) -> int:
    """Le nombre affiché à côté de « À trier » : comme la page, sans les « Bof » ni les « Plus tard »."""
    return sum(1 for o in requetes.offres_a_trier(conn)
               if not o["favori"] and (o["score"] is None or o["score"] >= SEUIL_BOF))


def _menu(conn) -> dict:
    """Compteurs du menu de gauche et dernier scrap, communs à toutes les pages."""
    return {"a_trier": nb_a_trier(conn), "selection": len(selection.fiches(conn)),
            "scrap": phrase_scrap(requetes.dernier_scrap(conn))}


@app.get("/api/journal")
def api_journal():
    config = charger_config()
    with connexion() as conn:
        r, d = claude.reglages(config), claude.depenses(conn, config)
        passages = requetes.passages(conn)
        details: dict[int, list[dict]] = {}
        if passages:
            ids = [p["passage_id"] for p in passages]
            for l in conn.execute(
                    f"SELECT passage_id, source, nb_offres, nb_nouvelles, erreurs, cout_usd FROM runs "
                    f"WHERE passage_id IN ({', '.join('?' * len(ids))}) AND source NOT IN "
                    f"({', '.join('?' * len(requetes.APPELS_IA))}) ORDER BY id", (*ids, *requetes.APPELS_IA)):
                details.setdefault(l["passage_id"], []).append(dict(l))
        appels = requetes.appels_ia(conn)
        total_offres = requetes.statistiques(conn)["total"]
        menu = _menu(conn)
    restant = max(r["credit_usd"] - d["total"], 0)
    return {
        **menu,
        "credit": {"total": r["credit_usd"], "depense": d["total"], "restant": restant, "mois": d["mois"],
                   "plafond_mois": r["plafond_mensuel_usd"], "plafond_total": r["plafond_total_usd"],
                   "dossiers": int(restant / COUT_DOSSIER)},
        "offres_en_base": total_offres,
        "passages": [{
            "id": p["passage_id"], "date": p["date"][:16], "auto": p["auto"], "trouvees": p["trouvees"],
            "nouvelles": p["nouvelles"], "gardees": p["gardees"], "top": p["top"], "notees": p["notees"],
            "cout": p["cout_usd"], "erreurs": p["erreurs"],
            "sources": [{"source": x["source"], "offres": x["nb_offres"], "nouvelles": x["nb_nouvelles"],
                         "erreur": x["erreurs"], "cout": x["cout_usd"]} for x in details.get(p["passage_id"], [])],
        } for p in passages],
        "appels": [{"date": (a["date_debut"] or "")[:16], "ou": "Assistant" if a["source"] == "chat" else "Fiche",
                    "modele": a["modele"], "cout": a["cout_usd"], "erreur": a["erreurs"]} for a in appels],
    }


def _ligne_corbeille(o: dict, raison: str | None, remettre: bool) -> dict:
    return {"id": o["id"], "titre": o["titre"], "entreprise": o.get("entreprise") or "Entreprise ?",
            "lieu": presentation.lieu_court(o.get("lieu")) or "", "score": o.get("score"),
            "raison": raison, "lien": o.get("lien"), "remettre": remettre}


@app.get("/api/corbeille")
def api_corbeille():
    with connexion() as conn:
        toi = requetes.offres_pas_interesse(conn)
        tri = requetes.offres_exclues(conn)
        expirees = expiration.expirees(conn)
        menu = _menu(conn)
    return {
        **menu,
        "listes": [
            {"cle": "toi", "nom": "Écartées par toi", "total": len(toi),
             "aide": "Rien n'est supprimé : tu peux remettre une offre dans À trier.",
             "offres": [_ligne_corbeille(o, o["raison"] or "Sans raison", True) for o in toi[:MAX_CORBEILLE]]},
            {"cle": "tri", "nom": "Écartées par le tri", "total": len(tri),
             "aide": "Écartées automatiquement (contrat, poste non technique, durée, lieu…) ou par l'IA. "
                     "Pour changer ce qui est écarté : Réglages › Critères.",
             "offres": [_ligne_corbeille(o, o["exclusion_prefiltre"] or o["exclusion_ia"], False)
                        for o in tri[:MAX_CORBEILLE]]},
            {"cle": "expirees", "nom": "Expirées", "total": len(expirees),
             "aide": "Plus en ligne, ou trop anciennes. Une offre signalée expirée à la main peut revenir.",
             "offres": [_ligne_corbeille(o, expiration.raison(o), o["expiration"] == "manuelle")
                        for o in expirees[:MAX_CORBEILLE]]},
        ],
    }


class Remise(BaseModel):
    offre_id: int
    liste: str


@app.post("/api/corbeille/remettre")
def api_remettre(r: Remise):
    with connexion() as conn:
        if r.liste == "toi":
            requetes.annuler_pas_interesse(conn, r.offre_id)
        elif r.liste == "expirees":
            expiration.annuler(conn, r.offre_id)
        else:
            raise HTTPException(400, "Les offres écartées par le tri se règlent dans Réglages › Critères.")
    return {"ok": True}


# =========================================================================== API : scrap

class _Scrap:
    """Un seul scrap à la fois, lancé dans un fil à part ; la page suit son avancement."""
    verrou = threading.Lock()
    en_cours = False
    lignes: list[str] = []
    bilan: list[str] | None = None
    erreur: str | None = None


class _VersLaPage(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record):
        _Scrap.lignes.append(self.format(record))
        del _Scrap.lignes[:-40]


def _faire_scrap() -> None:
    from .. import pipeline   # import tardif : la collecte charge beaucoup de modules
    journal = _VersLaPage()
    racine = logging.getLogger()
    ancien = racine.level
    racine.addHandler(journal)
    racine.setLevel(logging.INFO)
    try:
        with connexion() as conn:
            bilan = pipeline.passage_complet(conn, charger_config(), auto=False)
        _Scrap.bilan = pipeline.resume_texte(bilan)
    except Exception as e:   # le site doit le dire, pas planter
        logging.getLogger(__name__).exception("Le scrap a planté")
        _Scrap.erreur = f"{type(e).__name__} : {e}"
    finally:
        racine.removeHandler(journal)
        racine.setLevel(ancien)
        _Scrap.en_cours = False


@app.post("/api/scrap")
def api_lancer_scrap():
    with _Scrap.verrou:
        if _Scrap.en_cours:
            return {"lance": False, "en_cours": True}
        _Scrap.en_cours, _Scrap.lignes, _Scrap.bilan, _Scrap.erreur = True, [], None, None
    threading.Thread(target=_faire_scrap, name="scrap", daemon=True).start()
    return {"lance": True, "en_cours": True}


@app.get("/api/scrap")
def api_etat_scrap():
    return {"en_cours": _Scrap.en_cours, "derniere_ligne": _Scrap.lignes[-1] if _Scrap.lignes else None,
            "bilan": _Scrap.bilan, "erreur": _Scrap.erreur}
