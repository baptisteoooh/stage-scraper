"""Comptes du site (mode --comptes) : mots de passe, sessions, invitations, et surtout l'étanchéité entre comptes
(chacun sa base, ses réglages, ses clés ; un ami ne voit jamais les données ni les clés de BAP)."""
import shutil
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from stage_scraper import collecte, comptes, config, db, reglages
from stage_scraper.sources import Contexte, careerjet
from stage_scraper.config import CHEMIN_CONFIG, COMPTE, Compte, secret
from stage_scraper.offre import nouvelle_offre
from stage_scraper.web import serveur

MDP = "un-bon-mot-de-passe"


@pytest.fixture
def dossier(tmp_path, monkeypatch):
    """Comptes, base et réglages de BAP : tout dans un dossier temporaire (jamais les vrais fichiers)."""
    monkeypatch.setenv("STAGE_SCRAPER_COMPTES_DOSSIER", str(tmp_path / "comptes"))
    copie = tmp_path / "config.yaml"
    shutil.copyfile(CHEMIN_CONFIG, copie)
    monkeypatch.setenv("STAGE_SCRAPER_CONFIG", str(copie))
    base = tmp_path / "bap.db"
    with closing(db.connecter(base)) as c:
        db.initialiser(c)
        db.enregistrer_offres(c, [
            nouvelle_offre(source="test", source_id="1", titre="Stage Data IA", entreprise="Doctolib", lieu="Paris"),
            nouvelle_offre(source="test", source_id="2", titre="Stage ML", entreprise="Owkin", lieu="Paris"),
            nouvelle_offre(source="test", source_id="3", titre="Stage retiré", entreprise="Acme", lieu="Paris"),
        ], passage_id=1)
        c.execute("UPDATE offres SET score = 9, favori = 1, pourquoi = 'avis de BAP' WHERE id = 1")
        c.execute("UPDATE offres SET expiration = 'retiree' WHERE id = 3")
        c.commit()
    monkeypatch.setenv("STAGE_SCRAPER_BASE", str(base))
    comptes._echecs.clear()
    # Careerjet : jamais le vrai (fausse clé, fausse IP, fausses recherches qui notent chaque appel)
    monkeypatch.setenv("CAREERJET_API_KEY", "fausse-cle-careerjet")
    monkeypatch.setattr(careerjet, "adresse_ip_publique", lambda: "203.0.113.7")
    appels = []

    def fausse_recherche(cle, requete, reglages, ip):
        appels.append(requete)
        return [nouvelle_offre(source="careerjet", source_id=f"cj-{requete}", titre=f"Stage {requete}", entreprise="Acme",
                               lieu="Paris")]
    monkeypatch.setattr(careerjet, "rechercher", fausse_recherche)
    monkeypatch.setattr(comptes, "_appels_careerjet_test", appels, raising=False)
    return tmp_path


# =========================================================================== module comptes

def test_premier_compte_puis_invitation(dossier):
    assert comptes.aucun_compte()
    bap = comptes.creer_admin("bap", MDP)
    assert bap.admin and bap.dossier is None                       # BAP garde les fichiers du projet
    with pytest.raises(comptes.CompteRefuse):
        comptes.creer_admin("autre", MDP)                          # un seul premier compte
    with pytest.raises(comptes.CompteRefuse, match="invitation"):
        comptes.creer_avec_invitation("faux-code", "lea", MDP)
    code = comptes.inviter()
    assert comptes.invitation_valable(code)
    for nom, mdp, message in [("Léa Martin", MDP, "Nom"), ("lea", "court", "8 caractères"), ("bap", MDP, "déjà pris")]:
        with pytest.raises(comptes.CompteRefuse, match=message):
            comptes.creer_avec_invitation(code, nom, mdp)
    lea = comptes.creer_avec_invitation(code, "Lea", MDP)
    assert lea.nom == "lea" and not lea.admin
    assert not comptes.invitation_valable(code)                    # usage unique
    with pytest.raises(comptes.CompteRefuse):
        comptes.creer_avec_invitation(code, "tom", MDP)
    # son dossier : réglages sans le profil de BAP, base prête, rien d'autre
    assert (lea.dossier / "stages.db").exists() and (lea.dossier / "profil").is_dir()
    p = reglages.lire(lea.config)["profil"]
    assert p["recherche"] == "" and "entretien_accueil" not in p and p["cv"] == "profil/cv.pdf"
    assert reglages.lire(lea.config)["notifications"]["envoi_actif"] is False


def test_mots_de_passe_et_sessions(dossier):
    comptes.creer_admin("bap", MDP)
    brut = (comptes.dossier_comptes() / "comptes.db").read_bytes()
    assert MDP.encode() not in brut                                # jamais le mot de passe en clair
    with pytest.raises(comptes.CompteRefuse, match="incorrect"):
        comptes.connecter("bap", "mauvais-mot-de-passe")
    with pytest.raises(comptes.CompteRefuse, match="incorrect"):
        comptes.connecter("inconnu", MDP)                          # même message : on ne dit pas qui existe
    jeton = comptes.connecter("BAP ", MDP)
    assert comptes.session(jeton).nom == "bap" and comptes.session("faux") is None
    assert jeton.encode() not in (comptes.dossier_comptes() / "comptes.db").read_bytes()   # seulement son empreinte
    comptes.fermer_session(jeton)
    assert comptes.session(jeton) is None
    comptes.changer_mot_de_passe("bap", MDP, "nouveau-mot-de-passe")
    assert comptes.session(comptes.connecter("bap", "nouveau-mot-de-passe"))


def test_trop_d_essais(dossier):
    comptes.creer_admin("bap", MDP)
    for _ in range(comptes.ESSAIS_MAX):
        with pytest.raises(comptes.CompteRefuse, match="incorrect"):
            comptes.connecter("bap", "faux-faux-faux")
    with pytest.raises(comptes.CompteRefuse, match="Trop d'essais"):
        comptes.connecter("bap", MDP)                              # même le bon, pendant la pause


def test_session_perimee(dossier, monkeypatch):
    from datetime import datetime, timedelta
    comptes.creer_admin("bap", MDP)
    jeton = comptes.connecter("bap", MDP)
    plus_tard = datetime.now() + comptes.DUREE_SESSION + timedelta(minutes=1)
    monkeypatch.setattr(comptes, "_maintenant", lambda: plus_tard)
    assert comptes.session(jeton) is None


def test_suppression(dossier):
    comptes.creer_admin("bap", MDP)
    lea = comptes.creer_avec_invitation(comptes.inviter(), "lea", MDP)
    with pytest.raises(comptes.CompteRefuse):
        comptes.supprimer("bap")
    comptes.supprimer("lea")
    assert comptes.compte("lea") is None and not lea.dossier.exists()


# =========================================================================== contexte : chemins et clés

def test_cles_et_chemins_d_un_ami(dossier, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "cle-de-bap-0123456789abcdef")
    monkeypatch.setenv("SERPAPI_API_KEY", "serpapi-de-bap")
    comptes.creer_admin("bap", MDP)
    lea = comptes.creer_avec_invitation(comptes.inviter(), "lea", MDP)
    jeton = COMPTE.set(lea)
    try:
        assert secret("GEMINI_API_KEY") is None                    # jamais la clé de BAP
        assert secret("SERPAPI_API_KEY") is None and secret("GMAIL_MOT_DE_PASSE_APPLI") is None
        with pytest.raises(comptes.CompteRefuse, match="format"):
            comptes.ecrire_cle(lea, "GEMINI_API_KEY", "pas une clé")
        comptes.ecrire_cle(lea, "GEMINI_API_KEY", "AIzaCleDeLea0123456789xyz")
        assert secret("GEMINI_API_KEY") == "AIzaCleDeLea0123456789xyz"
        assert config.chemin_projet("profil/cv.pdf") == lea.dossier / "profil" / "cv.pdf"
        assert config.charger_config()["profil"]["recherche"] == ""   # ses réglages à elle
        comptes.ecrire_cle(lea, "GEMINI_API_KEY", "")
        assert secret("GEMINI_API_KEY") is None
    finally:
        COMPTE.reset(jeton)
    assert secret("GEMINI_API_KEY") == "cle-de-bap-0123456789abcdef"
    assert comptes.cle_masquee("AIzaCleDeLea0123456789xyz") == "AIza…9xyz"


def test_collecte_commune(dossier, tmp_path):
    base_ami = tmp_path / "ami.db"
    with closing(db.connecter(base_ami)) as conn:
        db.initialiser(conn)
        passage, bilan = collecte.importer_commune(conn, dossier / "bap.db")
        lignes = {l["source_id"]: dict(l) for l in conn.execute("SELECT * FROM offres")}
        assert set(lignes) == {"1", "2"} and bilan[0]["nb_nouvelles"] == 2
        # les données brutes seulement : ni la note, ni le favori, ni l'avis de BAP
        assert lignes["1"]["score"] is None and lignes["1"]["favori"] == 0 and lignes["1"]["pourquoi"] is None
        assert conn.execute("SELECT source FROM runs").fetchone()[0] == "commune"
        # repassage : rien de neuf ; une offre retirée chez BAP l'est aussi chez l'ami
        with closing(db.connecter(dossier / "bap.db")) as bap:
            bap.execute("UPDATE offres SET expiration = 'retiree' WHERE id = 2")
            bap.commit()
        _, bilan = collecte.importer_commune(conn, dossier / "bap.db")
        assert bilan[0]["nb_nouvelles"] == 0 and bilan[0]["nb_expirees"] == 1
        assert conn.execute("SELECT expiration FROM offres WHERE source_id = '2'").fetchone()[0] == "retiree"


# =========================================================================== site en mode comptes

@pytest.fixture
def site(dossier, monkeypatch):
    monkeypatch.setenv("STAGE_SCRAPER_COMPTES", "1")
    with TestClient(serveur.app) as c:
        yield c


def _nouveau_client():
    return TestClient(serveur.app)


def test_site_ferme_sans_connexion(site):
    assert site.get("/").status_code == 200                       # l'accueil sert de page de connexion
    r = site.get("/a-trier", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert site.get("/api/a-trier").status_code == 401
    assert site.get("/api/compte").json() == {"mode": True, "connecte": False, "premier": True, "invitation": None}
    assert site.get("/statique/css/site.css").status_code == 200


def test_bap_puis_un_ami(site, dossier):
    # BAP crée le premier compte : il voit ses offres (sa base)
    r = site.post("/api/compte/inscription", json={"nom": "bap", "mot_de_passe": MDP})
    assert r.status_code == 200 and r.json()["admin"]
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=lax" in r.headers["set-cookie"].lower()
    assert {o["id"] for o in site.get("/api/a-trier").json()["offres"]} == {1, 2}
    lien = site.post("/api/compte/inviter").json()["lien"]
    code = lien.split("invitation=")[1]

    # Léa : invitation, son compte, sa base vide, ses réglages à elle
    lea = _nouveau_client()
    assert lea.get(f"/api/compte?invitation={code}").json()["invitation"] is True
    assert lea.post("/api/compte/inscription", json={"nom": "lea", "mot_de_passe": MDP, "code": "faux"}).status_code == 400
    assert lea.post("/api/compte/inscription", json={"nom": "lea", "mot_de_passe": MDP, "code": code}).status_code == 200
    moi = lea.get("/api/compte").json()
    assert moi["nom"] == "lea" and not moi["admin"] and moi["cles"] == {"gemini": None, "claude": None}
    assert lea.get("/api/a-trier").json()["offres"] == []
    assert lea.post("/api/compte/inviter").status_code == 403    # seul BAP invite
    r = lea.get("/a-trier", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/bienvenue"   # profil neuf : l'entretien d'abord

    # ses décisions et son profil ne touchent pas ceux de BAP
    config_bap = (dossier / "config.yaml").read_text(encoding="utf-8")
    assert lea.post("/api/profil", json={"valeurs": {"recherche": "Un stage en robotique"}}).status_code == 200
    assert (dossier / "config.yaml").read_text(encoding="utf-8") == config_bap
    assert "robotique" in (comptes.compte("lea").config).read_text(encoding="utf-8")

    # sa clé Gemini (vérifiée sans dépense ; ici la vérification est simulée)
    import stage_scraper.gemini as gemini
    gemini_cle_valable, gemini.cle_valable = gemini.cle_valable, lambda cle: True
    try:
        r = lea.post("/api/compte/cle", json={"cle": "gemini", "valeur": "AIzaCleDeLea0123456789xyz"}).json()
    finally:
        gemini.cle_valable = gemini_cle_valable
    assert r == {"ok": True, "masquee": "AIza…9xyz", "valable": True}
    assert "AIzaCleDeLea" not in str(lea.get("/api/compte").json())
    assert site.post("/api/compte/cle", json={"cle": "gemini", "valeur": "x" * 30}).status_code == 400   # BAP : .env

    # déconnexion
    assert lea.post("/api/compte/deconnexion").status_code == 200
    assert lea.get("/api/a-trier").status_code == 401
    assert lea.post("/api/compte/connexion", json={"nom": "lea", "mot_de_passe": "faux-faux-faux"}).status_code == 400
    assert lea.post("/api/compte/connexion", json={"nom": "lea", "mot_de_passe": MDP}).status_code == 200
    assert lea.get("/api/a-trier").status_code == 200


def test_sans_mode_comptes_rien_ne_change(dossier):
    with TestClient(serveur.app) as c:
        assert c.get("/api/compte").json() == {"mode": False}
        assert c.get("/api/a-trier").status_code == 200
        assert c.post("/api/compte/connexion", json={"nom": "bap", "mot_de_passe": MDP}).status_code == 404


def test_passage_automatique_des_amis(dossier, monkeypatch):
    """La tâche de 8 h : après le passage de BAP, chaque ami reçoit les offres (sans clé : pas encore notées)."""
    import run
    monkeypatch.setenv("GEMINI_API_KEY", "cle-de-bap-0123456789abcdef")   # ne doit jamais servir à un ami
    comptes.creer_admin("bap", MDP)
    lea = comptes.creer_avec_invitation(comptes.inviter(), "lea", MDP)
    reglages_lea = reglages.lire(lea.config)
    reglages_lea["recherches"]["requetes"] = ["stage finance de marché", "stage audit"]
    reglages.ecrire(reglages_lea, lea.config)
    lignes = run.passages_des_amis(dossier / "bap.db")
    # 2 offres partagées par BAP + 2 trouvées sur Careerjet avec SES recherches à elle
    assert len(lignes) == 1 and lignes[0].startswith("Compte lea : 4 nouvelle(s) offre(s), 0 notée(s)"), lignes
    assert "ajoute ta clé dans Mon profil" in lignes[0]
    assert comptes._appels_careerjet_test == ["stage finance de marché", "stage audit"]
    with closing(db.connecter(lea.dossier / "stages.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM offres").fetchone()[0] == 4
        assert {r[0] for r in conn.execute("SELECT source FROM runs")} == {"commune", "careerjet"}
    with closing(db.connecter(dossier / "bap.db")) as conn:   # la base de BAP n'a pas bougé
        assert conn.execute("SELECT COUNT(*) FROM offres").fetchone()[0] == 3


def test_careerjet_partage_memoire_et_plafond(dossier, monkeypatch):
    """La clé Careerjet de BAP sert aux amis : une recherche déjà faite dans les 24 h est reprise sans appel,
    et un ami a au plus CAREERJET_PAR_AMI_PAR_JOUR vraies recherches par jour. BAP, lui, cherche toujours à neuf."""
    appels = comptes._appels_careerjet_test
    monkeypatch.setattr(comptes, "CAREERJET_PAR_AMI_PAR_JOUR", 3)
    comptes.creer_admin("bap", MDP)
    lea = comptes.creer_avec_invitation(comptes.inviter(), "lea", MDP)
    tom = comptes.creer_avec_invitation(comptes.inviter(), "tom", MDP)
    reglages_cj = {"referer": "https://exemple.fr/", "delai_secondes": 0}

    def chercher(compte, requetes):
        jeton = COMPTE.set(compte)
        try:
            return careerjet.collecter({"sources": {"careerjet": reglages_cj}, "recherches": {"requetes": requetes}}, Contexte())
        finally:
            COMPTE.reset(jeton)

    assert secret("CAREERJET_API_KEY") == "fausse-cle-careerjet"
    r = chercher(lea, ["stage audit", "stage finance"])
    assert r.nb_requetes == 2 and len(r.offres) == 2 and appels == ["stage audit", "stage finance"]
    r = chercher(tom, ["stage audit", "stage marketing digital"])       # « stage audit » déjà cherché par Léa
    assert r.nb_requetes == 1 and len(r.offres) == 2 and appels[-1] == "stage marketing digital"
    r = chercher(lea, ["stage a", "stage b", "stage c"])                # plafond : 3 par jour, 2 déjà faites
    assert r.nb_requetes == 1 and "plafond" in r.message and appels[-1] == "stage a"
    assert comptes.careerjet_restantes("lea") == 0 and comptes.careerjet_restantes("tom") == 2
    avant = len(appels)
    r = chercher(comptes.compte("bap"), ["stage audit"])                # BAP : toujours à neuf, sans plafond
    assert r.nb_requetes == 1 and len(appels) == avant + 1


def test_aucun_test_ne_sort_sur_internet():
    """Le garde-fou de conftest.py : même la vraie fonction de recherche ne peut pas joindre Careerjet."""
    import requests
    from conftest import ReseauInterdit
    with pytest.raises(ReseauInterdit):
        requests.get("https://search.api.careerjet.net/v4/query", timeout=5)

