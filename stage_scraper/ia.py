"""Accès à l'IA sans clé personnelle : une cascade de fournisseurs essayés dans l'ordre.

Chaque fournisseur a un quota gratuit par jour. Quand l'un répond « quota atteint » (erreur 429),
il est mis de côté jusqu'au lendemain et le suivant prend le relais. Ordre par défaut :
  1. Gemini, seulement si une clé GEMINI_API_KEY est renseignée (BAP, ou un ami qui a mis la sienne) ;
  2. Cloudflare Workers AI (Gemma 4 26B) : CLOUDFLARE_ACCOUNT_ID et CLOUDFLARE_API_TOKEN dans .env ;
  3. Groq (Qwen3.8 27B) : GROQ_API_KEY dans .env.
Cloudflare et Groq sont les clés de BAP, prêtées aux amis (config.SECRETS_PARTAGES). L'ordre et les
modèles se changent dans config.yaml > ia > cascade (les catalogues gratuits changent souvent).

Le client a la même interface que gemini.ClientGemini (generer, appeler), avec les messages et
réponses au format Gemini : le reste du code n'a pas à savoir quel fournisseur a répondu.
Cloudflare et Groq parlent le format d'OpenAI (chat/completions) : ce module fait la traduction.
"""
import json
import logging
import time
from datetime import date

import requests

from . import gemini
from .config import secret

log = logging.getLogger(__name__)

# Fournisseurs au format OpenAI : adresse (avec {compte} pour Cloudflare) et secrets nécessaires.
FOURNISSEURS = {
    "cloudflare": {"url": "https://api.cloudflare.com/client/v4/accounts/{compte}/ai/v1/chat/completions",
                   "cle": "CLOUDFLARE_API_TOKEN", "compte": "CLOUDFLARE_ACCOUNT_ID"},
    "groq": {"url": "https://api.groq.com/openai/v1/chat/completions", "cle": "GROQ_API_KEY"},
}

# Utilisée quand config.yaml n'a pas de rubrique ia (par exemple le config.yaml d'un ami).
# « options » : réglages propres au modèle, ici pour couper sa réflexion (5 à 10 fois plus rapide et
# économe en quota, sans perte visible au test du 24/11/2026).
CASCADE_PAR_DEFAUT = [
    {"fournisseur": "gemini"},
    {"fournisseur": "cloudflare", "modele": "@cf/google/gemma-4-26b-a4b-it",
     "options": {"chat_template_kwargs": {"enable_thinking": False}}},
    {"fournisseur": "groq", "modele": "qwen/qwen3.8-27b", "options": {"reasoning_effort": "none"}},
]

ATTENTE_429_MAX = 60   # une limite par minute (attente courte proposée) est attendue ; au-delà : quota du jour
ATTENTES_SURCHARGE = (5,)

# Fournisseurs dont le quota du jour est épuisé : {nom: date}. Partagé par tout le processus (site,
# passage de 8 h) : inutile de redemander à un fournisseur épuisé à chaque offre.
_EPUISES: dict[str, date] = {}


class ErreurIA(gemini.ErreurGemini):
    """Erreur d'un fournisseur. quota=True : quota du jour atteint (on passe au suivant jusqu'à demain)."""

    def __init__(self, message: str, bloquante: bool = False, quota: bool = False):
        super().__init__(message, bloquante=bloquante)
        self.quota = quota


# =========================================================================== choix du client

def cascade(config: dict | None) -> list[dict]:
    return list(((config or {}).get("ia") or {}).get("cascade") or CASCADE_PAR_DEFAUT)


def _branche(etape: dict) -> bool:
    """Le fournisseur a-t-il ses secrets ?"""
    nom = etape.get("fournisseur")
    if nom == "gemini":
        return bool(secret("GEMINI_API_KEY"))
    f = FOURNISSEURS.get(nom)
    return bool(f) and all(secret(f[k]) for k in ("cle", "compte") if k in f)


def disponible(config: dict | None = None) -> bool:
    """Au moins un fournisseur branché : l'IA peut répondre."""
    return any(_branche(e) for e in cascade(config))


def client(config: dict | None = None, delai_entre_appels: float = 0, timeout: float = 120,
           attentes_surcharge: tuple = ATTENTES_SURCHARGE) -> "ClientCascade":
    """Le client à utiliser partout à la place de gemini.ClientGemini."""
    return ClientCascade(config, delai_entre_appels=delai_entre_appels, timeout=timeout,
                         attentes_surcharge=attentes_surcharge)


# =========================================================================== cascade

class ClientCascade:
    """Essaie chaque fournisseur branché, dans l'ordre. `dernier_modele` : celui qui a répondu en dernier."""

    def __init__(self, config: dict | None = None, delai_entre_appels: float = 0, timeout: float = 120,
                 attentes_surcharge: tuple = ATTENTES_SURCHARGE):
        self.etapes = [e for e in cascade(config) if _branche(e)]
        if not self.etapes:
            from .config import ou_mettre_la_cle
            raise ErreurIA(f"aucune IA branchée : {ou_mettre_la_cle()}", bloquante=True)
        self.delai, self.timeout, self.attentes = delai_entre_appels, timeout, tuple(attentes_surcharge)
        self._clients: dict[str, object] = {}
        self.dernier_modele: str | None = None

    def generer(self, modele: str, systeme: str, parties: list[dict], schema: dict | None = None,
                reflexion: str | None = None) -> tuple[str, dict]:
        contenu, usage = self.appeler(modele, systeme, [{"role": "user", "parts": parties}], schema, reflexion)
        return gemini.texte_de(contenu), usage

    def appeler(self, modele: str, systeme: str, contents: list[dict], schema: dict | None = None,
                reflexion: str | None = None, outils: list[dict] | None = None,
                forcer_outil: bool = False) -> tuple[dict, dict]:
        """`modele` (et `reflexion`) ne servent qu'à Gemini ; les autres fournisseurs ont leur modèle dans la cascade.
        Avec un schéma, une réponse qui n'est pas du JSON valide est redemandée une fois, puis au suivant."""
        aujourd_hui = date.today()
        derniere = None
        for etape in self.etapes:
            nom = etape["fournisseur"]
            if _EPUISES.get(nom) == aujourd_hui:
                derniere = derniere or ErreurIA(f"quota du jour de {nom} atteint", bloquante=True, quota=True)
                continue
            modele_etape = modele if nom == "gemini" else etape["modele"]
            for essai in range(2):
                try:
                    contenu, usage = self._client(etape).appeler(
                        modele_etape, systeme, contents, schema=schema,
                        reflexion=reflexion if nom == "gemini" else None, outils=outils, forcer_outil=forcer_outil)
                except gemini.ErreurGemini as e:
                    derniere = e
                    if getattr(e, "quota", False) or (nom == "gemini" and "quota" in str(e)):
                        _EPUISES[nom] = aujourd_hui
                    log.info("IA : %s n'a pas répondu (%s), fournisseur suivant", nom, e)
                    break
                if schema and not gemini.appels_outils(contenu) and not _json_valide(contenu):
                    derniere = ErreurIA(f"réponse illisible de {nom}")
                    continue   # un second essai, puis le fournisseur suivant
                self.dernier_modele = f"{nom}/{modele_etape}" if nom != "gemini" else modele_etape
                return contenu, {**usage, "modele": self.dernier_modele}
        if isinstance(derniere, gemini.ErreurGemini):
            raise ErreurIA(f"aucune IA disponible ({derniere}) : le reste sera traité plus tard", bloquante=True,
                           quota=getattr(derniere, "quota", False)) from derniere
        raise ErreurIA("aucune IA disponible", bloquante=True)

    def _client(self, etape: dict):
        nom = etape["fournisseur"]
        if nom not in self._clients:
            if nom == "gemini":
                self._clients[nom] = gemini.ClientGemini(delai_entre_appels=self.delai, timeout=self.timeout,
                                                         attentes_surcharge=self.attentes)
            else:
                self._clients[nom] = ClientCompatible(nom, options=etape.get("options"), timeout=self.timeout,
                                                      attentes_surcharge=self.attentes)
        return self._clients[nom]


def _json_valide(contenu: dict) -> bool:
    try:
        json.loads(gemini.texte_de(contenu))
        return True
    except (ValueError, gemini.ErreurGemini):
        return False


# =========================================================================== fournisseur au format OpenAI

class ClientCompatible:
    """Un fournisseur qui parle le format d'OpenAI (Cloudflare, Groq). Messages et réponses au format Gemini."""

    def __init__(self, nom: str, options: dict | None = None, timeout: float = 120,
                 attentes_surcharge: tuple = ATTENTES_SURCHARGE):
        f = FOURNISSEURS[nom]
        self.nom, self.options, self.timeout, self.attentes = nom, dict(options or {}), timeout, attentes_surcharge
        self.cle = secret(f["cle"])
        self.url = f["url"].format(compte=secret(f["compte"]) if "compte" in f else "")
        if not self.cle:
            raise ErreurIA(f"clé {f['cle']} absente", bloquante=True)

    def appeler(self, modele: str, systeme: str, contents: list[dict], schema: dict | None = None,
                reflexion: str | None = None, outils: list[dict] | None = None,
                forcer_outil: bool = False) -> tuple[dict, dict]:
        format_json = {"type": "json_schema", "json_schema": {"name": "reponse", "schema": schema}} if schema else None
        corps = {"model": modele, "messages": [{"role": "system", "content": systeme}] + vers_messages(contents),
                 "temperature": 0.2, **self.options}
        if outils:
            # Outils + format imposé dans la même requête : le modèle n'appellerait plus d'outil. Le format
            # est d'abord demandé dans les consignes ; s'il répond quand même en texte libre, on lui
            # redemande sa réponse avec le format imposé (et les outils désactivés).
            if schema:
                corps["messages"][0]["content"] += (
                    "\n\nQuand tu réponds sans appeler d'outil, ta réponse est uniquement un objet JSON conforme "
                    "à ce schéma :\n" + json.dumps(schema, ensure_ascii=False))
            corps["tools"] = [{"type": "function", "function": {"name": o["name"], "description": o.get("description", ""),
                                                                "parameters": o.get("parameters") or {"type": "object", "properties": {}}}}
                              for o in outils]
            if forcer_outil:
                corps["tool_choice"] = "required"
        elif format_json:
            corps["response_format"] = format_json

        contenu, usage = self._envoyer(corps, modele)
        if schema and outils and not forcer_outil and not gemini.appels_outils(contenu) and not _json_valide(contenu):
            contenu, usage2 = self._envoyer({**corps, "tool_choice": "none", "response_format": format_json}, modele)
            usage = {k: usage[k] + usage2[k] for k in usage}
        return contenu, usage

    def _envoyer(self, corps: dict, modele: str) -> tuple[dict, dict]:
        """Une requête, avec patience sur la limite par minute et un nouvel essai si le serveur est surchargé."""
        for essai in range(len(self.attentes) + 2):
            try:
                r = requests.post(self.url, json=corps, timeout=self.timeout,
                                  headers={"Authorization": f"Bearer {self.cle}"})
            except requests.RequestException as e:
                raise ErreurIA(f"{self.nom} injoignable ({type(e).__name__})", bloquante=True) from e
            if r.status_code in (500, 502, 503) and essai < len(self.attentes):
                time.sleep(self.attentes[essai])
                continue
            attente = _attente_courte(r)
            if attente is not None and essai <= len(self.attentes):   # limite par minute : on patiente
                log.info("%s : limite par minute, nouvel essai dans %.0f s", self.nom, attente)
                time.sleep(attente + 1)
                continue
            break
        if not r.ok:
            raise _erreur_http(self.nom, r, modele)
        donnees = r.json()
        message = ((donnees.get("choices") or [{}])[0]).get("message") or {}
        u = donnees.get("usage") or {}
        usage = {"promptTokenCount": u.get("prompt_tokens", 0) or 0,
                 "candidatesTokenCount": u.get("completion_tokens", 0) or 0}
        contenu = depuis_message(message)
        if not contenu["parts"]:
            raise ErreurIA(f"réponse vide de {self.nom}")
        return contenu, usage


def _attente_courte(r: requests.Response) -> float | None:
    """Erreur 429 avec une courte attente proposée (limite par minute), sinon None (quota du jour)."""
    if r.status_code != 429:
        return None
    try:
        attente = float(r.headers.get("retry-after", ""))
    except ValueError:
        return None
    return attente if attente <= ATTENTE_429_MAX else None


def _erreur_http(nom: str, r: requests.Response, modele: str) -> ErreurIA:
    try:
        corps = r.json()
        detail = (corps.get("error") or {}).get("message") if isinstance(corps.get("error"), dict) else None
        detail = detail or "; ".join(e.get("message", "") for e in corps.get("errors") or []) or r.text[:200]
    except ValueError:
        detail = r.text[:200]
    if r.status_code in (401, 403):
        return ErreurIA(f"clé {nom} refusée ({r.status_code})", bloquante=True)
    # Cloudflare : quota gratuit de neurons du jour épuisé (code 4006, parfois sans 429)
    if r.status_code == 429 or "neurons" in detail.lower() or "daily free allocation" in detail.lower():
        return ErreurIA(f"quota gratuit du jour de {nom} atteint", bloquante=True, quota=True)
    if r.status_code in (404, 410):
        return ErreurIA(f"modèle « {modele} » introuvable ou retiré chez {nom} : change ia.cascade dans config.yaml",
                        bloquante=True)
    if r.status_code >= 500 or r.status_code == 408:
        return ErreurIA(f"{nom} surchargé ({r.status_code})", bloquante=True)
    return ErreurIA(f"{nom} : erreur {r.status_code} : {detail[:200]}")


# =========================================================================== traduction Gemini <-> OpenAI

def vers_messages(contents: list[dict]) -> list[dict]:
    """Conversation au format Gemini -> messages au format OpenAI.

    Les appels d'outils n'ont pas d'identifiant chez Gemini : chaque réponse d'outil (functionResponse)
    est rattachée, dans l'ordre, aux appels du message précédent du modèle.
    """
    messages, en_attente = [], []
    for c in contents:
        parts = c.get("parts") or []
        if c.get("role") == "model":
            texte = "".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought"))
            appels = [p for p in parts if "functionCall" in p]
            m = {"role": "assistant", "content": texte or None}
            if appels:
                m["tool_calls"] = [{"id": p["functionCall"].get("id") or f"appel_{len(messages)}_{i}", "type": "function",
                                    "function": {"name": p["functionCall"]["name"],
                                                 "arguments": json.dumps(p["functionCall"].get("args") or {},
                                                                         ensure_ascii=False)}}
                                   for i, p in enumerate(appels)]
                en_attente = [t["id"] for t in m["tool_calls"]]
            messages.append(m)
            continue
        texte = []
        for p in parts:
            if "functionResponse" in p:
                ident = en_attente.pop(0) if en_attente else f"appel_{len(messages)}"
                messages.append({"role": "tool", "tool_call_id": ident,
                                 "content": json.dumps(p["functionResponse"].get("response"), ensure_ascii=False)})
            elif "text" in p:
                texte.append(p["text"])
        if texte:
            messages.append({"role": "user", "content": "".join(texte)})
    return messages


def depuis_message(message: dict) -> dict:
    """Message de réponse au format OpenAI -> contenu au format Gemini ({role: model, parts})."""
    parts = []
    if message.get("content"):
        parts.append({"text": message["content"]})
    for t in message.get("tool_calls") or []:
        f = t.get("function") or {}
        try:
            args = json.loads(f.get("arguments") or "{}")
        except ValueError:
            args = {}
        # l'identifiant va dans functionCall (champ « id » prévu aussi par Gemini, si la suite passe chez lui)
        parts.append({"functionCall": {"name": f.get("name"), "args": args, "id": t.get("id")}})
    return {"role": "model", "parts": parts}
