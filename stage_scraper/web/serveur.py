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
- GET  /api/selection/{id}/dossier            analyse face au CV, conseils, lettre (versions), conversation
- POST /api/selection/{id}/dossier/preparer | /analyser | /message | /lettre | /version   (IA : Claude ou Gemini)
- GET  /api/selection/{id}/dossier/lettre.docx | lettre.txt   la lettre signée, à télécharger
- GET  /api/assistant  /  POST /api/assistant {question}  /  POST /api/assistant/effacer   chat sur les offres (Gemini)
- GET  /api/journal            passages (scraps), coût de l'IA, crédit Claude restant
- GET  /api/corbeille          offres écartées (par BAP, par le tri) et expirées
- POST /api/corbeille/remettre {offre_id, liste} : remet une offre dans À trier
- GET  /api/reglages  /  POST /api/reglages   critères, entreprises suivies, mails (écrit config.yaml)
- GET  /api/reglages/apercu/{alerte|recap}     aperçu d'un mail ; POST /api/reglages/mail-test
- GET  /api/profil  /  POST /api/profil {valeurs}   profil de recherche (critères, domaines, entreprises...)
- POST /api/profil/message {texte}  /  POST /api/profil/effacer   le modifier en conversation (agent Gemini)
- POST /api/profil/a-revoir/ignorer {cle}   « Non » à une proposition « À revoir » (elle ne revient plus)
- POST /api/reglages/retrier                   refait le tri de toutes les offres
- GET|POST /api/reglages/documents/{cv|modele} texte anonymisé / dépôt du fichier (corps brut)
- GET  /api/entretien  /  POST /api/entretien/question {id, valeurs}   entretien d'accueil (page /bienvenue)
- POST /api/entretien/repondre {question, choix | texte, valeurs}  /  /apercu {valeurs}  /  /terminer {valeurs}
Mode comptes (python site_web.py --comptes) :
- GET  /api/compte                    qui est connecté (et s'il faut créer le premier compte)
- POST /api/compte/connexion {nom, mot_de_passe}  /  /inscription {nom, mot_de_passe, code}  /  /deconnexion
- POST /api/compte/cle {cle: gemini|claude, valeur}   la clé IA de son compte (amis)
- POST /api/compte/mot-de-passe {ancien, nouveau}
- POST /api/compte/inviter  /  /supprimer {nom}       (BAP seulement)
"""
import hashlib
import io
import json
import logging
import os
import re
import secrets
import threading
import contextvars
from contextlib import asynccontextmanager, closing
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import langue
from .. import a_revoir, agent_profil, chat_offres, claude, comptes, db, decisions, dossier, entretien, expiration, notifications, presentation, profil, reglages, requetes, selection
from .. import cv as module_cv
from .. import config as config_module
from ..config import CHEMIN_CONFIG, COMPTE, RACINE, charger_config, chemin_projet, secret

STATIQUE = Path(__file__).parent / "statique"
SEUIL_BOF = 5



@asynccontextmanager
async def _demarrage(_app):
    with connexion() as conn:   # crée ou met à jour les tables avant la première page
        db.initialiser(conn)
    yield


app = FastAPI(title="Stage Scraper", docs_url=None, redoc_url=None, lifespan=_demarrage)
app.mount("/statique", StaticFiles(directory=STATIQUE), name="statique")


@app.middleware("http")
async def _toujours_a_jour(request: Request, appel_suivant):
    """CSS, JS, images : le navigateur redemande toujours si le fichier a changé (réponse 304 sinon, très légère).
    Sans ça, Chrome garde un vieux site.css pendant des heures et les changements de style n'apparaissent pas."""
    reponse = await appel_suivant(request)
    if request.url.path.startswith("/statique/"):
        reponse.headers.setdefault("Cache-Control", "no-cache")
    return reponse


# =========================================================================== comptes

COOKIE_SESSION = "session"
# Ce qu'on peut ouvrir sans être connecté : l'accueil (qui sert aussi de page de connexion), les fichiers du site.
_PUBLIC = ("/statique/", "/api/compte")


def mode_comptes() -> bool:
    """Site partagé (python site_web.py --comptes) : il faut se connecter, chacun a ses données."""
    return os.getenv("STAGE_SCRAPER_COMPTES") == "1"


def en_ligne() -> bool:
    """Site sur Internet (python site_web.py --en-ligne) : le premier compte (admin) ne se crée jamais depuis le
    site, seulement sur le serveur (python site_web.py --creer-admin). Sinon, si comptes.db était perdu, le premier
    inconnu à ouvrir la page deviendrait admin."""
    return os.getenv("STAGE_SCRAPER_EN_LIGNE") == "1"


@app.middleware("http")
async def _compte_de_la_requete(request: Request, appel_suivant):
    """En mode comptes : retrouve la personne connectée (cookie de session) et fait travailler tout le code
    pour elle (sa base, ses réglages, ses clés). Sans session : l'accueil, pour se connecter."""
    if not mode_comptes():
        return await appel_suivant(request)
    chemin = request.url.path
    c = comptes.session(request.cookies.get(COOKIE_SESSION))
    if c is None and chemin != "/" and not chemin.startswith(_PUBLIC):
        if chemin.startswith("/api/"):
            return Response(json.dumps({"detail": "Connecte-toi d'abord."}), status_code=401, media_type="application/json")
        return RedirectResponse("/", status_code=303)
    jeton = COMPTE.set(c)
    try:
        return await appel_suivant(request)
    finally:
        COMPTE.reset(jeton)


_STATIQUE_DANS_PAGE = re.compile(r"(/statique/[\w/.-]+\.(?:css|js))(?=[\"'])")


def _version(chemin: Path) -> str:
    """Empreinte courte du contenu : elle change dès que le fichier change."""
    return hashlib.md5(chemin.read_bytes()).hexdigest()[:10]


def versionner(page: str) -> str:
    """Donne à chaque CSS/JS une adresse qui change avec son contenu (site.css?v=…) : une vieille copie gardée par
    le navigateur ne peut plus servir. L'« import map » fait de même pour les modules JS importés entre eux."""
    def avec_version(m):
        fichier = STATIQUE / m.group(1).removeprefix("/statique/")
        return f"{m.group(1)}?v={_version(fichier)}" if fichier.is_file() else m.group(1)

    page = _STATIQUE_DANS_PAGE.sub(avec_version, page)
    modules = {f"/statique/js/{f.name}": f"/statique/js/{f.name}?v={_version(f)}" for f in sorted((STATIQUE / "js").glob("*.js"))}
    carte = f'<script type="importmap">{json.dumps({"imports": modules})}</script>'
    return page.replace("<head>", "<head>\n" + carte, 1)


# =========================================================================== base

def _compte_ami():
    """Le compte connecté s'il a son propre dossier (un ami), sinon None (BAP, ou site sans comptes)."""
    c = COMPTE.get()
    return c if c is not None and c.dossier is not None else None


def config_de_bap() -> Path:
    """config.yaml, sauf si STAGE_SCRAPER_CONFIG en désigne une copie (tests : ne jamais toucher au vrai)."""
    autre = os.getenv("STAGE_SCRAPER_CONFIG")
    return Path(autre) if autre else CHEMIN_CONFIG


def base_de_bap() -> Path:
    """Base de config.yaml, sauf si la variable STAGE_SCRAPER_BASE en désigne une autre (tests, essais)."""
    autre = os.getenv("STAGE_SCRAPER_BASE")
    if autre:
        return Path(autre)
    general = Path(charger_config(config_de_bap())["general"]["base_de_donnees"])
    return general if general.is_absolute() else RACINE / general


def chemin_base() -> Path:
    """La base de la personne connectée (un ami : celle de son dossier ; sinon celle de BAP)."""
    ami = _compte_ami()
    return ami.dossier / "stages.db" if ami else base_de_bap()


def chemin_config() -> Path:
    ami = _compte_ami()
    return ami.config if ami else config_de_bap()


def config_courante() -> dict:
    return charger_config(chemin_config())


_bases_pretes: set[str] = set()


def connexion():
    chemin = chemin_base()
    conn = db.connecter(chemin)
    if str(chemin) not in _bases_pretes:   # base d'un compte ouverte pour la première fois : tables à jour
        db.initialiser(conn)
        _bases_pretes.add(str(chemin))
    return closing(conn)


# =========================================================================== pages

@app.get("/", include_in_schema=False)
def page_accueil(request: Request):
    page = (STATIQUE / "accueil.html").read_text(encoding="utf-8")
    page = versionner(langue.preparer_page(page, langue.langue_de(request)))
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})


def page_appli(nom: str, request: Request | None = None) -> HTMLResponse:
    """Page de l'appli avec le menu de gauche (un seul fichier, _menu.html), la page en cours marquée."""
    page = (STATIQUE / f"{nom}.html").read_text(encoding="utf-8")
    menu = (STATIQUE / "_menu.html").read_text(encoding="utf-8")
    lien = f'<a href="/{nom}">'
    menu = menu.replace(lien, f'<a class="on" href="/{nom}" aria-current="page">')
    page = versionner(langue.preparer_page(page.replace("<!-- menu -->", menu), langue.langue_de(request)))
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})


@app.get("/bienvenue", include_in_schema=False)
def page_bienvenue(request: Request):
    """L'entretien d'accueil : une page à part (sans le menu), une question à la fois."""
    page = (STATIQUE / "entretien.html").read_text(encoding="utf-8")
    page = versionner(langue.preparer_page(page, langue.langue_de(request)))
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})


@app.get("/a-trier", include_in_schema=False)
def page_a_trier(request: Request):
    # Profil jamais configuré : l'entretien d'accueil d'abord (sauf si l'étudiant a dit « Plus tard » dans ce navigateur).
    if request.cookies.get("entretien") != "plus_tard" and entretien.a_faire(reglages.lire(chemin_config())):
        return RedirectResponse("/bienvenue", status_code=303)
    return page_appli("a-trier", request)


@app.get("/selection", include_in_schema=False)
def page_selection(request: Request):
    return page_appli("selection", request)


@app.get("/journal", include_in_schema=False)
def page_journal(request: Request):
    return page_appli("journal", request)


@app.get("/corbeille", include_in_schema=False)
def page_corbeille(request: Request):
    return page_appli("corbeille", request)


@app.get("/profil", include_in_schema=False)
def page_profil(request: Request):
    return page_appli("profil", request)


@app.get("/assistant", include_in_schema=False)
def page_assistant(request: Request):
    return page_appli("assistant", request)


@app.get("/reglages", include_in_schema=False)
def page_reglages(request: Request):
    return page_appli("reglages", request)


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
    return int(config_courante().get("candidatures", {}).get("relance_jours", 7))


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


# =========================================================================== API : dossier de candidature

# Client d'IA imposé (tests : un faux client, pour ne jamais appeler ni payer une vraie IA). None = les vrais.
CLIENT_IA = None
DEMANDE_PREMIER_JET = "Rédige une première version de la lettre."
CENTIMES = {"modeles": 4, "modeles_premier_jet": 4}   # mesuré : ~3,6 c par appel Sonnet (novembre 2026)
NOMS_MODELES = {"claude-sonnet-5-5": "Claude Sonnet", "claude-haiku-5-5": "Claude Haiku"}


def libelle_appel(donnees: dict) -> str | None:
    """« Claude Sonnet · 0,61 centime » ou « Gemini (gratuit) » sous une réponse de l'IA."""
    modele = donnees.get("modele")
    if not modele:
        return None
    if not claude.est_claude(modele):
        return "Gemini (gratuit)"
    centimes = (donnees.get("cout") or 0) * 100
    return f"{NOMS_MODELES.get(modele, modele)} · {centimes:.2f} centime".replace(".", ",")


def prix(conn, config: dict, cle_modeles: str, centimes: float) -> str:
    """« ≈ 4 c » si Claude répondra, « gratuit, Gemini » s'il prend le relais (plafond, pas de clé, config)."""
    modeles = config.get("dossier", {}).get(cle_modeles) or dossier.MODELES_PAR_DEFAUT
    if claude.blocage(conn, config) or not claude.est_claude(modeles[0]):
        return "gratuit, Gemini"
    return f"≈ {centimes:g} c".replace(".", ",")


def _dossier_de(conn, candidature_id: int) -> tuple[dict, dict]:
    f = _fiche_ou_404(conn, candidature_id)
    return f, dossier.ouvrir(conn, f["offre_id"])


def _etat_dossier(conn, config: dict, f: dict, d: dict) -> dict:
    courante = dossier.version_courante(conn, d)
    toutes = dossier.versions(conn, d["id"])
    blocage = claude.blocage(conn, config)
    return {
        "cv_present": bool(module_cv.texte_cv(config)),
        "claude_en_pause": blocage,
        "etape": f["etape"],
        "prix": {"analyse": prix(conn, config, "modeles", CENTIMES["modeles"]),
                 "premier_jet": prix(conn, config, "modeles_premier_jet", CENTIMES["modeles_premier_jet"]),
                 "retouche": prix(conn, config, "modeles_retouche", 0.1)},
        "diagnostic": d.get("diagnostic"),
        "a_refaire": dossier.a_refaire(d, config),
        "date_diagnostic": (d.get("date_diagnostic") or "")[:16],
        "modele_diagnostic": d.get("modele_diagnostic"),
        "lettre": None if not courante else {
            "numero": courante["numero"], "total": len(toutes), "texte": courante["texte"],
            "auteur": "toi" if courante["modele"] is None else "l'IA", "alertes": courante["alertes"],
            "figee": dossier.lettre_figee(conn, d)},
        "versions": [{"numero": v["numero"], "date": (v["date"] or "")[5:16], "auteur": "toi" if v["modele"] is None else "IA",
                      "demande": (v["demande"] or "")[:120]} for v in reversed(toutes)],
        "messages": [{"role": m["role"], "texte": m["texte"], "version": m["donnees"].get("version"),
                      "detail": libelle_appel(m["donnees"]) if m["role"] == "assistant" else None}
                     for m in dossier.messages(conn, dossier.conversation_de(d))],
    }


@app.get("/api/selection/{candidature_id}/dossier")
def api_dossier(candidature_id: int):
    config = config_courante()
    with connexion() as conn:
        f, d = _dossier_de(conn, candidature_id)
        return _etat_dossier(conn, config, f, d)


class Preparation(BaseModel):
    analyse: bool = True
    lettre: bool = True


class Message(BaseModel):
    texte: str
    lettre_actuelle: str | None = None   # ce que BAP a tapé dans la lettre, gardé avant la retouche


class Lettre(BaseModel):
    texte: str


class Version(BaseModel):
    numero: int


def _ia(action):
    """Lance un appel d'IA ; une erreur affichable devient une réponse 400 avec son texte."""
    try:
        return action()
    except dossier.DossierImpossible as e:
        raise HTTPException(400, f"L'IA n'a pas pu terminer : {e}") from e


@app.post("/api/selection/{candidature_id}/dossier/preparer")
def api_preparer(candidature_id: int, p: Preparation):
    """Analyse puis premier jet : seulement ce qui manque (et ce qui est demandé)."""
    config = config_courante()
    with connexion() as conn:
        f, d = _dossier_de(conn, candidature_id)
        if p.analyse and not d.get("diagnostic"):
            _ia(lambda: dossier.diagnostiquer(conn, config, d, client=CLIENT_IA))
        if p.lettre and not dossier.version_courante(conn, d):
            _ia(lambda: dossier.discuter(conn, config, d, DEMANDE_PREMIER_JET, client=CLIENT_IA))
        return _etat_dossier(conn, config, f, d)


@app.post("/api/selection/{candidature_id}/dossier/analyser")
def api_analyser(candidature_id: int):
    """Refaire l'analyse (CV ou offre changés) : remplace l'ancienne."""
    config = config_courante()
    with connexion() as conn:
        f, d = _dossier_de(conn, candidature_id)
        _ia(lambda: dossier.diagnostiquer(conn, config, d, client=CLIENT_IA))
        return _etat_dossier(conn, config, f, d)


@app.post("/api/selection/{candidature_id}/dossier/message")
def api_message(candidature_id: int, m: Message):
    texte = m.texte.strip()
    if not texte:
        raise HTTPException(400, "Message vide")
    config = config_courante()
    with connexion() as conn:
        f, d = _dossier_de(conn, candidature_id)
        if m.lettre_actuelle is not None:
            dossier.modifier_a_la_main(conn, d, m.lettre_actuelle)
        _ia(lambda: dossier.discuter(conn, config, d, texte, client=CLIENT_IA))
        return _etat_dossier(conn, config, f, d)


@app.post("/api/selection/{candidature_id}/dossier/lettre")
def api_lettre(candidature_id: int, lettre: Lettre):
    """Ce que BAP a tapé dans la lettre (plusieurs modifications d'affilée restent une seule version)."""
    config = config_courante()
    with connexion() as conn:
        f, d = _dossier_de(conn, candidature_id)
        change = dossier.modifier_a_la_main(conn, d, lettre.texte)
        return {"change": change, **_etat_dossier(conn, config, f, d)}


@app.post("/api/selection/{candidature_id}/dossier/version")
def api_version(candidature_id: int, v: Version):
    config = config_courante()
    with connexion() as conn:
        f, d = _dossier_de(conn, candidature_id)
        if not any(x["numero"] == v.numero for x in dossier.versions(conn, d["id"])):
            raise HTTPException(404, "Version introuvable")
        dossier.choisir_version(conn, d, v.numero)
        return _etat_dossier(conn, config, f, d)


@app.get("/api/selection/{candidature_id}/dossier/lettre.{format_}")
def api_telecharger_lettre(candidature_id: int, format_: str):
    """La lettre signée (ton vrai nom à la place de [Prénom Nom]) : elle ne quitte pas l'ordinateur."""
    if format_ not in ("docx", "txt"):
        raise HTTPException(404, "Format inconnu")
    config = config_courante()
    with connexion() as conn:
        f, d = _dossier_de(conn, candidature_id)
        courante = dossier.version_courante(conn, d)
    if not courante:
        raise HTTPException(404, "Pas encore de lettre")
    signee = module_cv.signer(courante["texte"], config)
    nom = "".join(c if c.isalnum() else "_" for c in (f["entreprise"] or "offre")).strip("_") or "offre"
    if format_ == "docx":
        contenu, type_ = dossier.exporter_docx(signee), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        contenu, type_ = signee.encode("utf-8"), "text/plain; charset=utf-8"
    return Response(contenu, media_type=type_,
                    headers={"Content-Disposition": f'attachment; filename="Lettre_{nom}.{format_}"'})


# =========================================================================== API : assistant

CONVERSATION_ASSISTANT = "assistant"   # même conversation que l'appli Streamlit


def _etat_offre(conn, o: dict) -> dict:
    """Où en est l'offre pour BAP : dans Ma sélection (avec la fiche), écartée, ou encore à trier."""
    c = requetes.candidature_de(conn, o["id"])
    if c:
        return {"etat": "selection", "candidature_id": c["id"]}
    return {"etat": "ecartee" if o["pas_interesse"] else "a_trier", "candidature_id": None}


def _messages_assistant(conn) -> list[dict]:
    """La conversation gardée en base, avec les offres proposées (relues : leur état a pu changer)."""
    sortie = []
    for m in dossier.messages(conn, CONVERSATION_ASSISTANT):
        donnees = m["donnees"]
        raisons = donnees.get("raisons") or {}
        offres = []
        for oid in donnees.get("ids") or []:
            o = requetes.offre(conn, oid)
            if o:
                offres.append({**carte(o), **_etat_offre(conn, o), "raison": raisons.get(str(oid), "")})
        sortie.append({"role": m["role"], "texte": m["texte"], "lues": donnees.get("lues") or [], "offres": offres,
                       "ids": donnees.get("ids") or []})
    return sortie


@app.get("/api/assistant")
def api_assistant():
    with connexion() as conn:
        return {"messages": _messages_assistant(conn), "nb_offres": len(requetes.offres_visibles(conn)),
                "menu": _menu(conn)}


class Question(BaseModel):
    question: str


@app.post("/api/assistant")
def api_assistant_demander(q: Question):
    """Une question à l'assistant (Gemini, gratuit). Elle n'est gardée que s'il a répondu."""
    question = q.question.strip()
    if not question:
        raise HTTPException(400, "Question vide")
    if len(question) > 2000:
        raise HTTPException(400, "Question trop longue (2 000 caractères au plus)")
    config = config_courante()
    with connexion() as conn:
        historique = [{"role": m["role"], "texte": m["texte"], "ids": m["ids"]} for m in _messages_assistant(conn)]
        try:
            r = chat_offres.demander(conn, config, question, historique, client=CLIENT_IA)
        except chat_offres.ChatImpossible as e:
            raise HTTPException(400, f"Pas de réponse : {e}") from e
        dossier.ajouter_message(conn, CONVERSATION_ASSISTANT, "user", question)
        dossier.ajouter_message(conn, CONVERSATION_ASSISTANT, "assistant", r["reponse"] or "…", {
            "lues": r["lues"], "ids": [o["id"] for o in r["offres"]],
            "raisons": {str(o["id"]): o["raison"] for o in r["offres"]}})
        return {"messages": _messages_assistant(conn), "nb_offres": len(requetes.offres_visibles(conn))}


@app.post("/api/assistant/effacer")
def api_assistant_effacer():
    """Nouvelle conversation (les offres ne bougent pas)."""
    with connexion() as conn:
        dossier.effacer_conversation(conn, CONVERSATION_ASSISTANT)
    return {"messages": []}


# =========================================================================== API : profil

CONVERSATION_PROFIL = "profil"


def _messages_profil(conn) -> list[dict]:
    return [{"role": m["role"], "texte": m["texte"], "changements": m["donnees"].get("changements") or [],
             "suggestions": m["donnees"].get("suggestions") or [], "refus": m["donnees"].get("refus") or [],
             "erreur": bool(m["donnees"].get("erreur"))}
            for m in dossier.messages(conn, CONVERSATION_PROFIL)]


def _etat_profil(request: Request | None = None) -> dict:
    """Le profil, ses alertes et les propositions « À revoir » (tirées des offres écartées)."""
    p = profil.lire(reglages.lire(chemin_config()))
    with connexion() as conn:
        propositions = a_revoir.propositions(conn, p, langue.langue_de(request) if request else "fr")
    return {"profil": p, "alertes": profil.alertes(p), "a_revoir": propositions}


@app.get("/api/profil")
def api_profil(request: Request):
    with connexion() as conn:
        messages, menu = _messages_profil(conn), _menu(conn)
    return {**_etat_profil(request), "messages": messages, "menu": menu,
            "champs": {c: {"libelle": l, "type": t} for c, (l, t) in profil.CHAMPS.items()},
            "champs_tri": sorted(profil.CHAMPS_TRI), "departements": profil.DEPARTEMENTS,
            "groupes": profil.GROUPES, "contrats": profil.CONTRATS, "six_mois": profil.SIX_MOIS,
            "ia_prete": CLIENT_IA is not None or bool(secret("GEMINI_API_KEY"))}


class ValeursProfil(BaseModel):
    valeurs: dict


@app.post("/api/profil")
def api_profil_modifier(v: ValeursProfil, request: Request):
    """Modification à la main (ou annulation : la page renvoie les anciennes valeurs)."""
    donnees = reglages.lire(chemin_config())
    try:
        changements = profil.appliquer(donnees, v.valeurs)
    except profil.ProfilInvalide as e:
        raise HTTPException(400, str(e)) from e
    if changements:
        reglages.ecrire(donnees, chemin_config())
    return {**_etat_profil(request), "changements": changements}


class CleARevoir(BaseModel):
    cle: str


@app.post("/api/profil/a-revoir/ignorer")
def api_a_revoir_ignorer(c: CleARevoir, request: Request):
    with connexion() as conn:
        a_revoir.ignorer(conn, c.cle)
    return _etat_profil(request)


class MessageProfil(BaseModel):
    texte: str


@app.post("/api/profil/message")
def api_profil_message(m: MessageProfil, request: Request):
    """« Accepte aussi les stages de 6 mois » : l'agent met le profil à jour (Gemini, gratuit)."""
    texte = m.texte.strip()
    if not texte:
        raise HTTPException(400, "Message vide")
    if len(texte) > 1500:
        raise HTTPException(400, "Message trop long (1 500 caractères au plus)")
    with connexion() as conn:
        historique = [{"role": x["role"], "texte": x["texte"],
                       "changements": [f"{c['libelle']} : {c['apres']}" for c in x["changements"]]}
                      for x in _messages_profil(conn)]
        try:
            r = agent_profil.demander(conn, chemin_config(), config_courante(), texte, historique, client=CLIENT_IA)
        except agent_profil.AgentImpossible as e:
            raise HTTPException(400, f"Pas de réponse : {e}") from e
        dossier.ajouter_message(conn, CONVERSATION_PROFIL, "user", texte)
        dossier.ajouter_message(conn, CONVERSATION_PROFIL, "assistant", r["reponse"] or "…", {
            "changements": r["changements"], "suggestions": r["suggestions"], "refus": r["refus"],
            "erreur": r["erreur"]})
        messages = _messages_profil(conn)
        propositions = a_revoir.propositions(conn, r["profil"], langue.langue_de(request))
    return {"profil": r["profil"], "alertes": r["alertes"], "changements": r["changements"], "messages": messages,
            "a_revoir": propositions}


@app.post("/api/profil/effacer")
def api_profil_effacer():
    """Nouvelle conversation (le profil ne bouge pas)."""
    with connexion() as conn:
        dossier.effacer_conversation(conn, CONVERSATION_PROFIL)
    return {"messages": []}


# =========================================================================== API : entretien d'accueil

class QuestionEntretien(BaseModel):
    id: str
    valeurs: dict = {}


class ReponseEntretien(BaseModel):
    question: str
    choix: dict[str, list[str]] = {}
    texte: str = ""
    valeurs: dict = {}


class BrouillonEntretien(BaseModel):
    valeurs: dict = {}


def _entretien(action):
    """Une réponse incohérente ou inconnue devient une erreur 400 lisible (rien n'est écrit)."""
    try:
        return action()
    except (profil.ProfilInvalide, entretien.EntretienImpossible) as e:
        raise HTTPException(400, str(e)[:1].upper() + str(e)[1:]) from e


@app.get("/api/entretien")
def api_entretien():
    return {"questions": entretien.liste_questions(), "neuf": entretien.a_faire(reglages.lire(chemin_config())),
            "ia_prete": CLIENT_IA is not None or bool(secret("GEMINI_API_KEY"))}


@app.post("/api/entretien/question")
def api_entretien_question(q: QuestionEntretien):
    return _entretien(lambda: entretien.question(q.id, reglages.lire(chemin_config()), q.valeurs))


@app.post("/api/entretien/repondre")
def api_entretien_repondre(r: ReponseEntretien, request: Request):
    """Une réponse en puces (le code la traduit) ou avec ses mots (Gemini, sinon lecture simple). Rien n'est écrit."""
    if len(r.texte) > 1500:
        raise HTTPException(400, "Réponse trop longue (1 500 caractères au plus)")
    with connexion() as conn:
        return _entretien(lambda: entretien.repondre(conn, chemin_config(), config_courante(), r.question, r.choix,
                                                     r.texte, r.valeurs, langue.langue_de(request), client=CLIENT_IA))


@app.post("/api/entretien/apercu")
def api_entretien_apercu(b: BrouillonEntretien, request: Request):
    return _entretien(lambda: entretien.apercu(chemin_config(), b.valeurs, langue.langue_de(request)))


@app.post("/api/entretien/terminer")
def api_entretien_terminer(b: BrouillonEntretien):
    """« C'est bon » : le profil est écrit, puis les offres déjà là sont retriées si les critères ont changé."""
    r = _entretien(lambda: entretien.terminer(chemin_config(), b.valeurs))
    retriees = None
    if any(c["champ"] in profil.CHAMPS_TRI for c in r["changements"]):
        from .. import pipeline
        with connexion() as conn:
            retriees = pipeline.retrier(conn, config_courante()).get("traitees", 0)
    return {"changements": r["changements"], "profil": r["profil"], "retriees": retriees}


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
    config = config_courante()
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
        "appels": [{"date": (a["date_debut"] or "")[:16], "ou": {"chat": "Assistant", "profil": "Mon profil", "accueil": "Entretien d'accueil"}.get(a["source"], "Fiche"),
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
                     "Pour changer ce qui est écarté : Mon profil.",
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
            raise HTTPException(400, "Les offres écartées par le tri se règlent dans Mon profil.")
    return {"ok": True}


# =========================================================================== API : réglages

GROUPES = {"priorite_absolue": "Priorité absolue", "grand_groupe": "Grand groupe", "scale_up": "Scale-up",
           "ecosysteme": "Écosystème"}
OUTILS = {"": "Aucun", "ashby": "Ashby", "workday": "Workday"}
DOCUMENTS = {"cv": module_cv.chemin_cv, "modele": module_cv.chemin_modele_lettre}
TAILLE_MAX_DOCUMENT = 8 * 1024 * 1024


@app.get("/api/reglages")
def api_reglages():
    donnees = reglages.lire(chemin_config())
    config = config_courante()
    _, mot_de_passe, destinataire = notifications.adresses()
    texte_cv = module_cv.texte_cv(config)
    with connexion() as conn:
        alerte, recap = notifications.offres_alerte(conn, config), notifications.offres_recap(conn, config)
        menu = _menu(conn)
    return {
        **menu,
        "criteres": {"anciennete_max_jours": int(donnees["general"]["anciennete_max_jours"]),
                     "contrats": list(donnees["exclusions"]["contrats"]),
                     "postes": list(donnees["exclusions"]["postes"]),
                     "niveaux": list(donnees["exclusions"]["niveaux"]),
                     "entreprises_suivies": reglages.entreprises_en_lignes(donnees)},
        "groupes": GROUPES, "outils": OUTILS,
        "mails": {"alerte_seuil_score": int(donnees["notifications"]["alerte_seuil_score"]),
                  "envoi_actif": bool(donnees["notifications"].get("envoi_actif")),
                  "destinataire": destinataire, "pret": bool(destinataire and mot_de_passe),
                  "en_attente": {"alerte": len(alerte), "recap": len(recap)}},
        "documents": {"cv": texte_cv is not None, "modele": module_cv.modele_lettre(config) is not None,
                      "nom_masque": texte_cv is None or module_cv.NOM_MASQUE in texte_cv},
    }


@app.post("/api/reglages")
def api_enregistrer_reglages(modifications: dict):
    permis = {"anciennete_max_jours", "alerte_seuil_score", "envoi_actif", "contrats", "postes", "niveaux",
              "entreprises_suivies"}
    inconnus = set(modifications) - permis
    if inconnus:
        raise HTTPException(400, f"Réglage inconnu : {', '.join(sorted(inconnus))}")
    for cle in ("anciennete_max_jours", "alerte_seuil_score"):
        if cle in modifications:
            try:
                valeur = int(modifications[cle])
            except (TypeError, ValueError) as err:
                raise HTTPException(400, f"{cle} doit être un nombre") from err
            bornes = (1, 365) if cle == "anciennete_max_jours" else (0, 10)
            if not bornes[0] <= valeur <= bornes[1]:
                raise HTTPException(400, f"{cle} doit être entre {bornes[0]} et {bornes[1]}")
    for cle in ("contrats", "postes", "niveaux"):
        if cle in modifications:
            modifications[cle] = reglages.texte_en_liste("\n".join(str(x) for x in modifications[cle]))
    for e in modifications.get("entreprises_suivies", []):
        if e.get("groupe") and e["groupe"] not in GROUPES:
            raise HTTPException(400, f"Groupe inconnu : {e['groupe']}")
        if e.get("outil") and e["outil"] not in OUTILS:
            raise HTTPException(400, f"Outil inconnu : {e['outil']}")
    donnees = reglages.lire(chemin_config())
    changements = reglages.appliquer(donnees, modifications)
    if changements:
        reglages.ecrire(donnees, chemin_config())
    return {"changements": changements}


@app.get("/api/reglages/apercu/{type_mail}")
def api_apercu(type_mail: str):
    if type_mail not in ("alerte", "recap"):
        raise HTTPException(404, "Aperçu inconnu")
    config = config_courante()
    with connexion() as conn:
        offres = (notifications.offres_alerte if type_mail == "alerte" else notifications.offres_recap)(conn, config)
    if not offres:
        return {"sujet": None, "html": None}
    sujet, _, page = notifications.construire(type_mail, offres, config)
    return {"sujet": sujet, "html": page}


@app.post("/api/reglages/mail-test")
def api_mail_test():
    try:
        notifications.mail_de_test()
    except RuntimeError as e:
        raise HTTPException(400, f"Mail de test non envoyé : {e}") from e
    return {"ok": True}


@app.post("/api/reglages/retrier")
def api_retrier():
    from .. import pipeline
    with connexion() as conn:
        bilan = pipeline.retrier(conn, config_courante())
    return {"texte": pipeline.resume_tri(bilan).strip()}


@app.get("/api/reglages/documents/{nom}")
def api_document(nom: str):
    """Ce que l'IA reçoit : le texte anonymisé du CV ou de la lettre modèle."""
    if nom not in DOCUMENTS:
        raise HTTPException(404, "Document inconnu")
    config = config_courante()
    return {"texte": module_cv.texte_cv(config) if nom == "cv" else module_cv.modele_lettre(config)}


@app.post("/api/reglages/documents/{nom}")
async def api_deposer_document(nom: str, request: Request, fichier: str = ""):
    """Dépôt du CV (PDF) ou de la lettre modèle (.txt, .docx) : le fichier arrive tel quel dans le corps."""
    if nom not in DOCUMENTS:
        raise HTTPException(404, "Document inconnu")
    contenu = await request.body()
    if not contenu or len(contenu) > TAILLE_MAX_DOCUMENT:
        raise HTTPException(400, "Fichier vide ou trop gros (8 Mo au plus)")
    extension = Path(fichier).suffix.lower()
    if nom == "cv":
        if not contenu.startswith(b"%PDF"):
            raise HTTPException(400, "Le CV doit être un PDF")
    elif extension == ".docx":
        from docx import Document
        contenu = "\n".join(p.text for p in Document(io.BytesIO(contenu)).paragraphs).encode("utf-8")
    elif extension not in (".txt", ""):
        raise HTTPException(400, "La lettre modèle doit être un .txt ou un .docx")
    chemin = DOCUMENTS[nom](config_courante())
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)
    return {"ok": True}


# =========================================================================== API : scrap

class _Scrap:
    """Un scrap à la fois par compte, lancé dans un fil à part ; la page suit son avancement."""
    def __init__(self, nom: str):
        self.fil = f"scrap-{nom}"
        self.en_cours = False
        self.lignes: list[str] = []
        self.bilan: list[str] | None = None
        self.erreur: str | None = None


_scraps: dict[str, _Scrap] = {}
_verrou_scrap = threading.Lock()


def _scrap_du_compte() -> _Scrap:
    c = COMPTE.get()
    nom = c.nom if c else ""
    with _verrou_scrap:
        return _scraps.setdefault(nom, _Scrap(nom))


class _VersLaPage(logging.Handler):
    """Les lignes du journal écrites par le fil de CE scrap (deux comptes peuvent scraper en même temps)."""
    def __init__(self, etat: _Scrap):
        super().__init__(level=logging.INFO)
        self.etat = etat
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record):
        if record.threadName == self.etat.fil:
            self.etat.lignes.append(self.format(record))
            del self.etat.lignes[:-40]


def _faire_scrap(etat: _Scrap) -> None:
    from .. import pipeline   # import tardif : la collecte charge beaucoup de modules
    journal = _VersLaPage(etat)
    racine = logging.getLogger()
    ancien = racine.level
    racine.addHandler(journal)
    racine.setLevel(logging.INFO)
    try:
        # Un ami ne scrape pas les sites : il reprend les offres collectées par BAP, et les note avec sa clé.
        commune = base_de_bap() if _compte_ami() else None
        with connexion() as conn:
            bilan = pipeline.passage_complet(conn, config_courante(), auto=False, commune=commune)
        etat.bilan = pipeline.resume_texte(bilan)
    except Exception as e:   # le site doit le dire, pas planter
        logging.getLogger(__name__).exception("Le scrap a planté")
        etat.erreur = f"{type(e).__name__} : {e}"
    finally:
        racine.removeHandler(journal)
        racine.setLevel(ancien)
        etat.en_cours = False


@app.post("/api/scrap")
def api_lancer_scrap():
    etat = _scrap_du_compte()
    with _verrou_scrap:
        if etat.en_cours:
            return {"lance": False, "en_cours": True}
        etat.en_cours, etat.lignes, etat.bilan, etat.erreur = True, [], None, None
    contexte = contextvars.copy_context()   # le fil garde le compte de la requête (sa base, ses clés)
    threading.Thread(target=contexte.run, args=(_faire_scrap, etat), name=etat.fil, daemon=True).start()
    return {"lance": True, "en_cours": True}


@app.get("/api/scrap")
def api_etat_scrap():
    etat = _scrap_du_compte()
    return {"en_cours": etat.en_cours, "derniere_ligne": etat.lignes[-1] if etat.lignes else None,
            "bilan": etat.bilan, "erreur": etat.erreur}


# =========================================================================== API : comptes

class CorpsConnexion(BaseModel):
    nom: str
    mot_de_passe: str
    code: str | None = None


class CorpsCle(BaseModel):
    cle: str
    valeur: str = ""


class CorpsMotDePasse(BaseModel):
    ancien: str
    nouveau: str


class CorpsNom(BaseModel):
    nom: str


def _avec_session(reponse: dict, jeton: str, request: Request) -> Response:
    r = Response(json.dumps(reponse), media_type="application/json")
    r.set_cookie(COOKIE_SESSION, jeton, max_age=int(comptes.DUREE_SESSION.total_seconds()), httponly=True,
                 samesite="lax", secure=request.url.scheme == "https", path="/")
    return r


def _connecte():
    c = COMPTE.get()
    if c is None:
        raise HTTPException(401, "Connecte-toi d'abord.")
    return c


def _admin():
    c = _connecte()
    if not c.admin:
        raise HTTPException(403, "Réservé au compte principal.")
    return c


def _refuser(e: Exception):
    raise HTTPException(400, str(e))


@app.get("/api/compte")
def api_compte(invitation: str | None = None):
    if not mode_comptes():
        return {"mode": False}
    c = COMPTE.get()
    rep = {"mode": True, "connecte": c is not None, "premier": comptes.aucun_compte() and not en_ligne(),
           "invitation": comptes.invitation_valable(invitation) if invitation else None}
    if c is None:
        return rep
    rep.update({"nom": c.nom, "admin": c.admin})
    if c.dossier:   # un ami : ses clés à lui (masquées)
        cles = config_module.lire_cles(c.cles)
        rep["cles"] = {"gemini": comptes.cle_masquee(cles.get("GEMINI_API_KEY")),
                       "claude": comptes.cle_masquee(cles.get("ANTHROPIC_API_KEY"))}
    else:
        rep["comptes"] = comptes.liste()
    return rep


@app.post("/api/compte/connexion")
def api_connexion(corps: CorpsConnexion, request: Request):
    if not mode_comptes():
        raise HTTPException(404, "Pas de comptes sur ce site.")
    try:
        jeton = comptes.connecter(corps.nom, corps.mot_de_passe)
    except comptes.CompteRefuse as e:
        _refuser(e)
    return _avec_session({"ok": True}, jeton, request)


@app.post("/api/compte/inscription")
def api_inscription(corps: CorpsConnexion, request: Request):
    if not mode_comptes():
        raise HTTPException(404, "Pas de comptes sur ce site.")
    try:
        c = comptes.creer_admin(corps.nom, corps.mot_de_passe) if comptes.aucun_compte() and not en_ligne() \
            else comptes.creer_avec_invitation(corps.code or "", corps.nom, corps.mot_de_passe)
    except comptes.CompteRefuse as e:
        _refuser(e)
    return _avec_session({"ok": True, "admin": c.admin}, comptes.ouvrir_session(c.nom), request)


@app.post("/api/compte/deconnexion")
def api_deconnexion(request: Request):
    comptes.fermer_session(request.cookies.get(COOKIE_SESSION))
    r = Response(json.dumps({"ok": True}), media_type="application/json")
    r.delete_cookie(COOKIE_SESSION, path="/")
    return r


@app.post("/api/compte/cle")
def api_cle(corps: CorpsCle):
    c = _connecte()
    nom = {"gemini": "GEMINI_API_KEY", "claude": "ANTHROPIC_API_KEY"}.get(corps.cle)
    if not c.dossier or not nom:
        raise HTTPException(400, "Les clés du compte principal sont dans le fichier .env.")
    try:
        comptes.ecrire_cle(c, nom, corps.valeur)
    except comptes.CompteRefuse as e:
        _refuser(e)
    valeur = corps.valeur.strip()
    valable = None
    if valeur and corps.cle == "gemini":
        from .. import gemini
        valable = gemini.cle_valable(valeur)
    return {"ok": True, "masquee": comptes.cle_masquee(valeur), "valable": valable}


@app.post("/api/compte/mot-de-passe")
def api_mot_de_passe(corps: CorpsMotDePasse):
    c = _connecte()
    try:
        comptes.changer_mot_de_passe(c.nom, corps.ancien, corps.nouveau)
    except comptes.CompteRefuse as e:
        _refuser(e)
    return {"ok": True}


@app.post("/api/compte/inviter")
def api_inviter(request: Request):
    _admin()
    code = comptes.inviter()
    return {"lien": str(request.base_url) + f"?invitation={code}", "jours": comptes.DUREE_INVITATION.days}


@app.post("/api/compte/supprimer")
def api_supprimer_compte(corps: CorpsNom):
    _admin()
    try:
        comptes.supprimer(corps.nom)
    except comptes.CompteRefuse as e:
        _refuser(e)
    return {"ok": True, "comptes": comptes.liste()}

