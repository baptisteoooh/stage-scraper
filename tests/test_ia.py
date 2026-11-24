"""Tests de la cascade d'IA (ia.py) avec de fausses réponses HTTP : aucun appel réel."""
import json

import pytest
import requests

from stage_scraper import config as config_module
from stage_scraper import gemini, ia

SCHEMA = {"type": "object", "properties": {"score": {"type": "integer"}}, "required": ["score"]}


class FausseReponse:
    def __init__(self, code=200, corps=None, entetes=None):
        self.status_code, self._corps, self.headers = code, corps or {}, entetes or {}
        self.ok = code < 400
        self.text = json.dumps(self._corps)

    def json(self):
        return self._corps


def openai(texte=None, appels=None, entree=100, sortie=20):
    message = {"role": "assistant", "content": texte}
    if appels:
        message["tool_calls"] = [{"id": f"t{i}", "type": "function",
                                  "function": {"name": n, "arguments": json.dumps(a)}} for i, (n, a) in enumerate(appels)]
    return FausseReponse(200, {"choices": [{"message": message}],
                               "usage": {"prompt_tokens": entree, "completion_tokens": sortie}})


@pytest.fixture
def cles(monkeypatch):
    """Cloudflare et Groq branchés, pas de Gemini ; quotas remis à zéro."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "compte123")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "jeton-cf")
    monkeypatch.setenv("GROQ_API_KEY", "cle-groq")
    monkeypatch.setattr(ia, "_EPUISES", {})
    monkeypatch.setattr(ia.time, "sleep", lambda s: None)


@pytest.fixture
def reseau(monkeypatch):
    """Faux requests.post : rend les réponses prévues pour chaque fournisseur, dans l'ordre."""
    prevues = {"cloudflare": [], "groq": []}
    envoyes = []

    def post(url, json=None, headers=None, timeout=None):
        nom = "cloudflare" if "cloudflare" in url else "groq"
        envoyes.append((nom, url, json, headers))
        return prevues[nom].pop(0)

    monkeypatch.setattr(ia.requests, "post", post)
    return prevues, envoyes


def test_premier_fournisseur_repond(cles, reseau):
    prevues, envoyes = reseau
    prevues["cloudflare"].append(openai('{"score": 7}'))
    c = ia.client()
    texte, usage = c.generer("gemini-3.5-flash-lite", "consignes", [{"text": "offre"}], schema=SCHEMA)
    assert json.loads(texte) == {"score": 7}
    assert usage == {"promptTokenCount": 100, "candidatesTokenCount": 20,
                     "modele": "cloudflare/@cf/google/gemma-4-26b-a4b-it"}
    nom, url, corps, entetes = envoyes[0]
    assert url == "https://api.cloudflare.com/client/v4/accounts/compte123/ai/v1/chat/completions"
    assert entetes["Authorization"] == "Bearer jeton-cf"
    assert corps["model"] == "@cf/google/gemma-4-26b-a4b-it"
    assert corps["chat_template_kwargs"] == {"enable_thinking": False}     # réflexion coupée
    assert corps["response_format"]["json_schema"]["schema"] == SCHEMA
    assert corps["messages"] == [{"role": "system", "content": "consignes"}, {"role": "user", "content": "offre"}]


def test_quota_du_jour_passe_au_suivant_et_s_en_souvient(cles, reseau):
    prevues, envoyes = reseau
    prevues["cloudflare"].append(FausseReponse(429, {"errors": [{"message": "you have used up your daily free allocation of 10,000 neurons"}]}))
    prevues["groq"] += [openai('{"score": 5}'), openai('{"score": 6}')]
    c = ia.client()
    assert c.generer("m", "s", [{"text": "o"}], schema=SCHEMA)[1]["modele"] == "groq/qwen/qwen3.8-27b"
    assert envoyes[-1][2]["reasoning_effort"] == "none"
    # offre suivante (même avec un nouveau client) : Cloudflare n'est plus redemandé aujourd'hui
    ia.client().generer("m", "s", [{"text": "o2"}], schema=SCHEMA)
    assert [e[0] for e in envoyes] == ["cloudflare", "groq", "groq"]


def test_limite_par_minute_on_patiente(cles, reseau):
    prevues, envoyes = reseau
    prevues["cloudflare"] += [FausseReponse(429, {"error": {"message": "rate limit"}}, {"retry-after": "12"}),
                              openai('{"score": 4}')]
    texte, usage = ia.client().generer("m", "s", [{"text": "o"}], schema=SCHEMA)
    assert usage["modele"].startswith("cloudflare/") and [e[0] for e in envoyes] == ["cloudflare", "cloudflare"]
    assert "cloudflare" not in ia._EPUISES


def test_json_illisible_redemande_puis_suivant(cles, reseau):
    prevues, envoyes = reseau
    prevues["cloudflare"] += [openai("désolé"), openai('{"score": ')]
    prevues["groq"].append(openai('{"score": 8}'))
    texte, usage = ia.client().generer("m", "s", [{"text": "o"}], schema=SCHEMA)
    assert json.loads(texte)["score"] == 8 and [e[0] for e in envoyes] == ["cloudflare", "cloudflare", "groq"]


def test_tous_en_panne_erreur_bloquante(cles, reseau):
    prevues, _ = reseau
    prevues["cloudflare"].append(FausseReponse(410, {"errors": [{"message": "Model has been deprecated"}]}))
    prevues["groq"].append(FausseReponse(401, {"error": {"message": "Invalid API Key"}}))
    with pytest.raises(gemini.ErreurGemini) as e:
        ia.client().generer("m", "s", [{"text": "o"}], schema=SCHEMA)
    assert e.value.bloquante and "groq refusée" in str(e.value)


def test_modele_retire_message_clair(cles, reseau):
    prevues, _ = reseau
    prevues["cloudflare"].append(FausseReponse(410, {"errors": [{"message": "Model has been deprecated"}]}))
    with pytest.raises(ia.ErreurIA, match="retiré chez cloudflare : change ia.cascade"):
        ia.ClientCompatible("cloudflare").appeler("@cf/vieux", "s", [{"role": "user", "parts": [{"text": "o"}]}])


def test_reseau_coupe(cles, monkeypatch):
    def coupe(*a, **k):
        raise requests.ConnectionError("pas de réseau")
    monkeypatch.setattr(ia.requests, "post", coupe)
    with pytest.raises(ia.ErreurIA, match="aucune IA disponible"):
        ia.client().generer("m", "s", [{"text": "o"}])


def test_gemini_d_abord_quand_sa_cle_est_la(cles, reseau, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "cle-gemini")
    appels = []

    def faux_gemini(self, modele, systeme, contents, schema=None, reflexion=None, outils=None, forcer_outil=False):
        appels.append((modele, reflexion))
        raise gemini.ErreurGemini("quota gratuit de Gemini atteint (429)", bloquante=True)

    monkeypatch.setattr(gemini.ClientGemini, "appeler", faux_gemini)
    reseau[0]["cloudflare"] += [openai('{"score": 3}'), openai('{"score": 2}')]
    c = ia.client()
    assert c.generer("gemini-3.5-flash-lite", "s", [{"text": "o"}], schema=SCHEMA, reflexion="low")[1]["modele"].startswith("cloudflare/")
    assert appels == [("gemini-3.5-flash-lite", "low")]
    c.generer("gemini-3.5-flash-lite", "s", [{"text": "o"}], schema=SCHEMA)
    assert len(appels) == 1   # quota de Gemini épuisé : plus redemandé aujourd'hui


def test_disponible_et_ordre_configurable(cles, monkeypatch):
    assert ia.disponible()
    config = {"ia": {"cascade": [{"fournisseur": "groq", "modele": "openai/gpt-oss-120b"}]}}
    assert [e["fournisseur"] for e in ia.client(config).etapes] == ["groq"]
    monkeypatch.delenv("GROQ_API_KEY")
    assert not ia.disponible(config)
    with pytest.raises(ia.ErreurIA, match="aucune IA branchée"):
        ia.client(config)


def test_outils_traduits_dans_les_deux_sens(cles, reseau):
    prevues, envoyes = reseau
    outils = [{"name": "chercher", "description": "cherche", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}]
    prevues["cloudflare"] += [openai(appels=[("chercher", {"q": "ml"})]), openai('{"reponse": "ok"}')]
    c = ia.client()
    contents = [{"role": "user", "parts": [{"text": "trouve"}]}]
    contenu, _ = c.appeler("m", "s", contents, schema=SCHEMA, outils=outils, forcer_outil=True)
    assert gemini.appels_outils(contenu) == [{"name": "chercher", "args": {"q": "ml"}, "id": "t0"}]
    corps = envoyes[0][2]
    assert corps["tool_choice"] == "required" and "response_format" not in corps
    assert corps["tools"][0]["function"]["name"] == "chercher"
    assert "objet JSON" in corps["messages"][0]["content"]          # le format est demandé dans les consignes
    # tour suivant : la réponse de l'outil est rattachée à l'appel par son identifiant
    contents += [contenu, {"role": "user", "parts": [{"functionResponse": {"name": "chercher", "response": {"n": 3}}}]}]
    c.appeler("m", "s", contents, schema=SCHEMA, outils=outils)
    messages = envoyes[1][2]["messages"]
    assert messages[2]["tool_calls"][0]["id"] == "t0"
    assert messages[3] == {"role": "tool", "tool_call_id": "t0", "content": '{"n": 3}'}


def test_les_amis_utilisent_les_cles_partagees_pas_le_gemini_de_bap(cles, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "cle-de-bap")
    (tmp_path / "cles.env").write_text("", encoding="utf-8")
    jeton = config_module.COMPTE.set(config_module.Compte("lea", dossier=tmp_path))
    try:
        assert [e["fournisseur"] for e in ia.client().etapes] == ["cloudflare", "groq"]   # pas de Gemini
    finally:
        config_module.COMPTE.reset(jeton)


def test_texte_libre_apres_les_outils_redemande_au_format(cles, reseau):
    prevues, envoyes = reseau
    outils = [{"name": "chercher", "parameters": {"type": "object", "properties": {}}}]
    prevues["cloudflare"] += [openai("### Voici les offres\n- **Stage DL**"), openai('{"score": 9}')]
    contenu, usage = ia.client().appeler("m", "s", [{"role": "user", "parts": [{"text": "q"}]}], schema=SCHEMA, outils=outils)
    assert json.loads(gemini.texte_de(contenu)) == {"score": 9}
    second = envoyes[1][2]
    assert second["tool_choice"] == "none" and second["response_format"]["json_schema"]["schema"] == SCHEMA
    assert usage["promptTokenCount"] == 200   # les deux requêtes comptées
