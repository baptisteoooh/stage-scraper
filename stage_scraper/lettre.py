"""Brouillon de lettre de motivation pour une offre, rédigé par Claude.

C'est un brouillon : Claude n'invente ni expérience ni chiffre, et laisse des repères
[à compléter : ...] là où il manque une information que lui seul (BAP) connaît.
"""
from datetime import datetime

from . import db
from .config import secret
from .prefiltre import entreprise_suivie
from .cv import texte_cv
from .scoring import LONGUEUR_DESCRIPTION_MAX, ajouter_usage, cout_du_mois


class LettreImpossible(Exception):
    """Erreur affichable telle quelle (sans secret)."""


def _maintenant() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def consignes_systeme(config: dict, avec_cv: bool) -> str:
    profil = config["profil"]
    texte = f"""Tu rédiges des brouillons de lettres de motivation pour un étudiant qui cherche un stage.

L'ÉTUDIANT
- {profil['annee']} à l'{profil['ecole']} (école d'ingénieurs), majeure {profil['majeure']}.
- Compétences : {', '.join(profil['competences'])}.
- Cherche un stage de {config['criteres']['duree']['min_mois']:g} à {config['criteres']['duree']['max_mois']:g} mois, à partir d'avril 2027, en Île-de-France.

RÈGLES
- Écris dans la langue de l'offre (français ou anglais).
- 250 à 350 mots, ton sobre et précis, sans formules creuses ni flatterie excessive.
- Structure : pourquoi cette entreprise et ce poste (en t'appuyant sur l'offre), ce que l'étudiant apporte
  (compétences reliées aux missions), disponibilités, formule de fin courte.
- N'invente jamais une expérience, un projet, un chiffre ou un nom. Quand une information précise manque,
  mets un repère entre crochets, par exemple [à compléter : projet de machine learning réalisé à l'ENSX].
- Pas d'en-tête d'adresse ni de date : commence par la formule d'appel (« Madame, Monsieur, » ou « Dear Hiring Team, »).
- Réponds uniquement avec le texte de la lettre."""
    if avec_cv:
        texte += "\n\nLe CV de l'étudiant est joint : appuie-toi dessus pour les expériences et projets réels."
    return texte


def message_offre(offre: dict, config: dict, consignes: str, cv: str | None):
    suivie = entreprise_suivie(offre.get("entreprise"), config)
    lignes = [
        "Rédige le brouillon de lettre de motivation pour cette offre.",
        "",
        f"Titre : {offre.get('titre')}",
        f"Entreprise : {offre.get('entreprise') or 'inconnue'}" + (" (entreprise que l'étudiant suit de près)" if suivie else ""),
        f"Lieu : {offre.get('lieu') or 'inconnu'}",
        f"Durée : {offre.get('duree') or offre.get('duree_ia') or 'non précisée'}",
        f"Début : {offre.get('date_debut') or offre.get('date_debut_ia') or 'non précisé'}",
        "",
        "Description de l'offre :",
        (offre.get("description") or "(pas de description : appuie-toi sur le titre)")[:LONGUEUR_DESCRIPTION_MAX],
    ]
    if consignes.strip():
        lignes += ["", f"Consignes de l'étudiant pour cette lettre : {consignes.strip()}"]
    texte = "\n".join(lignes)
    if cv:
        return f"CV de l'étudiant (coordonnées retirées) :\n<cv>\n{cv}\n</cv>\n\n{texte}"
    return texte


def rediger(conn, config: dict, offre: dict, consignes: str = "", client=None) -> dict:
    """Rédige un brouillon. Renvoie {'texte', 'cout_usd', 'tokens_entree', 'tokens_sortie'}."""
    reglages = config.get("lettre", {})
    modele = reglages.get("modele", config["scoring"]["modele"])
    budget = config["scoring"].get("budget_mensuel_usd", 2.0)
    if cout_du_mois(conn) >= budget:
        raise LettreImpossible(f"budget IA du mois ({budget} $) atteint")
    if client is None:
        if not secret("ANTHROPIC_API_KEY"):
            raise LettreImpossible("ajoute ANTHROPIC_API_KEY dans .env pour rédiger des lettres")
        import anthropic
        client = anthropic.Anthropic()

    cv = texte_cv(config)
    bilan = {"texte": "", "cout_usd": 0.0, "tokens_entree": 0, "tokens_sortie": 0}
    debut, erreur = _maintenant(), None
    try:
        reponse = client.messages.create(
            model=modele,
            max_tokens=reglages.get("max_tokens", 6000),
            output_config={"effort": reglages.get("effort", "medium")},
            system=consignes_systeme(config, avec_cv=bool(cv)),
            messages=[{"role": "user", "content": message_offre(offre, config, consignes, cv)}],
        )
        ajouter_usage(bilan, reponse.usage, modele)
        bilan["texte"] = "\n".join(b.text for b in reponse.content if getattr(b, "type", "") == "text").strip()
        if reponse.stop_reason == "refusal" or not bilan["texte"]:
            erreur = "l'IA n'a pas rédigé de lettre pour cette offre"
        elif reponse.stop_reason == "max_tokens":
            bilan["texte"] += "\n\n[lettre coupée : relance la rédaction]"
    except Exception as e:  # erreurs d'API : message simple, sans secret
        erreur = _message_erreur(e)
    finally:
        db.journaliser_run(conn, passage_id=db.nouveau_passage_id(conn), date_debut=debut, date_fin=_maintenant(),
                           declenchement="manuel", source="lettre", nb_offres=1, nb_requetes=1,
                           erreurs=erreur, tokens_entree=bilan["tokens_entree"],
                           tokens_sortie=bilan["tokens_sortie"], cout_usd=round(bilan["cout_usd"], 6))
        conn.commit()
    if erreur:
        raise LettreImpossible(erreur)
    return bilan


def _message_erreur(e: Exception) -> str:
    import anthropic
    if isinstance(e, anthropic.AuthenticationError):
        return "clé ANTHROPIC_API_KEY refusée : vérifie-la dans .env"
    if isinstance(e, anthropic.RateLimitError):
        return "trop de requêtes vers l'API Claude (429) : réessaie dans une minute"
    if isinstance(e, anthropic.APIConnectionError):
        return "API Claude injoignable (réseau)"
    return f"{type(e).__name__}"
