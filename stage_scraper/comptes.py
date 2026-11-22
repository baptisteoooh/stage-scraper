"""Comptes du site (mode « comptes », pour partager le site avec quelques amis).

- Le premier compte créé est celui de BAP (admin) : il garde les fichiers du projet (config.yaml, data/stages.db,
  profil/). Lui seul collecte les offres sur les sites (SerpApi, Careerjet, Gmail…) et peut inviter.
- Chaque ami a son dossier : comptes/<nom>/ avec config.yaml, stages.db, profil/ (CV, lettre) et cles.env (sa clé
  Gemini, et Claude s'il en a une). Il reçoit les offres collectées par BAP et les note avec SA clé.
- Les mots de passe ne sont jamais gardés : seulement une empreinte scrypt salée (impossible à inverser).
- Une session = un jeton aléatoire dans un cookie ; la base ne garde que son empreinte (un vol de la base ne
  donne pas de session valable). Une invitation = un code aléatoire à usage unique, valable 7 jours.

Le dossier des comptes est ignoré par Git (données personnelles).
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from . import db, reglages
from .config import CHEMIN_CONFIG, Compte, RACINE, lire_cles

DUREE_SESSION = timedelta(days=30)
DUREE_INVITATION = timedelta(days=7)
NOM_VALIDE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,29}$")
MOT_DE_PASSE_MIN = 8
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
ESSAIS_MAX = 5           # mots de passe faux d'affilée avant une pause
PAUSE_ESSAIS_S = 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comptes (
    nom         TEXT PRIMARY KEY,
    empreinte   TEXT NOT NULL,             -- scrypt$sel$hash (hex)
    admin       INTEGER NOT NULL DEFAULT 0,
    cree_le     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    empreinte   TEXT PRIMARY KEY,          -- sha256 du jeton (le jeton lui-même n'est que dans le cookie)
    nom         TEXT NOT NULL REFERENCES comptes(nom) ON DELETE CASCADE,
    expire      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS careerjet_jour (   -- recherches Careerjet faites par un ami aujourd'hui (plafond)
    nom         TEXT NOT NULL,
    jour        TEXT NOT NULL,
    nb          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (nom, jour)
);
CREATE TABLE IF NOT EXISTS careerjet_cache (  -- résultats d'une recherche, réutilisés par les autres comptes
    cle         TEXT PRIMARY KEY,              -- empreinte de (mots-clés, lieu, type de contrat, taille)
    date        TEXT NOT NULL,
    offres      TEXT NOT NULL                  -- JSON
);
CREATE TABLE IF NOT EXISTS invitations (
    empreinte   TEXT PRIMARY KEY,          -- sha256 du code
    cree_le     TEXT NOT NULL,
    expire      TEXT NOT NULL,
    utilisee_par TEXT
);
"""

_echecs: dict[str, list[float]] = {}   # nom -> instants des derniers mots de passe faux (en mémoire)


class CompteRefuse(Exception):
    """Message à montrer tel quel (nom pris, mot de passe trop court, invitation périmée…)."""


# =========================================================================== où sont les comptes

def dossier_comptes() -> Path:
    autre = os.getenv("STAGE_SCRAPER_COMPTES_DOSSIER")
    return Path(autre) if autre else RACINE / "comptes"


def _connecter() -> sqlite3.Connection:
    dossier = dossier_comptes()
    dossier.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(dossier / "comptes.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn


def _maintenant() -> datetime:
    return datetime.now()


def _hacher_jeton(jeton: str) -> str:
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


# =========================================================================== mots de passe

def _empreinte_mdp(mot_de_passe: str, sel: bytes | None = None) -> str:
    sel = sel or secrets.token_bytes(16)
    h = hashlib.scrypt(mot_de_passe.encode("utf-8"), salt=sel, **_SCRYPT)
    return f"scrypt${sel.hex()}${h.hex()}"


def _mdp_correct(mot_de_passe: str, empreinte: str) -> bool:
    try:
        _, sel, attendu = empreinte.split("$")
        return hmac.compare_digest(_empreinte_mdp(mot_de_passe, bytes.fromhex(sel)).split("$")[2], attendu)
    except ValueError:
        return False


# =========================================================================== comptes

def aucun_compte() -> bool:
    with closing(_connecter()) as conn:
        return conn.execute("SELECT COUNT(*) FROM comptes").fetchone()[0] == 0


def compte(nom: str) -> Compte | None:
    with closing(_connecter()) as conn:
        ligne = conn.execute("SELECT nom, admin FROM comptes WHERE nom = ?", (nom,)).fetchone()
    return _vers_compte(ligne) if ligne else None


def _vers_compte(ligne) -> Compte:
    return Compte(nom=ligne["nom"], admin=bool(ligne["admin"]),
                  dossier=None if ligne["admin"] else dossier_comptes() / ligne["nom"])


def liste() -> list[dict]:
    with closing(_connecter()) as conn:
        return [dict(l) for l in conn.execute("SELECT nom, admin, cree_le FROM comptes ORDER BY admin DESC, cree_le")]


def amis() -> list[Compte]:
    """Les comptes qui ont leur propre dossier (tous sauf BAP)."""
    with closing(_connecter()) as conn:
        return [_vers_compte(l) for l in conn.execute("SELECT nom, admin FROM comptes WHERE admin = 0 ORDER BY nom")]


def _verifier_nouveau(conn, nom: str, mot_de_passe: str) -> str:
    nom = (nom or "").strip().lower()
    if not NOM_VALIDE.match(nom):
        raise CompteRefuse("Nom : 2 à 30 caractères, lettres minuscules, chiffres, - ou _ (sans espace ni accent).")
    if len(mot_de_passe or "") < MOT_DE_PASSE_MIN:
        raise CompteRefuse(f"Mot de passe : au moins {MOT_DE_PASSE_MIN} caractères.")
    if conn.execute("SELECT 1 FROM comptes WHERE nom = ?", (nom,)).fetchone():
        raise CompteRefuse("Ce nom est déjà pris.")
    return nom


def creer_admin(nom: str, mot_de_passe: str) -> Compte:
    """Le tout premier compte : celui de BAP, sur les fichiers du projet. Refusé s'il existe déjà des comptes."""
    with closing(_connecter()) as conn:
        if conn.execute("SELECT COUNT(*) FROM comptes").fetchone()[0]:
            raise CompteRefuse("Le premier compte existe déjà : demande une invitation.")
        nom = _verifier_nouveau(conn, nom, mot_de_passe)
        conn.execute("INSERT INTO comptes (nom, empreinte, admin, cree_le) VALUES (?, ?, 1, ?)",
                     (nom, _empreinte_mdp(mot_de_passe), _maintenant().isoformat(timespec="seconds")))
        conn.commit()
    return compte(nom)


def creer_avec_invitation(code: str, nom: str, mot_de_passe: str) -> Compte:
    with closing(_connecter()) as conn:
        inv = conn.execute("SELECT * FROM invitations WHERE empreinte = ?", (_hacher_jeton(code or ""),)).fetchone()
        if not inv or inv["utilisee_par"] or inv["expire"] < _maintenant().isoformat():
            raise CompteRefuse("Cette invitation n'est plus valable : demande un nouveau lien.")
        nom = _verifier_nouveau(conn, nom, mot_de_passe)
        nouveau = Compte(nom=nom, dossier=dossier_comptes() / nom)
        _preparer_dossier(nouveau)
        conn.execute("INSERT INTO comptes (nom, empreinte, admin, cree_le) VALUES (?, ?, 0, ?)",
                     (nom, _empreinte_mdp(mot_de_passe), _maintenant().isoformat(timespec="seconds")))
        conn.execute("UPDATE invitations SET utilisee_par = ? WHERE empreinte = ?", (nom, inv["empreinte"]))
        conn.commit()
    return nouveau


def supprimer(nom: str) -> None:
    """Supprime le compte d'un ami ET son dossier (base, CV, clés). Le compte de BAP ne se supprime pas."""
    c = compte(nom)
    if not c or c.admin:
        raise CompteRefuse("Ce compte ne peut pas être supprimé.")
    with closing(_connecter()) as conn:
        conn.execute("DELETE FROM comptes WHERE nom = ?", (nom,))
        conn.commit()
    if c.dossier and c.dossier.resolve().parent == dossier_comptes().resolve():
        shutil.rmtree(c.dossier, ignore_errors=True)


def _preparer_dossier(c: Compte) -> None:
    """Dossier neuf : réglages tirés de ceux du projet, mais sans le profil de BAP (l'entretien d'accueil le remplira)."""
    c.dossier.mkdir(parents=True, exist_ok=False)
    (c.dossier / "profil").mkdir()
    donnees = reglages.lire(Path(os.getenv("STAGE_SCRAPER_CONFIG") or CHEMIN_CONFIG))   # les réglages de BAP servent de modèle
    p = donnees["profil"]
    p["recherche"] = ""
    for cle in ("entretien_accueil",):
        p.pop(cle, None)
    for cle in ("ecole", "annee", "majeure"):
        if cle in p:
            p[cle] = ""
    if "competences" in p:
        p["competences"] = []
    p["cv"] = "profil/cv.pdf"
    p["modele_lettre"] = "profil/modele_lettre.txt"
    donnees["general"]["base_de_donnees"] = "stages.db"
    notif = donnees.get("notifications")
    if notif is not None:
        notif["envoi_actif"] = False      # les mails partent de la boîte Gmail de BAP : pas pour les amis
        notif["dossier_apercus"] = "mails"
    reglages.ecrire(donnees, c.config)
    c.config.with_name("config.yaml.bak").unlink(missing_ok=True)
    with closing(db.connecter(c.dossier / "stages.db")) as conn:
        db.initialiser(conn)


# =========================================================================== connexion et sessions

def connecter(nom: str, mot_de_passe: str) -> str:
    """Vérifie le mot de passe et ouvre une session. Renvoie le jeton (à mettre dans le cookie)."""
    nom = (nom or "").strip().lower()
    recents = [t for t in _echecs.get(nom, []) if time.monotonic() - t < PAUSE_ESSAIS_S]
    if len(recents) >= ESSAIS_MAX:
        raise CompteRefuse("Trop d'essais : attends une minute.")
    with closing(_connecter()) as conn:
        ligne = conn.execute("SELECT empreinte FROM comptes WHERE nom = ?", (nom,)).fetchone()
        # même calcul (et même durée) que le compte existe ou non
        ok = _mdp_correct(mot_de_passe or "", ligne["empreinte"] if ligne else _empreinte_mdp("leurre"))
        if not (ligne and ok):
            _echecs[nom] = recents + [time.monotonic()]
            raise CompteRefuse("Nom ou mot de passe incorrect.")
        _echecs.pop(nom, None)
        return _ouvrir_session(conn, nom)


def _ouvrir_session(conn, nom: str) -> str:
    jeton = secrets.token_urlsafe(32)
    maintenant = _maintenant()
    conn.execute("DELETE FROM sessions WHERE expire < ?", (maintenant.isoformat(),))
    conn.execute("INSERT INTO sessions (empreinte, nom, expire) VALUES (?, ?, ?)",
                 (_hacher_jeton(jeton), nom, (maintenant + DUREE_SESSION).isoformat()))
    conn.commit()
    return jeton


def ouvrir_session(nom: str) -> str:
    """Session ouverte juste après la création d'un compte (pas besoin de retaper le mot de passe)."""
    with closing(_connecter()) as conn:
        return _ouvrir_session(conn, nom)


def session(jeton: str | None) -> Compte | None:
    if not jeton:
        return None
    with closing(_connecter()) as conn:
        ligne = conn.execute("SELECT c.nom, c.admin FROM sessions s JOIN comptes c ON c.nom = s.nom "
                             "WHERE s.empreinte = ? AND s.expire > ?",
                             (_hacher_jeton(jeton), _maintenant().isoformat())).fetchone()
    return _vers_compte(ligne) if ligne else None


def fermer_session(jeton: str | None) -> None:
    if jeton:
        with closing(_connecter()) as conn:
            conn.execute("DELETE FROM sessions WHERE empreinte = ?", (_hacher_jeton(jeton),))
            conn.commit()


def changer_mot_de_passe(nom: str, ancien: str, nouveau: str) -> None:
    with closing(_connecter()) as conn:
        ligne = conn.execute("SELECT empreinte FROM comptes WHERE nom = ?", (nom,)).fetchone()
        if not ligne or not _mdp_correct(ancien or "", ligne["empreinte"]):
            raise CompteRefuse("Mot de passe actuel incorrect.")
        if len(nouveau or "") < MOT_DE_PASSE_MIN:
            raise CompteRefuse(f"Mot de passe : au moins {MOT_DE_PASSE_MIN} caractères.")
        conn.execute("UPDATE comptes SET empreinte = ? WHERE nom = ?", (_empreinte_mdp(nouveau), nom))
        conn.commit()


# =========================================================================== invitations

def inviter() -> str:
    """Nouveau code d'invitation (à usage unique, 7 jours). Seule son empreinte est gardée."""
    code = secrets.token_urlsafe(18)
    maintenant = _maintenant()
    with closing(_connecter()) as conn:
        conn.execute("INSERT INTO invitations (empreinte, cree_le, expire) VALUES (?, ?, ?)",
                     (_hacher_jeton(code), maintenant.isoformat(timespec="seconds"),
                      (maintenant + DUREE_INVITATION).isoformat()))
        conn.commit()
    return code


def invitation_valable(code: str | None) -> bool:
    if not code:
        return False
    with closing(_connecter()) as conn:
        inv = conn.execute("SELECT utilisee_par, expire FROM invitations WHERE empreinte = ?",
                           (_hacher_jeton(code),)).fetchone()
    return bool(inv) and not inv["utilisee_par"] and inv["expire"] > _maintenant().isoformat()


# =========================================================================== clés IA d'un compte

CLES_MODIFIABLES = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY")


def ecrire_cle(c: Compte, nom: str, valeur: str | None) -> None:
    """Enregistre (ou efface, valeur vide) une clé IA dans le cles.env du compte."""
    if nom not in CLES_MODIFIABLES or not c.cles:
        raise CompteRefuse("Clé inconnue.")
    valeur = (valeur or "").strip()
    if valeur and not re.fullmatch(r"[A-Za-z0-9_\-]{20,200}", valeur):
        raise CompteRefuse("Cette clé n'a pas le bon format : copie-la en entier, sans espace.")
    cles = lire_cles(c.cles)
    if valeur:
        cles[nom] = valeur
    else:
        cles.pop(nom, None)
    c.cles.write_text("".join(f"{k}={v}\n" for k, v in cles.items()), encoding="utf-8")


def cle_masquee(valeur: str | None) -> str | None:
    """« AIza…x7Q4 » : assez pour reconnaître sa clé, jamais assez pour la réutiliser."""
    return f"{valeur[:4]}…{valeur[-4:]}" if valeur and len(valeur) > 12 else ("…" if valeur else None)


# =========================================================================== Careerjet partagé

CAREERJET_PAR_AMI_PAR_JOUR = 15        # recherches réelles (hors mémoire) par ami et par jour
DUREE_CACHE_CAREERJET = timedelta(hours=24)


def comptes_actifs() -> bool:
    """Vrai si le site partagé a déjà servi (sinon rien n'est écrit dans comptes/)."""
    return (dossier_comptes() / "comptes.db").exists()


def careerjet_restantes(nom: str) -> int:
    with closing(_connecter()) as conn:
        ligne = conn.execute("SELECT nb FROM careerjet_jour WHERE nom = ? AND jour = ?",
                             (nom, _maintenant().date().isoformat())).fetchone()
    return max(0, CAREERJET_PAR_AMI_PAR_JOUR - (ligne["nb"] if ligne else 0))


def careerjet_compter(nom: str) -> None:
    with closing(_connecter()) as conn:
        conn.execute("INSERT INTO careerjet_jour (nom, jour, nb) VALUES (?, ?, 1) "
                     "ON CONFLICT (nom, jour) DO UPDATE SET nb = nb + 1", (nom, _maintenant().date().isoformat()))
        conn.commit()


def careerjet_memoire(cle: str) -> list[dict] | None:
    """Offres d'une recherche faite il y a moins de 24 h (par n'importe quel compte), ou None."""
    with closing(_connecter()) as conn:
        ligne = conn.execute("SELECT date, offres FROM careerjet_cache WHERE cle = ?", (cle,)).fetchone()
    if not ligne or ligne["date"] < (_maintenant() - DUREE_CACHE_CAREERJET).isoformat():
        return None
    return json.loads(ligne["offres"])


def careerjet_memoriser(cle: str, offres: list[dict]) -> None:
    with closing(_connecter()) as conn:
        limite = (_maintenant() - DUREE_CACHE_CAREERJET).isoformat()
        conn.execute("DELETE FROM careerjet_cache WHERE date < ?", (limite,))
        conn.execute("INSERT OR REPLACE INTO careerjet_cache (cle, date, offres) VALUES (?, ?, ?)",
                     (cle, _maintenant().isoformat(), json.dumps(offres, ensure_ascii=False)))
        conn.commit()

