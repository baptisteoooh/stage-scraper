"""Le profil de recherche (page « Mon profil ») : ce que l'étudiant cherche, lu et écrit dans config.yaml.

Le profil est une vue simple et lisible des réglages éparpillés dans config.yaml (critères, domaines,
secteurs, entreprises suivies, exclusions, recherches envoyées aux sites). Chaque champ a un nom court,
un libellé et un type ; toute modification est vérifiée avant d'être écrite (dates réelles, durées
cohérentes, départements connus...). Les commentaires du fichier sont gardés (voir reglages.py).

Utilisé par la page « Mon profil » (modification à la main) et par l'agent qui modifie le profil
en conversation (agent_profil.py).
"""
from datetime import date

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from . import reglages

DEPARTEMENTS = {"75": "Paris", "77": "Seine-et-Marne", "78": "Yvelines", "91": "Essonne", "92": "Hauts-de-Seine",
                "93": "Seine-Saint-Denis", "94": "Val-de-Marne", "95": "Val-d'Oise"}
CONTRATS = {"stage": "Stage", "cdd": "CDD"}
SIX_MOIS = {"a_negocier": "À négocier chez les entreprises suivies", "exclure": "Toujours exclues"}
GROUPES = {"priorite_absolue": "Priorité absolue", "grand_groupe": "Grand groupe", "scale_up": "Scale-up",
           "ecosysteme": "Écosystème"}

# champ -> (libellé, type). Types : texte, liste, date, nombre, booleen, choix, entreprises.
CHAMPS = {
    "recherche": ("Ce que tu cherches", "texte"),
    "ecole": ("École", "texte"),
    "annee": ("Année", "texte"),
    "majeure": ("Majeure", "texte"),
    "competences": ("Compétences", "liste"),
    "contrats": ("Contrats acceptés", "liste"),
    "debut_au_plus_tot": ("Début au plus tôt", "date"),
    "debut_ideal": ("Début idéal", "date"),
    "debut_au_plus_tard": ("Début au plus tard", "date"),
    "fin_au_plus_tard": ("Fin au plus tard", "date"),
    "duree_min": ("Durée minimale", "nombre"),
    "duree_max": ("Durée maximale", "nombre"),
    "six_mois": ("Offres de 6 mois", "choix"),
    "departements": ("Départements", "liste"),
    "hybride": ("Hybride accepté", "booleen"),
    "full_remote": ("Télétravail complet accepté", "booleen"),
    "domaines": ("Domaines, par ordre de préférence", "liste"),
    "secteurs_cible": ("Secteurs visés", "liste"),
    "secteurs_ok": ("Secteurs qui vont aussi", "liste"),
    "secteurs_moins": ("Secteurs moins intéressants", "liste"),
    "autres_secteurs_domaines": ("Hors de tes secteurs, seulement pour ces domaines", "liste"),
    "tailles": ("Tailles d'entreprise préférées", "liste"),
    "entreprises": ("Entreprises suivies", "entreprises"),
    "postes_exclus": ("Postes exclus", "liste"),
    "contrats_exclus": ("Contrats exclus", "liste"),
    "niveaux_exclus": ("Niveaux trop élevés", "liste"),
    "requetes": ("Recherches envoyées aux sites", "liste"),
    "anciennete_max_jours": ("Ancienneté maximale d'une offre (jours)", "nombre"),
}
# Les champs qui changent ce que le pré-filtre garde : après eux, il faut refaire le tri des offres déjà là.
CHAMPS_TRI = {"contrats", "debut_au_plus_tot", "debut_au_plus_tard", "fin_au_plus_tard", "duree_min", "duree_max",
              "six_mois", "departements", "hybride", "full_remote", "entreprises", "postes_exclus", "contrats_exclus",
              "niveaux_exclus", "anciennete_max_jours"}
LONGUEUR_TEXTE_MAX = 400
LONGUEUR_ELEMENT_MAX = 80
ELEMENTS_MAX = 60


class ProfilInvalide(ValueError):
    pass


# =========================================================================== lecture

def lire(donnees) -> dict:
    """Le profil (dict JSON simple) à partir du contenu de config.yaml."""
    c, p = donnees["criteres"], donnees.get("profil") or {}
    s = donnees.get("secteurs") or {}
    domaines = sorted(donnees.get("domaines") or [], key=lambda d: d.get("priorite", 99))
    return {
        "recherche": str(p.get("recherche") or ""),
        "ecole": str(p.get("ecole") or ""), "annee": str(p.get("annee") or ""), "majeure": str(p.get("majeure") or ""),
        "competences": [str(x) for x in p.get("competences") or []],
        "contrats": [str(x) for x in c.get("contrats_acceptes") or []],
        **{cle: _iso(c["dates"].get(cle)) for cle in ("debut_au_plus_tot", "debut_ideal", "debut_au_plus_tard",
                                                       "fin_au_plus_tard")},
        "duree_min": _nombre(c["duree"].get("min_mois")), "duree_max": _nombre(c["duree"].get("max_mois")),
        "six_mois": str(c["duree"].get("six_mois_entreprise_suivie") or "a_negocier"),
        "departements": [str(x) for x in c["lieu"].get("departements") or []],
        "hybride": bool(c["lieu"].get("hybride")), "full_remote": bool(c["lieu"].get("full_remote")),
        "domaines": [str(d["nom"]) for d in domaines],
        "secteurs_cible": [str(x) for x in s.get("cible") or []],
        "secteurs_ok": [str(x) for x in s.get("ok") or []],
        "secteurs_moins": [str(x) for x in s.get("score_reduit") or []],
        "autres_secteurs_domaines": [str(x) for x in s.get("hors_sante_domaines") or []],
        "tailles": [str(x) for x in s.get("taille_preferee") or []],
        "entreprises": reglages.entreprises_en_lignes(donnees),
        "postes_exclus": [str(x) for x in donnees["exclusions"].get("postes") or []],
        "contrats_exclus": [str(x) for x in donnees["exclusions"].get("contrats") or []],
        "niveaux_exclus": [str(x) for x in donnees["exclusions"].get("niveaux") or []],
        "requetes": [str(x) for x in (donnees.get("recherches") or {}).get("requetes") or []],
        "anciennete_max_jours": int(donnees["general"].get("anciennete_max_jours", 90)),
    }


def _iso(valeur) -> str:
    return valeur.isoformat() if isinstance(valeur, date) else str(valeur or "")


def _nombre(valeur):
    valeur = float(valeur or 0)
    return int(valeur) if valeur.is_integer() else valeur


# =========================================================================== écriture

def appliquer(donnees, valeurs: dict) -> list[dict]:
    """Vérifie et applique des valeurs (champ -> nouvelle valeur) au contenu de config.yaml.

    Tout est vérifié avant d'écrire quoi que ce soit : une valeur invalide lève ProfilInvalide et
    `donnees` reste intact. Renvoie les changements réels [{champ, libelle, avant, apres}].
    """
    inconnus = set(valeurs) - set(CHAMPS)
    if inconnus:
        raise ProfilInvalide(f"champ inconnu : {', '.join(sorted(inconnus))}")
    avant = lire(donnees)
    nouveau = {**avant, **{champ: normaliser(champ, v) for champ, v in valeurs.items()}}
    # Un domaine retiré disparaît aussi des listes qui en dépendent.
    if "domaines" in valeurs and "autres_secteurs_domaines" not in valeurs:
        nouveau["autres_secteurs_domaines"] = [d for d in nouveau["autres_secteurs_domaines"] if d in nouveau["domaines"]]
    verifier(nouveau)
    changements = [{"champ": champ, "libelle": CHAMPS[champ][0], "avant": avant[champ], "apres": nouveau[champ]}
                   for champ in CHAMPS if nouveau[champ] != avant[champ]]
    for ch in changements:
        _ecrire(donnees, ch["champ"], ch["apres"], nouveau)
    return changements


def normaliser(champ: str, valeur):
    """Met une valeur reçue (de la page ou de l'agent) dans la forme du profil, ou lève ProfilInvalide."""
    libelle, genre = CHAMPS[champ]
    if genre == "texte":
        texte = " ".join(str(valeur or "").split())
        if len(texte) > LONGUEUR_TEXTE_MAX:
            raise ProfilInvalide(f"{libelle} : {LONGUEUR_TEXTE_MAX} caractères au plus")
        return texte
    if genre == "liste":
        if isinstance(valeur, str):
            valeur = valeur.split(",")
        if not isinstance(valeur, list):
            raise ProfilInvalide(f"{libelle} : une liste est attendue")
        liste = reglages.texte_en_liste("\n".join(str(x) for x in valeur))
        if len(liste) > ELEMENTS_MAX or any(len(x) > LONGUEUR_ELEMENT_MAX for x in liste):
            raise ProfilInvalide(f"{libelle} : liste trop longue")
        if champ == "contrats":
            liste = [x.lower() for x in liste]
            if set(liste) - set(CONTRATS):
                raise ProfilInvalide(f"{libelle} : seulement « stage » et « cdd »")
        if champ == "departements" and set(liste) - set(DEPARTEMENTS):
            raise ProfilInvalide(f"{libelle} : seulement ceux d'Île-de-France ({', '.join(DEPARTEMENTS)})")
        return liste
    if genre == "date":
        try:
            return date.fromisoformat(str(valeur).strip()).isoformat()
        except ValueError as e:
            raise ProfilInvalide(f"{libelle} : date au format AAAA-MM-JJ attendue") from e
    if genre == "nombre":
        try:
            n = float(str(valeur).replace(",", "."))
        except ValueError as e:
            raise ProfilInvalide(f"{libelle} : un nombre est attendu") from e
        bornes = (1, 365) if champ == "anciennete_max_jours" else (1, 12)
        if not bornes[0] <= n <= bornes[1]:
            raise ProfilInvalide(f"{libelle} : entre {bornes[0]} et {bornes[1]}")
        if champ == "anciennete_max_jours":
            return int(n)
        n = round(n * 2) / 2   # au demi-mois près
        return int(n) if n.is_integer() else n
    if genre == "booleen":
        if isinstance(valeur, bool):
            return valeur
        texte = str(valeur).strip().lower()
        if texte in ("oui", "true", "vrai", "1", "yes"):
            return True
        if texte in ("non", "false", "faux", "0", "no"):
            return False
        raise ProfilInvalide(f"{libelle} : oui ou non")
    if genre == "choix":
        if valeur not in SIX_MOIS:
            raise ProfilInvalide(f"{libelle} : {' ou '.join(SIX_MOIS)}")
        return valeur
    if genre == "entreprises":
        if not isinstance(valeur, list):
            raise ProfilInvalide(f"{libelle} : une liste est attendue")
        lignes, vus = [], set()
        for e in valeur:
            e = {"nom": e} if isinstance(e, str) else dict(e)
            nom = " ".join(str(e.get("nom") or "").split())
            if not nom or nom.lower() in vus:
                continue
            if len(nom) > LONGUEUR_ELEMENT_MAX:
                raise ProfilInvalide(f"{libelle} : nom trop long")
            groupe = e.get("groupe") or "scale_up"
            if groupe not in GROUPES:
                raise ProfilInvalide(f"{libelle} : groupe inconnu ({groupe})")
            if (e.get("outil") or "") not in ("", "ashby", "workday"):
                raise ProfilInvalide(f"{libelle} : outil carrières inconnu ({e['outil']})")
            vus.add(nom.lower())
            lignes.append({"nom": nom, "groupe": groupe, "alias": str(e.get("alias") or ""),
                           "outil": str(e.get("outil") or ""), "adresse_ou_id": str(e.get("adresse_ou_id") or "")})
        if len(lignes) > ELEMENTS_MAX:
            raise ProfilInvalide(f"{libelle} : {ELEMENTS_MAX} entreprises au plus")
        return lignes
    raise ProfilInvalide(f"type inconnu pour {champ}")


def verifier(p: dict) -> None:
    """Les règles qui lient les champs entre eux (lève ProfilInvalide)."""
    if not p["contrats"]:
        raise ProfilInvalide("garde au moins un type de contrat (stage ou CDD)")
    if not p["departements"] and not p["full_remote"]:
        raise ProfilInvalide("garde au moins un département, ou accepte le télétravail complet")
    if not p["domaines"]:
        raise ProfilInvalide("garde au moins un domaine")
    inconnus = [d for d in p["autres_secteurs_domaines"] if d not in p["domaines"]]
    if inconnus:
        raise ProfilInvalide(f"{CHAMPS['autres_secteurs_domaines'][0]} : « {inconnus[0]} » n'est pas dans tes domaines")
    tot, ideal, tard, fin = (date.fromisoformat(p[c]) for c in ("debut_au_plus_tot", "debut_ideal",
                                                                 "debut_au_plus_tard", "fin_au_plus_tard"))
    if not tot <= tard:
        raise ProfilInvalide("le début au plus tôt doit précéder le début au plus tard")
    if not tot <= ideal <= tard:
        raise ProfilInvalide("le début idéal doit être entre le début au plus tôt et au plus tard")
    if not tard < fin:
        raise ProfilInvalide("la fin au plus tard doit venir après le début au plus tard")
    if p["duree_min"] > p["duree_max"]:
        raise ProfilInvalide("la durée minimale dépasse la durée maximale")


def alertes(p: dict) -> list[str]:
    """Incohérences qui n'empêchent pas d'enregistrer, mais qu'il faut signaler."""
    sortie = []
    tot, fin = date.fromisoformat(p["debut_au_plus_tot"]), date.fromisoformat(p["fin_au_plus_tard"])
    mois_possibles = (fin - tot).days / 30.4
    if p["duree_min"] > mois_possibles + 0.25:
        sortie.append(f"Entre le début au plus tôt et la fin au plus tard, il n'y a que {mois_possibles:.1f} mois : "
                      f"moins que ta durée minimale ({p['duree_min']:g} mois).")
    if p["duree_max"] >= 6 and p["six_mois"] == "exclure":
        sortie.append("Ta durée maximale accepte 6 mois, mais les offres de 6 mois sont réglées sur « toujours exclues ».")
    if not p["requetes"]:
        sortie.append("Aucune recherche envoyée aux sites : Google Jobs et Careerjet ne ramèneront rien.")
    if not p["recherche"]:
        sortie.append("Décris en une phrase ce que tu cherches : l'IA s'en sert pour noter les offres.")
    return sortie


def _ecrire(donnees, champ: str, valeur, profil: dict) -> None:
    """Écrit un champ à sa place dans config.yaml (listes modifiées sur place : commentaires gardés)."""
    c = donnees["criteres"]
    if champ in ("recherche", "ecole", "annee", "majeure", "competences"):
        p = donnees.setdefault("profil", CommentedMap())
        if champ == "competences":
            _liste(p, "competences", valeur, en_ligne=True)
        elif champ == "recherche" and "recherche" not in p:
            p.insert(0, "recherche", valeur)
        else:
            p[champ] = valeur
    elif champ == "contrats":
        _liste(c, "contrats_acceptes", valeur, en_ligne=True)
    elif champ.startswith(("debut_", "fin_")):
        c["dates"][champ] = date.fromisoformat(valeur)
    elif champ in ("duree_min", "duree_max"):
        c["duree"]["min_mois" if champ == "duree_min" else "max_mois"] = valeur
    elif champ == "six_mois":
        c["duree"]["six_mois_entreprise_suivie"] = valeur
    elif champ == "departements":
        _liste(c["lieu"], "departements", valeur, en_ligne=True)
    elif champ in ("hybride", "full_remote"):
        c["lieu"][champ] = valeur
    elif champ == "domaines":
        _ecrire_domaines(donnees, profil["domaines"])
    elif champ in ("secteurs_cible", "secteurs_ok", "secteurs_moins", "autres_secteurs_domaines", "tailles"):
        cle = {"secteurs_cible": "cible", "secteurs_ok": "ok", "secteurs_moins": "score_reduit",
               "autres_secteurs_domaines": "hors_sante_domaines", "tailles": "taille_preferee"}[champ]
        _liste(donnees.setdefault("secteurs", CommentedMap()), cle, valeur, en_ligne=True)
    elif champ == "entreprises":
        reglages.appliquer(donnees, {"entreprises_suivies": valeur})
    elif champ in ("postes_exclus", "contrats_exclus", "niveaux_exclus"):
        _liste(donnees["exclusions"], champ.split("_")[0], valeur)
    elif champ == "requetes":
        _liste(donnees.setdefault("recherches", CommentedMap()), "requetes", valeur)
    elif champ == "anciennete_max_jours":
        donnees["general"]["anciennete_max_jours"] = valeur


def _liste(parent, cle: str, valeurs: list, en_ligne: bool = False) -> None:
    if isinstance(parent.get(cle), CommentedSeq):
        reglages.remplacer_liste(parent[cle], valeurs)
        return
    seq = CommentedSeq(valeurs)
    if en_ligne:
        seq.fa.set_flow_style()
    parent[cle] = seq


def _ecrire_domaines(donnees, noms: list[str]) -> None:
    """Domaines : la priorité suit l'ordre de la liste, et le premier est le « très intéressant ».

    Les autres champs d'un domaine (ajoutés à la main dans le fichier) sont gardés."""
    anciens = {d["nom"]: d for d in donnees.get("domaines") or []}
    nouveaux = []
    for i, nom in enumerate(noms, start=1):
        d = anciens.get(nom)
        if d is None:
            d = CommentedMap()
            d["nom"] = nom
        d["priorite"] = i
        if i == 1:
            d["tres_interessant"] = True
        elif "tres_interessant" in d:
            del d["tres_interessant"]
        nouveaux.append(d)
    if isinstance(donnees.get("domaines"), CommentedSeq):
        seq = donnees["domaines"]
        # Le titre de la section suivante (« # Secteurs ») est accroché à la dernière clé du dernier domaine :
        # on le déplace sur le nouveau dernier domaine.
        dernier = seq[-1] if len(seq) and isinstance(seq[-1], CommentedMap) and len(seq[-1]) else None
        titre_suivant = dernier.ca.items.pop(list(dernier)[-1], None) if dernier is not None else None
        del seq[:]
        seq.extend(nouveaux)
        if titre_suivant and nouveaux:
            fin = nouveaux[-1]
            for cle in list(fin)[:-1]:
                fin.ca.items.pop(cle, None)
            fin.ca.items[list(fin)[-1]] = titre_suivant
    else:
        donnees["domaines"] = CommentedSeq(nouveaux)


# =========================================================================== pour les IA

def zone(p: dict) -> str:
    """« Île-de-France » si tous les départements y sont, sinon leur liste ; plus le télétravail."""
    if set(p["departements"]) == set(DEPARTEMENTS):
        lieu = "Île-de-France"
    elif p["departements"]:
        lieu = ", ".join(f"{DEPARTEMENTS[d]} ({d})" for d in p["departements"])
    else:
        lieu = "aucun département"
    modes = [m for m, oui in (("hybride", p["hybride"]), ("télétravail complet", p["full_remote"])) if oui]
    return lieu + (f" ; {' et '.join(modes)} accepté{'s' if len(modes) > 1 else ''}" if modes else "")


def en_texte(p: dict) -> str:
    """Le profil en clair, champ par champ (pour les consignes des IA)."""
    lignes = []
    for champ, (libelle, genre) in CHAMPS.items():
        v = p[champ]
        if genre == "entreprises":
            v = "; ".join(f"{e['nom']} ({GROUPES[e['groupe']]})" for e in v) or "aucune"
        elif genre == "liste":
            v = " | ".join(v) or "(vide)"
        elif genre == "booleen":
            v = "oui" if v else "non"
        elif genre == "choix":
            v = f"{v} ({SIX_MOIS[v]})"
        lignes.append(f"- {champ} — {libelle} : {v if v != '' else '(vide)'}")
    return "\n".join(lignes)
