"""Client Claude (API Anthropic) de la page Candidater, et suivi du crédit prépayé.

Répartition (config.yaml > dossier) : Sonnet pour l'analyse de l'offre et le premier jet de la
lettre, Haiku pour les retouches. Gemini (gratuit) prend le relais si Claude échoue ou si un
plafond est atteint.

Économies :
- cache de prompt : la partie fixe (consignes, CV, offre) est marquée « à garder » ; les appels
  suivants du même dossier la relisent pour ~10 % du prix (5 % sur Sonnet) pendant 5 minutes ;
- réflexion dosée (effort) et réponses plafonnées (max_tokens).

Garde-fous (config.yaml > claude) : plafond mensuel et plafond total, calculés sur le coût de
chaque appel enregistré dans le journal (table runs) depuis l'achat du crédit. Le solde exact
reste celui de la console Anthropic (Billing).
"""
import copy
from datetime import datetime

from .config import secret

# Dollars par million de tokens : entrée, sortie (réflexion comprise), écriture du cache (5 min), lecture du cache.
PRIX = {
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.10),
}
PRIX_INCONNU = PRIX["claude-sonnet-5-5"]   # modèle absent du tableau : on compte large
MAX_TOKENS_PAR_DEFAUT = 8000
CLES_USAGE = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


class ErreurClaude(Exception):
    """Message affichable tel quel (sans la clé). `usage` : tokens facturés malgré l'échec, s'il y en a."""

    def __init__(self, message: str, usage: dict | None = None):
        super().__init__(message)
        self.usage = usage


def est_claude(modele: str) -> bool:
    return modele.startswith("claude")


# =========================================================================== coûts et plafonds

def cout(modele: str, usage: dict) -> float:
    """Coût en dollars d'un appel, d'après son usage (tokens normaux, cache écrit, cache lu)."""
    entree, sortie, ecriture, lecture = PRIX.get(modele, PRIX_INCONNU)
    return ((usage.get("input_tokens", 0) or 0) * entree
            + (usage.get("output_tokens", 0) or 0) * sortie
            + (usage.get("cache_creation_input_tokens", 0) or 0) * ecriture
            + (usage.get("cache_read_input_tokens", 0) or 0) * lecture) / 1_000_000


def reglages(config: dict) -> dict:
    return {"credit_usd": 5.0, "plafond_mensuel_usd": 1.0, "plafond_total_usd": 4.5,
            "credit_depuis": "2026-11-19", **(config.get("claude") or {})}


def depenses(conn, config: dict) -> dict:
    """Dépenses Claude depuis l'achat du crédit : {'total', 'mois'} en dollars (Gemini compte 0)."""
    r = reglages(config)
    depuis = str(r["credit_depuis"])
    debut_mois = max(depuis, datetime.now().strftime("%Y-%m-01"))
    somme = "SELECT COALESCE(SUM(cout_usd), 0) FROM runs WHERE date_debut >= ?"
    return {"total": conn.execute(somme, (depuis,)).fetchone()[0],
            "mois": conn.execute(somme, (debut_mois,)).fetchone()[0]}


def blocage(conn, config: dict) -> str | None:
    """Pourquoi Claude ne doit pas être appelé (pas de clé, plafond atteint), ou None si c'est permis."""
    if not secret("ANTHROPIC_API_KEY"):
        return "pas de clé ANTHROPIC_API_KEY dans .env"
    r, d = reglages(config), depenses(conn, config)
    if d["total"] >= r["plafond_total_usd"]:
        return f"plafond total de Claude atteint ({d['total']:.2f} $ sur {r['plafond_total_usd']:.2f} $)"
    if d["mois"] >= r["plafond_mensuel_usd"]:
        return f"plafond du mois atteint ({d['mois']:.2f} $ sur {r['plafond_mensuel_usd']:.2f} $)"
    return None


# =========================================================================== format des réponses

def schema_strict(schema: dict) -> dict:
    """Adapte un schéma JSON aux réponses structurées de Claude.

    Chaque objet reçoit additionalProperties: false ; « type: [x, null] » devient anyOf ;
    les contraintes non acceptées (minimum, maxItems...) sont retirées (le code vérifie après).
    """
    retirees = {"minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength", "multipleOf"}

    def adapter(noeud):
        if isinstance(noeud, list):
            return [adapter(n) for n in noeud]
        if not isinstance(noeud, dict):
            return noeud
        noeud = {k: adapter(v) for k, v in noeud.items() if k not in retirees}
        if isinstance(noeud.get("type"), list):
            types = noeud.pop("type")
            description = noeud.pop("description", None)
            noeud = {"anyOf": [{**noeud, "type": t} if t != "null" else {"type": "null"} for t in types]}
            if description:
                noeud["description"] = description
        if noeud.get("type") == "object":
            noeud["additionalProperties"] = False
        return noeud

    return adapter(copy.deepcopy(schema))


# =========================================================================== client

class ClientClaude:
    """Même interface que gemini.ClientGemini.appeler : renvoie (contenu au format Gemini, usage)."""

    def __init__(self, cle: str | None = None, timeout: float = 90, max_tokens: int = MAX_TOKENS_PAR_DEFAUT):
        import anthropic
        cle = cle or secret("ANTHROPIC_API_KEY")
        if not cle:
            raise ErreurClaude("ajoute ANTHROPIC_API_KEY dans .env")
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=cle, timeout=timeout, max_retries=1)
        self.max_tokens = max_tokens

    def appeler(self, modele: str, systeme: str, contents: list[dict], schema: dict | None = None,
                reflexion: str | None = None, outils=None) -> tuple[dict, dict]:
        """Un appel. `contents` au format Gemini (role user/model, parts[].text)."""
        a = self._anthropic
        messages = [{"role": "assistant" if c["role"] == "model" else "user",
                     "content": "".join(p.get("text", "") for p in c["parts"])} for c in contents]
        output_config = {}
        if reflexion:
            output_config["effort"] = reflexion
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema_strict(schema)}
        try:
            r = self.client.messages.create(
                model=modele, max_tokens=self.max_tokens, messages=messages,
                # la partie fixe (consignes, CV, offre) est gardée en cache 5 min : relue à ~10 % du prix
                system=[{"type": "text", "text": systeme, "cache_control": {"type": "ephemeral"}}],
                **({"output_config": output_config} if output_config else {}))
        except a.AuthenticationError as e:
            raise ErreurClaude("clé ANTHROPIC_API_KEY refusée : vérifie-la dans .env") from e
        except a.PermissionDeniedError as e:
            raise ErreurClaude("accès refusé par Anthropic (403)") from e
        except a.RateLimitError as e:
            raise ErreurClaude("trop de requêtes vers Claude (429) : réessaie dans une minute") from e
        except a.BadRequestError as e:
            if "credit" in str(e).lower():
                raise ErreurClaude("crédit Anthropic épuisé : Gemini prend le relais") from e
            raise ErreurClaude(f"requête refusée par Claude (400) : {getattr(e, 'message', e)}") from e
        except a.APIStatusError as e:
            raise ErreurClaude(f"Claude indisponible ({e.status_code})") from e
        except a.APIConnectionError as e:
            raise ErreurClaude("Claude injoignable (réseau ou délai dépassé)") from e

        usage = {k: getattr(r.usage, k, 0) or 0 for k in CLES_USAGE}
        if r.stop_reason == "refusal":
            raise ErreurClaude("Claude a refusé de répondre", usage)
        if r.stop_reason == "max_tokens":
            raise ErreurClaude("réponse de Claude coupée (trop longue)", usage)
        texte = "".join(b.text for b in r.content if b.type == "text")
        return {"role": "model", "parts": [{"text": texte}]}, usage
