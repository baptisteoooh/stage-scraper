"""Accès à l'API Gemini de Google (offre gratuite d'AI Studio), par de simples requêtes HTTP.

Clé : GEMINI_API_KEY dans .env (https://aistudio.google.com, rubrique « Get API key »).
Le client espace ses appels (limite de requêtes par minute de l'offre gratuite) et réessaie
quand le modèle est momentanément surchargé (erreur 503).
"""
import base64
import logging
import time

import requests

from .config import secret

log = logging.getLogger(__name__)

URL = "https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent"
ATTENTES_SURCHARGE = (5, 20)  # secondes d'attente avant chaque nouvel essai après une erreur 503 / 500
ATTENTE_429_MAX = 60          # au-delà, une erreur 429 n'est pas retentée (quota du jour)


class ErreurGemini(Exception):
    """bloquante=True : inutile de continuer avec les offres suivantes (clé, quota, réseau...)."""

    def __init__(self, message: str, bloquante: bool = False):
        super().__init__(message)
        self.bloquante = bloquante


class ClientGemini:
    def __init__(self, cle: str | None = None, delai_entre_appels: float = 4.0, timeout: float = 120,
                 attentes_surcharge: tuple = ATTENTES_SURCHARGE):
        self.cle = cle or secret("GEMINI_API_KEY")
        if not self.cle:
            raise ErreurGemini("ajoute GEMINI_API_KEY dans .env", bloquante=True)
        self.delai = delai_entre_appels
        self.timeout = timeout
        self.attentes = tuple(attentes_surcharge)   # moins d'essais quand quelqu'un attend devant l'écran
        self._dernier_appel = 0.0

    def generer(self, modele: str, systeme: str, parties: list[dict], schema: dict | None = None,
                reflexion: str | None = None) -> tuple[str, dict]:
        """Un appel simple (un seul message). Renvoie (texte de la réponse, compteur de tokens)."""
        contenu, usage = self.appeler(modele, systeme, [{"role": "user", "parts": parties}], schema, reflexion)
        return texte_de(contenu), usage

    def appeler(self, modele: str, systeme: str, contents: list[dict], schema: dict | None = None,
                reflexion: str | None = None, outils: list[dict] | None = None) -> tuple[dict, dict]:
        """Un appel avec toute la conversation (`contents`) et d'éventuels outils.

        Renvoie (contenu de la réponse : {role: 'model', parts: [...]}, compteur de tokens). Les
        parts peuvent être du texte ou des appels d'outils ({functionCall: {name, args}}).
        """
        config = {}
        if schema:
            config.update(responseMimeType="application/json", responseJsonSchema=schema)
        if reflexion:
            config["thinkingConfig"] = {"thinkingLevel": reflexion}
        corps = {"systemInstruction": {"parts": [{"text": systeme}]}, "contents": contents,
                 "generationConfig": config}
        if outils:
            corps["tools"] = [{"functionDeclarations": outils}]

        for essai in range(len(self.attentes) + 1):
            self._patienter()
            try:
                r = requests.post(URL.format(modele=modele), json=corps, timeout=self.timeout,
                                  headers={"x-goog-api-key": self.cle})
            except requests.RequestException as e:
                raise ErreurGemini(f"API Gemini injoignable ({type(e).__name__}) : "
                                   "le reste sera noté au prochain passage", bloquante=True) from e
            if r.status_code in (500, 503) and essai < len(self.attentes):
                log.info("Gemini surchargé (%s), nouvel essai dans %s s", r.status_code, self.attentes[essai])
                time.sleep(self.attentes[essai])
                continue
            # 429 avec une courte attente proposée par Google : limite par minute, on patiente.
            # (Le quota du jour, lui, ne propose pas d'attente courte : on s'arrête.)
            attente = attente_proposee(r) if r.status_code == 429 else None
            if attente is not None and attente <= ATTENTE_429_MAX and essai < len(self.attentes):
                log.info("Limite de Gemini par minute atteinte, nouvel essai dans %.0f s", attente)
                time.sleep(attente + 1)
                continue
            break

        if not r.ok:
            raise _erreur_http(r, modele)
        donnees = r.json()
        candidat = (donnees.get("candidates") or [{}])[0]
        contenu = candidat.get("content") or {}
        if not contenu.get("parts"):
            raise ErreurGemini(f"réponse vide (raison : {candidat.get('finishReason') or 'inconnue'})")
        contenu.setdefault("role", "model")
        return contenu, donnees.get("usageMetadata", {})

    def _patienter(self) -> None:
        attente = self._dernier_appel + self.delai - time.monotonic()
        if attente > 0:
            time.sleep(attente)
        self._dernier_appel = time.monotonic()


def texte_de(contenu: dict) -> str:
    """Le texte d'une réponse (sans les pensées du modèle ni les appels d'outils)."""
    texte = "".join(p.get("text", "") for p in contenu.get("parts", []) if not p.get("thought"))
    if not texte:
        raise ErreurGemini("réponse vide")
    return texte


def appels_outils(contenu: dict) -> list[dict]:
    """Les appels d'outils demandés par le modèle : [{name, args}]."""
    return [p["functionCall"] for p in contenu.get("parts", []) if "functionCall" in p]


def partie_texte(texte: str) -> dict:
    return {"text": texte}


def partie_pdf(contenu: bytes) -> dict:
    return {"inlineData": {"mimeType": "application/pdf", "data": base64.standard_b64encode(contenu).decode("ascii")}}


def attente_proposee(r: requests.Response) -> float | None:
    """Secondes d'attente indiquées par Google dans une erreur 429 (RetryInfo), ou None."""
    try:
        details = r.json().get("error", {}).get("details", [])
    except ValueError:
        return None
    for d in details:
        if str(d.get("@type", "")).endswith("RetryInfo"):
            try:
                return float(str(d.get("retryDelay", "")).rstrip("s"))
            except ValueError:
                return None
    return None


def _erreur_http(r: requests.Response, modele: str) -> ErreurGemini:
    try:
        detail = r.json().get("error", {}).get("message", "")
    except ValueError:
        detail = r.text[:200]
    if r.status_code in (401, 403) or "API key" in detail:
        return ErreurGemini("clé GEMINI_API_KEY refusée : vérifie-la dans .env", bloquante=True)
    if r.status_code == 429:
        return ErreurGemini("quota gratuit de Gemini atteint (429) : réessaie plus tard (le reste sera noté "
                            "au prochain passage)", bloquante=True)
    if r.status_code == 404:
        return ErreurGemini(f"modèle « {modele} » introuvable : change scoring.modele dans config.yaml",
                            bloquante=True)
    if r.status_code in (500, 503):
        return ErreurGemini(f"Gemini surchargé ({r.status_code}) : le reste sera noté au prochain passage",
                            bloquante=True)
    return ErreurGemini(f"erreur {r.status_code} : {detail}")
