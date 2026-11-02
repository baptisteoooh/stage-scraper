"""Parseurs des mails d'alerte : un module par site (linkedin.py, indeed.py, ...).

Chaque module expose :
- NOM : nom de la source enregistré dans la base (ex. "alerte_linkedin") ;
- reconnait(expediteur) -> bool : True si ce mail vient de ce site ;
- extraire(message) -> list[dict] : les offres du mail, au format commun (offre.py).

Pour ajouter un site : créer son module ici et l'ajouter à PARSEURS.
"""

from . import linkedin

PARSEURS: list = [linkedin]
