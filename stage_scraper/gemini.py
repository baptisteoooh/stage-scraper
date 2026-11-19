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


class ErreurGemini(Exception):
    """bloquante=True : inutile de continuer avec les offres suivantes (clé, quota, réseau...)."""

    def __init__(self, message: str, bloquante: bool = False):
        super().__init__(message)
        self.bloquante = bloquante


class ClientGemini:
    def __init__(self, cle: str | None = None, delai_entre_appels: float = 4.0, timeout: float = 120):
        self.cle = cle or secret("GEMINI_API_KEY")
        if not self.cle:
            raise ErreurGemini("ajoute GEMINI_API_KEY dans .env", bloquante=True)
        self.delai = delai_entre_appels
        self.timeout = timeout
        self._dernier_appel = 0.0

    def generer(self, modele: str, systeme: str, parties: list[dict], schema: dict | None = None,
                reflexion: str | None = None) -> tuple[str, dict]:
        """Un appel. Renvoie (texte de la réponse, compteur de tokens)."""
        config = {}
        if schema:
            config.update(responseMimeType="application/json", responseJsonSchema=schema)
        if reflexion:
            config["thinkingConfig"] = {"thinkingLevel": reflexion}
        corps = {"systemInstruction": {"parts": [{"text": systeme}]},
                 "contents": [{"role": "user", "parts": parties}],
                 "generationConfig": config}

        for essai in range(len(ATTENTES_SURCHARGE) + 1):
            self._patienter()
            try:
                r = requests.post(URL.format(modele=modele), json=corps, timeout=self.timeout,
                                  headers={"x-goog-api-key": self.cle})
            except requests.RequestException as e:
                raise ErreurGemini(f"API Gemini injoignable ({type(e).__name__}) : "
                                   "le reste sera noté au prochain passage", bloquante=True) from e
            if r.status_code in (500, 503) and essai < len(ATTENTES_SURCHARGE):
                log.info("Gemini surchargé (%s), nouvel essai dans %s s", r.status_code, ATTENTES_SURCHARGE[essai])
                time.sleep(ATTENTES_SURCHARGE[essai])
                continue
            break

        if not r.ok:
            raise _erreur_http(r, modele)
        donnees = r.json()
        candidat = (donnees.get("candidates") or [{}])[0]
        texte = "".join(p.get("text", "") for p in candidat.get("content", {}).get("parts", [])
                        if not p.get("thought"))
        if not texte:
            raise ErreurGemini(f"réponse vide (raison : {candidat.get('finishReason') or 'inconnue'})")
        return texte, donnees.get("usageMetadata", {})

    def _patienter(self) -> None:
        attente = self._dernier_appel + self.delai - time.monotonic()
        if attente > 0:
            time.sleep(attente)
        self._dernier_appel = time.monotonic()


def partie_texte(texte: str) -> dict:
    return {"text": texte}


def partie_pdf(contenu: bytes) -> dict:
    return {"inlineData": {"mimeType": "application/pdf", "data": base64.standard_b64encode(contenu).decode("ascii")}}


def _erreur_http(r: requests.Response, modele: str) -> ErreurGemini:
    try:
        detail = r.json().get("error", {}).get("message", "")
    except ValueError:
        detail = r.text[:200]
    if r.status_code in (401, 403) or "API key" in detail:
        return ErreurGemini("clé GEMINI_API_KEY refusée : vérifie-la dans .env", bloquante=True)
    if r.status_code == 429:
        return ErreurGemini("quota gratuit de Gemini atteint (429) : le reste sera noté au prochain passage",
                            bloquante=True)
    if r.status_code == 404:
        return ErreurGemini(f"modèle « {modele} » introuvable : change scoring.modele dans config.yaml",
                            bloquante=True)
    if r.status_code in (500, 503):
        return ErreurGemini(f"Gemini surchargé ({r.status_code}) : le reste sera noté au prochain passage",
                            bloquante=True)
    return ErreurGemini(f"erreur {r.status_code} : {detail}")
