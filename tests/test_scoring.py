"""Tests du scoring IA avec un faux client Claude (aucun appel réel, aucun coût)."""
from contextlib import closing
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from stage_scraper import db, scoring, traitement
from stage_scraper.config import charger_config
from stage_scraper.offre import nouvelle_offre

CONFIG = charger_config()


def notation(**champs):
    valeurs = dict(score=9, section="Santé", resume="Stage ML sur l'imagerie.", pourquoi="IA + medtech.",
                   duree="4 mois", date_debut="avril 2027", exclusion=None, poste_ia_data=True)
    valeurs.update(champs)
    return scoring.Notation(**valeurs)


USAGE = SimpleNamespace(input_tokens=500, cache_read_input_tokens=1500, cache_creation_input_tokens=0, output_tokens=200)


class FauxClient:
    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = []
        self.messages = self

    def parse(self, **parametres):
        self.appels.append(parametres)
        reponse = self.reponses.pop(0)
        if isinstance(reponse, Exception):
            raise reponse
        return reponse


def reponse(n=None, stop_reason="end_turn"):
    return SimpleNamespace(parsed_output=n, stop_reason=stop_reason, usage=USAGE)


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
        # Coût : 2 appels x (500 x 0,10 + 1500 x 0,01 + 200 x 0,50) / 1 000 000
        assert bilan["cout_usd"] == pytest.approx(2 * (500 * 0.10 + 1500 * 0.01 + 200 * 0.50) / 1e6)
        run = conn.execute("SELECT * FROM runs WHERE source = 'scoring'").fetchone()
        assert run["tokens_entree"] == 4000 and run["tokens_sortie"] == 400 and run["cout_usd"] > 0
        # Les offres déjà notées ne sont pas renotées
        assert scoring.noter_nouvelles(conn, CONFIG, 2, False, client=FauxClient([]))["notees"] == 0


def test_parametres_envoyes(tmp_path):
    with closing(base(tmp_path, nb=1)) as conn:
        client = FauxClient([reponse(notation())])
        scoring.noter_nouvelles(conn, CONFIG, 1, False, client=client)
        appel = client.appels[0]
        assert appel["model"] == "claude-haiku-5-5"
        assert appel["output_format"] is scoring.Notation
        assert "temperature" not in appel                     # refusé par Haiku 5.5
        assert appel["system"][-1]["cache_control"] == {"type": "ephemeral"}
        assert "Stage Machine Learning 0" in appel["messages"][0]["content"]


def test_refus_et_erreur_ne_bloquent_pas(tmp_path):
    with closing(base(tmp_path, nb=3)) as conn:
        erreur = anthropic.BadRequestError("requête invalide", response=httpx2.Response(
            400, request=httpx2.Request("POST", "https://api.anthropic.com")), body=None)
        client = FauxClient([reponse(None, "refusal"), erreur, reponse(notation())])
        bilan = scoring.noter_nouvelles(conn, CONFIG, 1, False, client=client)
        assert bilan["notees"] == 1 and len(bilan["erreurs"]) == 2


def test_cle_refusee_arrete_tout(tmp_path):
    with closing(base(tmp_path, nb=3)) as conn:
        erreur = anthropic.AuthenticationError("clé invalide", response=httpx2.Response(
            401, request=httpx2.Request("POST", "https://api.anthropic.com")), body=None)
        client = FauxClient([erreur])
        bilan = scoring.noter_nouvelles(conn, CONFIG, 1, False, client=client)
        assert bilan["notees"] == 0 and "ANTHROPIC_API_KEY" in bilan["erreurs"][0]
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
    monkeypatch.setattr(scoring, "secret", lambda nom: None)
    with closing(base(tmp_path, nb=1)) as conn:
        bilan = scoring.noter_nouvelles(conn, CONFIG, 1, False)
        assert "ANTHROPIC_API_KEY" in bilan["message"]


def test_exemples_pas_interesse_dans_le_prompt(tmp_path):
    with closing(base(tmp_path, nb=1)) as conn:
        conn.execute("INSERT INTO feedback (offre_id, raison) VALUES (1, 'trop orienté finance')")
        systeme = scoring.prompt_systeme(conn, CONFIG)[0]["text"]
        assert "PAS INTÉRESSÉ" in systeme and "trop orienté finance" in systeme
