# Stage Scraper

Outil local qui collecte les offres de stage medtech / santé (profil IA / data), les dédoublonne, les note avec Claude, les affiche dans une appli Streamlit, envoie un récap par mail et suit les candidatures.

Le cahier des charges complet est dans `CLAUDE.md`.

## État d'avancement

- [x] 1. Squelette, base SQLite, `config.yaml`, `.env.example`, Git
- [ ] 2. API France Travail (reportée : API suspendue par France Travail)
- [ ] 3. Google Jobs (SerpApi), puis Careerjet
- [ ] 4. Alertes Gmail
- [ ] 5. Scraping direct LinkedIn et Indeed
- [ ] 6. Pages carrières
- [ ] 7. Dédoublonnage et pré-filtre
- [ ] 8. Scoring Claude
- [ ] 9. Appli Streamlit
- [ ] 10. Mails
- [ ] 11. Tâche planifiée Windows
- [ ] 12. Feedback « pas intéressé » et lettres de motivation

## Installation (Windows 11)

Prérequis : Python 3.12 et Git.

Dans un terminal (PowerShell ou CMD), depuis le dossier du projet :

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
```

Ensuite, ouvre `.env` et remplis les clés au fur et à mesure (chaque ligne indique à quelle étape elle sert).

### Activer l'environnement virtuel (facultatif)

Une fois activé, tu peux taper `python` au lieu de `.venv\Scripts\python`.

- CMD : `.venv\Scripts\activate.bat`
- PowerShell : `.venv\Scripts\Activate.ps1`
  Si PowerShell refuse (« l'exécution de scripts est désactivée »), lance une seule fois :
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## Lancement manuel

```
.venv\Scripts\python run.py
```

Options :

| Commande | Effet |
|---|---|
| `run.py --auto` | passage automatique (tâche planifiée) : lance aussi les sources réservées au matin, comme Google Jobs |
| `run.py --source google_jobs` | lance une seule source, même désactivée ou réservée au mode auto |
| `run.py --source google_jobs --max-requetes 1` | test avec une seule requête (économise le quota) |
| `run.py --verifier` | affiche l'état de la base et les secrets manquants, sans rien collecter |

### Quota Google Jobs (SerpApi)

L'offre gratuite donne 250 recherches par mois. Par défaut, Google Jobs ne tourne qu'au passage automatique, avec 7 recherches par passage, soit environ 217 par mois. Avant de commencer, le programme demande à SerpApi combien de recherches il reste (cet appel est gratuit). Une recherche identique relancée dans l'heure est servie depuis le cache de SerpApi et n'est pas décomptée. Réglages : `sources.google_jobs` dans `config.yaml`.

## Tests

```
.venv\Scripts\python -m pytest
```

Les tests utilisent une vraie réponse enregistrée (`tests/donnees/`) : ils ne consomment aucun quota et ne touchent pas à ta base.

## Lancement de l'appli

À venir (étape 9).

## Tâche planifiée

À venir (étape 11).

## Organisation des fichiers

```
config.yaml            paramètres (critères, mots-clés, entreprises suivies, sources)
.env                   secrets (jamais sur Git) ; modèle dans .env.example
run.py                 lancement d'un passage
stage_scraper/
  config.py            lecture de config.yaml et .env
  db.py                tables SQLite, enregistrement des offres, journal
  offre.py             format commun d'une offre
  collecte.py          lance chaque source, isole les pannes, écrit le journal
  sources/             un module de collecte par source (google_jobs.py, ...)
tests/                 tests automatiques
data/stages.db         base SQLite (créée au premier lancement, jamais sur Git)
profil/cv.pdf          ton CV, utilisé par le scoring dès qu'il est présent (jamais sur Git)
```
