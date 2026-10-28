"""Scoring IA : Claude note chaque nouvelle offre gardée par le pré-filtre.

Entrée : l'offre, le profil de BAP, son CV (profil/cv.pdf dès qu'il existe) et des
exemples d'offres marquées « pas intéressé ». Sortie : un JSON validé (score, section,
résumé, explication, durée, date de début, exclusion).

Coût : la partie fixe (consignes, profil, CV, exemples) est mise en cache par l'API,
seule l'offre change d'un appel à l'autre. Les tokens et le coût de chaque passage sont
enregistrés dans le journal (source = 'scoring'), et le scoring s'arrête de lui-même
quand le budget mensuel (config.yaml > scoring.budget_mensuel_usd) est atteint.
"""
import base64
import logging
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from . import db
from .config import chemin_projet, secret
from .prefiltre import entreprise_suivie

log = logging.getLogger(__name__)

# Prix en dollars par million de tokens (entrée, sortie). Lecture du cache : 0,1 x l'entrée,
# écriture du cache : 1,25 x l'entrée.
PRIX = {"claude-haiku-5-5": (0.10, 0.50)}
LONGUEUR_DESCRIPTION_MAX = 6000  # caractères envoyés à l'IA (les descriptions très longues sont coupées)


class Notation(BaseModel):
    """Format de réponse imposé à Claude."""
    score: int
    section: Literal["Santé", "Hors santé mais intéressant", "À négocier"]
    resume: str
    pourquoi: str
    duree: Optional[str]
    date_debut: Optional[str]
    exclusion: Optional[str]
    poste_ia_data: bool


class BudgetAtteint(Exception):
    pass


def noter_nouvelles(conn, config: dict, passage_id: int, auto: bool, client=None) -> dict:
    """Note les offres gardées et pas encore notées. Renvoie le bilan du scoring."""
    reglages = config["scoring"]
    bilan = {"notees": 0, "erreurs": [], "message": None, "tokens_entree": 0, "tokens_sortie": 0, "cout_usd": 0.0}

    offres = conn.execute(
        "SELECT * FROM offres WHERE score IS NULL AND exclusion_ia IS NULL AND doublon_de IS NULL "
        "AND exclusion_prefiltre IS NULL AND pas_interesse = 0 ORDER BY id LIMIT ?",
        (reglages.get("max_offres_par_passage", 150),),
    ).fetchall()
    if not offres:
        bilan["message"] = "aucune nouvelle offre à noter"
        return bilan

    if client is None:
        if not secret("ANTHROPIC_API_KEY"):
            bilan["message"] = f"{len(offres)} offre(s) en attente : ajoute ANTHROPIC_API_KEY dans .env pour les noter"
            return bilan
        import anthropic
        client = anthropic.Anthropic()

    deja_depense = cout_du_mois(conn)
    budget = reglages.get("budget_mensuel_usd", 2.0)
    systeme = prompt_systeme(conn, config)
    cv = charger_cv(config)
    debut = _maintenant()

    try:
        for ligne in offres:
            offre = dict(ligne)
            if deja_depense + bilan["cout_usd"] >= budget:
                raise BudgetAtteint(f"budget mensuel de {budget} $ atteint : scoring arrêté jusqu'au mois prochain")
            try:
                notation, usage = noter(client, reglages, systeme, texte_offre(offre, config, cv))
            except Exception as e:  # erreurs d'API : voir _erreur_bloquante
                if _erreur_bloquante(e):
                    raise
                bilan["erreurs"].append(f"offre {offre['id']} : {type(e).__name__} : {e}")
                continue
            ajouter_usage(bilan, usage, reglages["modele"])
            if notation is None:
                bilan["erreurs"].append(f"offre {offre['id']} : l'IA a refusé de répondre")
                continue
            enregistrer(conn, offre["id"], notation, config)
            bilan["notees"] += 1
    except BudgetAtteint as e:
        bilan["message"] = str(e)
    except Exception as e:
        bilan["erreurs"].append(_message_erreur(e))
    finally:
        conn.commit()
        db.journaliser_run(
            conn, passage_id=passage_id, date_debut=debut, date_fin=_maintenant(),
            declenchement="auto" if auto else "manuel", source="scoring",
            nb_offres=len(offres), nb_nouvelles=bilan["notees"], nb_requetes=bilan["notees"] + len(bilan["erreurs"]),
            erreurs="\n".join(bilan["erreurs"]) or None,
            tokens_entree=bilan["tokens_entree"], tokens_sortie=bilan["tokens_sortie"],
            cout_usd=round(bilan["cout_usd"], 6),
        )
    return bilan


def noter(client, reglages: dict, systeme: list, message):
    """Un appel à Claude pour une offre. Renvoie (Notation ou None si refus, usage)."""
    reponse = client.messages.parse(
        model=reglages["modele"],
        max_tokens=reglages.get("max_tokens", 4000),
        output_config={"effort": reglages.get("effort", "low")},
        system=systeme,
        messages=[{"role": "user", "content": message}],
        output_format=Notation,
    )
    if reponse.stop_reason == "refusal" or reponse.parsed_output is None:
        return None, reponse.usage
    return reponse.parsed_output, reponse.usage


def prompt_systeme(conn, config: dict) -> list:
    """Consignes fixes (mises en cache), avec le CV en pièce jointe s'il existe."""
    criteres, profil = config["criteres"], config["profil"]
    domaines = "\n".join(f"  {d['priorite']}. {d['nom']}" for d in sorted(config["domaines"], key=lambda d: d["priorite"]))
    suivies = ", ".join(e["nom"] for e in config.get("entreprises_suivies", []))
    exemples = exemples_pas_interesse(conn, config["scoring"].get("exemples_pas_interesse_max", 10))
    seuils = config["scoring"]["seuils"]

    consignes = f"""Tu aides un étudiant à trier des offres de stage. Pour chaque offre, tu rends une note et une courte analyse en français.

PROFIL
- {profil['annee']} à l'{profil['ecole']}, majeure {profil['majeure']}.
- Compétences : {', '.join(profil['competences'])}.
- Cherche un stage dans la medtech / santé, de préférence un poste IA ou data.

CRITÈRES
- Début entre le {criteres['dates']['debut_au_plus_tot']} et le {criteres['dates']['debut_au_plus_tard']} (idéal : {criteres['dates']['debut_ideal']}), fin au plus tard le {criteres['dates']['fin_au_plus_tard']}.
- Durée : {criteres['duree']['min_mois']:g} à {criteres['duree']['max_mois']:g} mois. Les offres « 3 à 6 mois » et « 4 à 6 mois » conviennent. Une offre de 6 mois fixes ne convient que chez une entreprise suivie : elle va alors dans la section « À négocier ».
- Lieu : Île-de-France, hybride ou télétravail acceptés.
- Contrats acceptés : stage, ou CDD aux mêmes conditions de dates et de durée.
- Exclus : alternance, apprentissage, CDI, VIE, stage de fin d'études / PFE, et tout poste non technique (marketing, commercial, vente, business development, RH...).
- Langues : français ou anglais.

DOMAINES, du plus au moins intéressant
{domaines}
Un poste IA (intelligence artificielle, machine learning, deep learning, LLM, computer vision...) est très intéressant.

SECTEURS
- Medtech / healthtech : cible principale. Biotech : bien. Pharma et assurance santé : moins intéressant (note réduite).
- Hors santé : seulement si c'est un poste tech IA/data très pertinent, dans la section « Hors santé mais intéressant ». Sinon note basse.
- Préférence pour les grosses startups et scale-ups ; les grands groupes restent intéressants.

ENTREPRISES SUIVIES (bonus ; Doctolib en priorité absolue, avec un bonus fort sur les postes IA)
{suivies}

NOTE (score de 0 à 10)
- {seuils['a_postuler_vite']} à 10 : à postuler vite (santé + IA/data + critères respectés).
- {seuils['a_regarder']} à {seuils['a_postuler_vite'] - 1} : à regarder.
- moins de {seuils['a_regarder']} : bof.

RÉPONSE
- section : « Santé », « Hors santé mais intéressant » ou « À négocier ».
- resume : 2 lignes maximum sur la mission.
- pourquoi : une phrase qui explique la note.
- duree et date_debut : telles que tu les lis dans l'offre, sinon null.
- exclusion : si l'offre viole un critère dur (contrat exclu, poste non technique, dates ou durée incompatibles, hors Île-de-France), la raison en quelques mots ; sinon null.
- poste_ia_data : true si le poste relève de l'IA ou de la data.
Si une information manque (durée, date), ne pénalise pas l'offre pour autant."""

    if exemples:
        consignes += "\n\nOFFRES QUE L'ÉTUDIANT A MARQUÉES « PAS INTÉRESSÉ » (note bas les offres semblables)\n" + exemples

    if charger_cv(config):
        consignes += "\n\nLe CV de l'étudiant est joint au début de chaque message : sers-t'en pour juger l'adéquation."
    return [{"type": "text", "text": consignes, "cache_control": {"type": "ephemeral"}}]


def charger_cv(config: dict) -> str | None:
    """Le CV (profil/cv.pdf) encodé en base64, ou None s'il n'existe pas encore."""
    chemin = chemin_projet(config["profil"].get("cv", "profil/cv.pdf"))
    return base64.standard_b64encode(chemin.read_bytes()).decode("ascii") if chemin.exists() else None


def texte_offre(offre: dict, config: dict, cv: str | None = None):
    """Le message utilisateur : l'offre, précédée du CV en document s'il existe (mis en cache)."""
    description = (offre.get("description") or "")[:LONGUEUR_DESCRIPTION_MAX]
    suivie = entreprise_suivie(offre.get("entreprise"), config)
    lignes = [
        f"Titre : {offre.get('titre')}",
        f"Entreprise : {offre.get('entreprise') or 'inconnue'}" + (" (entreprise suivie)" if suivie else ""),
        f"Type de contrat : {offre.get('type_contrat') or 'inconnu'}",
        f"Lieu : {offre.get('lieu') or 'inconnu'}" + (f" (département {offre['departement']})" if offre.get("departement") else ""),
        f"Télétravail : {offre.get('teletravail') or 'non précisé'}",
        f"Publiée le : {offre.get('date_publication') or 'inconnu'}",
        f"Durée détectée : {offre.get('duree') or 'non détectée'}",
        f"Début détecté : {offre.get('date_debut') or 'non détecté'}",
        f"Gratification : {offre.get('gratification') or 'non précisée'}",
        "",
        "Description :",
        description or "(pas de description)",
    ]
    texte = "\n".join(lignes)
    if cv:
        return [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": cv},
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": texte},
        ]
    return texte


def exemples_pas_interesse(conn, maximum: int) -> str:
    lignes = conn.execute(
        "SELECT o.titre, o.entreprise, f.raison FROM feedback f JOIN offres o ON o.id = f.offre_id "
        "ORDER BY f.id DESC LIMIT ?", (maximum,)).fetchall()
    return "\n".join(f"- {l['titre']} ({l['entreprise'] or 'entreprise inconnue'})"
                     + (f" : {l['raison']}" if l["raison"] else "") for l in lignes)


def enregistrer(conn, offre_id: int, notation: Notation, config: dict) -> None:
    score = max(0, min(10, notation.score))
    conn.execute(
        "UPDATE offres SET score = ?, categorie = ?, section = ?, resume = ?, pourquoi = ?, duree_ia = ?, "
        "date_debut_ia = ?, exclusion_ia = ?, poste_ia_data = ?, date_scoring = ? WHERE id = ?",
        (score, categorie(score, config), notation.section, notation.resume, notation.pourquoi,
         notation.duree, notation.date_debut, notation.exclusion or None, int(notation.poste_ia_data),
         _maintenant(), offre_id),
    )


def categorie(score: int, config: dict) -> str:
    seuils = config["scoring"]["seuils"]
    if score >= seuils["a_postuler_vite"]:
        return "À postuler vite"
    if score >= seuils["a_regarder"]:
        return "À regarder"
    return "Bof"


def ajouter_usage(bilan: dict, usage, modele: str) -> None:
    """Additionne les tokens d'un appel et son coût en dollars."""
    entree = getattr(usage, "input_tokens", 0) or 0
    cache_lu = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_ecrit = getattr(usage, "cache_creation_input_tokens", 0) or 0
    sortie = getattr(usage, "output_tokens", 0) or 0
    prix_entree, prix_sortie = PRIX.get(modele, PRIX["claude-haiku-5-5"])
    bilan["tokens_entree"] += entree + cache_lu + cache_ecrit
    bilan["tokens_sortie"] += sortie
    bilan["cout_usd"] += (entree * prix_entree + cache_lu * prix_entree * 0.1
                          + cache_ecrit * prix_entree * 1.25 + sortie * prix_sortie) / 1_000_000


def cout_du_mois(conn) -> float:
    debut_mois = datetime.now().strftime("%Y-%m-01")
    return conn.execute("SELECT COALESCE(SUM(cout_usd), 0) FROM runs WHERE source = 'scoring' AND date_debut >= ?",
                        (debut_mois,)).fetchone()[0]


def _erreur_bloquante(e: Exception) -> bool:
    """Clé refusée, quota, réseau coupé : inutile de continuer avec les offres suivantes."""
    import anthropic
    return isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError,
                          anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.NotFoundError))


def _message_erreur(e: Exception) -> str:
    import anthropic
    if isinstance(e, anthropic.AuthenticationError):
        return "clé ANTHROPIC_API_KEY refusée : vérifie-la dans .env"
    if isinstance(e, anthropic.RateLimitError):
        return "trop de requêtes vers l'API Claude (429) : le reste sera noté au prochain passage"
    if isinstance(e, anthropic.APIConnectionError):
        return "API Claude injoignable (réseau) : le reste sera noté au prochain passage"
    return f"{type(e).__name__} : {e}"


def _maintenant() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")
