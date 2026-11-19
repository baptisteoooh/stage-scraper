"""Collecte des offres sur les pages carrières des entreprises suivies.

Chaque entreprise publie ses offres via un outil de recrutement (Ashby, Greenhouse,
Workday...). La plupart de ces outils exposent les offres en JSON public : on lit ce
JSON plutôt que la page HTML, c'est plus fiable et plus léger pour leurs serveurs.

Dans config.yaml, une entreprise suivie est collectée si elle a un bloc `carrieres` :
    - {nom: Doctolib, groupe: priorite_absolue, carrieres: {outil: ashby, id: doctolib}}

Pour ajouter un outil : créer son module ici (même forme que ashby.py : `collecter` et `prefixe`)
et l'ajouter à OUTILS.
"""
import logging
import time

import requests

from .. import Contexte, Resultat
from . import ashby, workday

NOM = "carrieres"
OUTILS = {
    "ashby": ashby,
    "workday": workday,
}

log = logging.getLogger(__name__)


def collecter(config: dict, contexte: Contexte) -> Resultat:
    reglages = config["sources"].get(NOM, {})
    entreprises = [e for e in config.get("entreprises_suivies", []) if e.get("carrieres")]
    if contexte.max_requetes is not None:
        entreprises = entreprises[:contexte.max_requetes]

    resultat = Resultat()
    for i, entreprise in enumerate(entreprises):
        if i > 0:
            time.sleep(reglages.get("delai_secondes", 2))
        page = entreprise["carrieres"]
        outil = OUTILS.get(page.get("outil"))
        if outil is None:
            resultat.erreurs.append(f"{entreprise['nom']} : outil « {page.get('outil')} » pas encore géré")
            continue
        resultat.nb_requetes += 1
        try:
            offres = outil.collecter(entreprise)
        except (requests.RequestException, ValueError, KeyError) as e:
            # une entreprise en panne ne bloque pas les suivantes
            resultat.erreurs.append(f"{entreprise['nom']} : {type(e).__name__} : {e}")
            continue
        log.info("  %s : %d offre(s) de stage ou CDD", entreprise["nom"], len(offres))
        resultat.offres.extend(offres)
        if getattr(offres, "complete", True):  # liste entière : les offres absentes ont expiré
            resultat.listes_completes[outil.prefixe(entreprise)] = {o.get("source_id") for o in offres}

    if not entreprises:
        resultat.message = "aucune entreprise suivie n'a de bloc `carrieres` dans config.yaml"
    return resultat
