"""Tests des lettres de motivation avec un faux client Claude (aucun appel réel, aucun coût)."""
from contextlib import closing
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from stage_scraper import db, lettre, requetes
from stage_scraper.config import charger_config
from stage_scraper.offre import nouvelle_offre

CONFIG = charger_config()
USAGE = SimpleNamespace(input_tokens=2000, cache_read_input_tokens=0, cache_creation_input_tokens=0, output_tokens=900)


class FauxClient:
    def __init__(self, reponse):
        self.reponse, self.appels = reponse, []
        self.messages = self

    def create(self, **parametres):
        self.appels.append(parametres)
        if isinstance(self.reponse, Exception):
            raise self.reponse
        return self.reponse


def reponse(texte="Madame, Monsieur,\n\nJe souhaite…", stop_reason="end_turn"):
    blocs = [SimpleNamespace(type="thinking", thinking="…"), SimpleNamespace(type="text", text=texte)]
    return SimpleNamespace(content=blocs, stop_reason=stop_reason, usage=USAGE)


def base(tmp_path):
    conn = db.connecter(tmp_path / "t.db")
    db.initialiser(conn)
    db.enregistrer_offres(conn, [nouvelle_offre(
        source="test", source_id="1", titre="ML Engineer Intern", entreprise="Doctolib", lieu="Levallois-Perret",
        date_publication="2026-10-20", description="Tu travailleras sur des modèles de NLP médical.")], passage_id=1)
    return conn


def test_redige_et_journalise(tmp_path):
    with closing(base(tmp_path)) as conn:
        client = FauxClient(reponse())
        resultat = lettre.rediger(conn, CONFIG, requetes.offre(conn, 1), "insister sur Python", client=client)
        assert resultat["texte"].startswith("Madame, Monsieur")  # le bloc de réflexion est ignoré
        appel = client.appels[0]
        assert appel["model"] == "claude-haiku-5-5" and "temperature" not in appel
        message = appel["messages"][0]["content"]
        message = message if isinstance(message, str) else message[-1]["text"]
        assert "NLP médical" in message and "insister sur Python" in message
        assert "n'invente jamais" in appel["system"].lower()
        run = conn.execute("SELECT * FROM runs WHERE source = 'lettre'").fetchone()
        assert run["tokens_entree"] == 2000 and run["cout_usd"] == pytest.approx((2000 * 0.10 + 900 * 0.50) / 1e6)
        assert requetes.couts_ia(conn)["mois"] == pytest.approx(run["cout_usd"])


def test_garder_dans_la_candidature(tmp_path):
    with closing(base(tmp_path)) as conn:
        requetes.enregistrer_lettre(conn, 1, "Ma lettre")
        c = requetes.candidature_de(conn, 1)
        assert c["lettre"] == "Ma lettre" and c["entreprise"] == "Doctolib"
        requetes.enregistrer_lettre(conn, 1, "Version 2")
        assert len(requetes.candidatures(conn)) == 1 and requetes.candidature_de(conn, 1)["lettre"] == "Version 2"


def test_erreurs_claires(tmp_path, monkeypatch):
    with closing(base(tmp_path)) as conn:
        offre = requetes.offre(conn, 1)
        erreur = anthropic.AuthenticationError("clé invalide", response=httpx2.Response(
            401, request=httpx2.Request("POST", "https://api.anthropic.com")), body=None)
        with pytest.raises(lettre.LettreImpossible, match="ANTHROPIC_API_KEY"):
            lettre.rediger(conn, CONFIG, offre, client=FauxClient(erreur))
        with pytest.raises(lettre.LettreImpossible, match="pas rédigé"):
            lettre.rediger(conn, CONFIG, offre, client=FauxClient(reponse("", "refusal")))
        monkeypatch.setattr(lettre, "secret", lambda nom: None)
        with pytest.raises(lettre.LettreImpossible, match="ANTHROPIC_API_KEY"):
            lettre.rediger(conn, CONFIG, offre)


def test_budget_commun_avec_le_scoring(tmp_path):
    with closing(base(tmp_path)) as conn:
        db.journaliser_run(conn, passage_id=1, date_debut=lettre._maintenant(), declenchement="manuel",
                           source="scoring", cout_usd=CONFIG["scoring"]["budget_mensuel_usd"])
        client = FauxClient(reponse())
        with pytest.raises(lettre.LettreImpossible, match="budget"):
            lettre.rediger(conn, CONFIG, requetes.offre(conn, 1), client=client)
        assert client.appels == []
