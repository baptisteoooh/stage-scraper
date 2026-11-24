"""Tests du scoring IA avec un faux client Gemini (aucun appel réel, aucun coût)."""
from contextlib import closing

import pytest
import requests

from stage_scraper import db, gemini, ia, scoring, traitement
from stage_scraper.config import charger_config
from stage_scraper.offre import nouvelle_offre

CONFIG = charger_config()


def notation(**champs):
    valeurs = dict(score=9, section="Santé", resume="Stage ML sur l'imagerie.", pourquoi="IA + medtech.",
                   duree="4 mois", date_debut="avril 2027", exclusion=None, poste_ia_data=True)
    valeurs.update(champs)
    return scoring.Notation(**valeurs)


USAGE = {"promptTokenCount": 2000, "candidatesTokenCount": 150, "thoughtsTokenCount": 50}


class FauxClient:
    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = []

    def generer(self, modele, systeme, parties, schema=None, reflexion=None):
        self.appels.append(dict(modele=modele, systeme=systeme, parties=parties, schema=schema, reflexion=reflexion))
        reponse = self.reponses.pop(0)
        if isinstance(reponse, Exception):
            raise reponse
        return reponse


def reponse(n=None):
    """Réponse de Gemini : le JSON de la notation, ou un texte illisible si n est None."""
    return (n.model_dump_json() if n else "désolé, je ne peux pas"), USAGE


def base(tmp_path, nb=2):
    conn = db.connecter(tmp_path / "t.db")
    db.initialiser(conn)
    offres = [nouvelle_offre(source="test", source_id=str(i), titre=f"Stage Machine Learning {i}",
                             entreprise=f"Medtech {i}", lieu="Paris", date_publication="2026-10-20")
              for i in range(nb)]
    db.enregistrer_offres(conn, offres, passage_id=1)
    traitement.traiter(conn, CONFIG)
    return conn


def test_note_et_enregistre(tmp_path):
    with closing(base(tmp_path)) as conn:
        client = FauxClient([reponse(notation(score=9)), reponse(notation(score=6, section="Hors santé mais intéressant"))])
        bilan = scoring.noter_nouvelles(conn, CONFIG, passage_id=1, auto=False, client=client)
        assert bilan["notees"] == 2 and not bilan["erreurs"]
        lignes = conn.execute("SELECT score, categorie, section, poste_ia_data FROM offres ORDER BY id").fetchall()
        assert [tuple(l) for l in lignes] == [(9, "À postuler vite", "Santé", 1),
                                               (6, "À regarder", "Hors santé mais intéressant", 1)]
        assert bilan["cout_usd"] == 0   # offre gratuite de Gemini
        run = conn.execute("SELECT * FROM runs WHERE source = 'scoring'").fetchone()
        assert run["tokens_entree"] == 4000 and run["tokens_sortie"] == 400
        # Les offres déjà notées ne sont pas renotées
        assert scoring.noter_nouvelles(conn, CONFIG, 2, False, client=FauxClient([]))["notees"] == 0


def test_modele_qui_a_note_enregistre(tmp_path):
    """Gemini par défaut ; le modèle de secours de la cascade quand c'est lui qui a répondu."""
    with closing(base(tmp_path)) as conn:
        secours = (notation().model_dump_json(), {**USAGE, "modele": "cloudflare/@cf/google/gemma-4-26b-a4b-it"})
        scoring.noter_nouvelles(conn, CONFIG, 1, False, client=FauxClient([reponse(notation()), secours]))
        assert [l[0] for l in conn.execute("SELECT modele_ia FROM offres ORDER BY id")] == [
            CONFIG["scoring"]["modele"], "cloudflare/@cf/google/gemma-4-26b-a4b-it"]


def test_parametres_envoyes(tmp_path):
    with closing(base(tmp_path, nb=1)) as conn:
        client = FauxClient([reponse(notation())])
        scoring.noter_nouvelles(conn, CONFIG, 1, False, client=client)
        appel = client.appels[0]
        assert appel["modele"] == CONFIG["scoring"]["modele"]
        assert appel["schema"]["properties"]["score"]["maximum"] == 10
        assert "PROFIL" in appel["systeme"]
        texte = appel["parties"][-1]["text"]
        assert texte.startswith("<offre>") and "Stage Machine Learning 0" in texte


def test_reponse_illisible_et_erreur_ne_bloquent_pas(tmp_path):
    with closing(base(tmp_path, nb=3)) as conn:
        client = FauxClient([reponse(None), gemini.ErreurGemini("erreur 400 : requête invalide"), reponse(notation())])
        bilan = scoring.noter_nouvelles(conn, CONFIG, 1, False, client=client)
        assert bilan["notees"] == 1 and len(bilan["erreurs"]) == 2


def test_cle_refusee_arrete_tout(tmp_path):
    with closing(base(tmp_path, nb=3)) as conn:
        erreur = gemini.ErreurGemini("clé GEMINI_API_KEY refusée : vérifie-la dans .env", bloquante=True)
        client = FauxClient([erreur])
        bilan = scoring.noter_nouvelles(conn, CONFIG, 1, False, client=client)
        assert bilan["notees"] == 0 and "GEMINI_API_KEY" in bilan["erreurs"][0]
        assert len(client.appels) == 1   # on n'insiste pas


def test_budget_mensuel(tmp_path):
    with closing(base(tmp_path, nb=2)) as conn:
        db.journaliser_run(conn, passage_id=1, date_debut=scoring._maintenant(), declenchement="manuel",
                           source="scoring", cout_usd=CONFIG["scoring"]["budget_mensuel_usd"])
        client = FauxClient([reponse(notation())])
        bilan = scoring.noter_nouvelles(conn, CONFIG, 2, False, client=client)
        assert bilan["notees"] == 0 and "budget" in bilan["message"]
        assert client.appels == []


def test_sans_cle(tmp_path, monkeypatch):
    monkeypatch.setattr(ia, "secret", lambda nom: None)   # aucune IA branchée
    with closing(base(tmp_path, nb=1)) as conn:
        bilan = scoring.noter_nouvelles(conn, CONFIG, 1, False)
        assert "GEMINI_API_KEY" in bilan["message"]


def test_exemples_pas_interesse_dans_le_prompt(tmp_path):
    with closing(base(tmp_path, nb=1)) as conn:
        conn.execute("INSERT INTO feedback (offre_id, raison) VALUES (1, 'trop orienté finance')")
        systeme = scoring.prompt_systeme(conn, CONFIG)[0]["text"]
        assert "PAS INTÉRESSÉ" in systeme and "trop orienté finance" in systeme


class FausseReponse:
    def __init__(self, code, donnees):
        self.status_code, self._donnees, self.ok, self.text = code, donnees, code == 200, str(donnees)

    def json(self):
        return self._donnees


def test_client_gemini_reessaie_si_surcharge(monkeypatch):
    reponses = [FausseReponse(503, {"error": {"message": "high demand"}}),
                FausseReponse(200, {"candidates": [{"content": {"parts": [{"text": '{"a": 1}'}]}}],
                                    "usageMetadata": USAGE})]
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    monkeypatch.setattr(gemini.requests, "post", lambda *a, **k: reponses.pop(0))
    client = gemini.ClientGemini(cle="test", delai_entre_appels=0)
    assert client.generer("m", "consignes", [gemini.partie_texte("x")]) == ('{"a": 1}', USAGE)


@pytest.mark.parametrize("code, morceau", [(401, "GEMINI_API_KEY"), (429, "quota"), (404, "introuvable"), (503, "surchargé")])
def test_client_gemini_erreurs_bloquantes(monkeypatch, code, morceau):
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    monkeypatch.setattr(gemini.requests, "post", lambda *a, **k: FausseReponse(code, {"error": {"message": "x"}}))
    with pytest.raises(gemini.ErreurGemini, match=morceau) as e:
        gemini.ClientGemini(cle="test", delai_entre_appels=0).generer("m", "s", [gemini.partie_texte("x")])
    assert e.value.bloquante


def test_client_gemini_reseau_coupe(monkeypatch):
    def coupe(*a, **k):
        raise requests.ConnectionError("pas de réseau")
    monkeypatch.setattr(gemini.requests, "post", coupe)
    with pytest.raises(gemini.ErreurGemini, match="injoignable"):
        gemini.ClientGemini(cle="test", delai_entre_appels=0).generer("m", "s", [gemini.partie_texte("x")])


def test_client_gemini_patiente_sur_limite_par_minute(monkeypatch):
    limite = {"error": {"message": "quota", "details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "0s"}]}}
    reponses = [FausseReponse(429, limite),
                FausseReponse(200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}], "usageMetadata": {}})]
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    monkeypatch.setattr(gemini.requests, "post", lambda *a, **k: reponses.pop(0))
    assert gemini.ClientGemini(cle="test", delai_entre_appels=0).generer("m", "s", [gemini.partie_texte("x")])[0] == "ok"
