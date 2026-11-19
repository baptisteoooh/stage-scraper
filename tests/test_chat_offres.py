"""Tests de l'assistant (chat sur les offres) avec un faux client Gemini (aucun appel réel)."""
import json
from contextlib import closing

import pytest

from stage_scraper import chat_offres, db, gemini, requetes, traitement
from stage_scraper.config import charger_config
from stage_scraper.offre import nouvelle_offre

CONFIG = charger_config()
USAGE = {"promptTokenCount": 3000, "candidatesTokenCount": 120}


def texte(reponse="ok", offres=()):
    return {"role": "model", "parts": [{"text": json.dumps({"reponse": reponse, "offres": list(offres)})}]}


def outil(nom, **args):
    return {"role": "model", "parts": [{"functionCall": {"name": nom, "args": args}}]}


class FauxClient:
    """Rend les réponses prévues, une par appel (la dernière est répétée), et garde ce qu'on lui a envoyé."""

    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.appels = []

    def appeler(self, modele, systeme, contents, schema=None, reflexion=None, outils=None):
        self.appels.append(dict(modele=modele, systeme=systeme, contents=json.loads(json.dumps(contents)),
                                outils=outils))
        reponse = self.reponses.pop(0) if len(self.reponses) > 1 else self.reponses[0]
        if isinstance(reponse, Exception):
            raise reponse
        return reponse, USAGE


def base(tmp_path):
    conn = db.connecter(tmp_path / "t.db")
    db.initialiser(conn)
    offres = [nouvelle_offre(source="test", source_id=str(i), titre=titre, entreprise=entreprise, lieu="Paris",
                             date_publication="2026-11-10", description=description)
              for i, (titre, entreprise, description) in enumerate([
                  ("Stage Computer Vision imagerie médicale", "Gleamer", "Missions : PyTorch, segmentation, DICOM."),
                  ("Stage Data Analyst", "Doctolib", "SQL et tableaux de bord.")])]
    db.enregistrer_offres(conn, offres, passage_id=1)
    traitement.traiter(conn, CONFIG)
    return conn


def ids(conn):
    return [r[0] for r in conn.execute("SELECT id FROM offres ORDER BY id")]


def test_offres_choisies_verifiees_dans_la_base(tmp_path):
    with closing(base(tmp_path)) as conn:
        a, b = ids(conn)
        client = FauxClient(texte("Deux pistes.", [{"id": a, "raison": "Vision en santé."},
                                                   {"id": 9999, "raison": "offre inventée"},
                                                   {"id": a, "raison": "en double"},
                                                   {"id": b, "raison": "Data chez Doctolib."}]))
        r = chat_offres.demander(conn, CONFIG, "computer vision", client=client)
        assert r["reponse"] == "Deux pistes."
        assert [o["id"] for o in r["offres"]] == [a, b]       # l'offre inventée et le doublon sont écartés
        assert r["offres"][0]["titre"] == "Stage Computer Vision imagerie médicale"   # titre de la base
        assert r["offres"][0]["raison"] == "Vision en santé."
        assert r["ignores"] == 1
        systeme = client.appels[0]["systeme"]
        assert "<offres>" in systeme and "Gleamer" in systeme and "N'invente jamais" in systeme
        run = conn.execute("SELECT * FROM runs WHERE source = 'chat'").fetchone()
        assert run["nb_requetes"] == 1 and run["tokens_entree"] == 3000


def test_lit_l_offre_avant_de_repondre(tmp_path):
    with closing(base(tmp_path)) as conn:
        a, _ = ids(conn)
        client = FauxClient(outil("lire_offres", ids=[a, 12345]), texte("Il te faut PyTorch et DICOM."))
        r = chat_offres.demander(conn, CONFIG, "quelles compétences pour le stage Gleamer ?", client=client)
        assert r["reponse"] == "Il te faut PyTorch et DICOM." and r["offres"] == []
        assert r["lues"] == ["Stage Computer Vision imagerie médicale — Gleamer"]
        # 2e appel : l'appel d'outil puis sa réponse, avec la description complète
        contents = client.appels[1]["contents"]
        assert contents[-2]["parts"][0]["functionCall"]["name"] == "lire_offres"
        fiches = contents[-1]["parts"][0]["functionResponse"]["response"]["offres"]
        assert "DICOM" in fiches[0]["description"] and fiches[1] == {"id": 12345, "erreur": "offre inconnue"}
        assert conn.execute("SELECT nb_requetes FROM runs WHERE source = 'chat'").fetchone()[0] == 2


def test_mes_candidatures(tmp_path):
    with closing(base(tmp_path)) as conn:
        requetes.creer_candidature(conn, ids(conn)[0])
        client = FauxClient(outil("mes_candidatures"), texte("Une candidature en cours."))
        chat_offres.demander(conn, CONFIG, "où en sont mes candidatures ?", client=client)
        reponse = client.appels[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]
        assert reponse["candidatures"][0]["entreprise"] == "Gleamer"


def test_nombre_de_tours_limite(tmp_path):
    with closing(base(tmp_path)) as conn:
        client = FauxClient(*[outil("lire_offres", ids=[ids(conn)[0]])] * chat_offres.TOURS_MAX, texte("Fini."))
        assert chat_offres.demander(conn, CONFIG, "x", client=client)["reponse"] == "Fini."
        assert client.appels[-1]["outils"] is None             # dernier tour : réponse obligatoire
        assert len(client.appels) == chat_offres.TOURS_MAX + 1


def test_historique_en_tours_de_parole(tmp_path):
    with closing(base(tmp_path)) as conn:
        client = FauxClient(texte())
        historique = [{"role": "assistant", "texte": "message orphelin"},
                      {"role": "user", "texte": "de la data"},
                      {"role": "assistant", "texte": "Voici.", "ids": [2]}]
        chat_offres.demander(conn, CONFIG, "plutôt à Paris", historique, client=client)
        contents = client.appels[0]["contents"]
        assert [c["role"] for c in contents] == ["user", "model", "user"]
        assert "offres montrées : id=2" in contents[1]["parts"][0]["text"]
        assert contents[-1]["parts"][-1]["text"] == "plutôt à Paris"


def test_erreurs(tmp_path):
    with closing(base(tmp_path)) as conn:
        illisible = {"role": "model", "parts": [{"text": "pas du json"}]}
        with pytest.raises(chat_offres.ChatImpossible, match="illisible"):
            chat_offres.demander(conn, CONFIG, "x", client=FauxClient(illisible))
        with pytest.raises(chat_offres.ChatImpossible, match="quota"):
            chat_offres.demander(conn, CONFIG, "x", client=FauxClient(
                gemini.ErreurGemini("quota gratuit de Gemini atteint (429)", bloquante=True)))
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE source = 'chat' AND erreurs IS NOT NULL").fetchone()[0] == 1


def test_sans_offres(tmp_path):
    conn = db.connecter(tmp_path / "vide.db")
    db.initialiser(conn)
    with closing(conn):
        assert "scrap" in chat_offres.demander(conn, CONFIG, "x", client=FauxClient(texte()))["reponse"]
