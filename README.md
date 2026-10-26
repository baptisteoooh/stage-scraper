# Stage Scraper

Outil local qui collecte les offres de stage medtech / santé (profil IA / data), les dédoublonne, les note avec Claude, les affiche dans une appli Streamlit, envoie un récap par mail et suit les candidatures.

Le cahier des charges complet est dans `CLAUDE.md`.

## État d'avancement

- [x] 1. Squelette, base SQLite, `config.yaml`, `.env.example`, Git
- [ ] 2. API France Travail (reportée : API suspendue par France Travail)
- [ ] 3. API Adzuna
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

Option `--auto` : passage automatique (utilisé par la tâche planifiée, envoie aussi le récap du jour).

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
  db.py                tables SQLite
  sources/             un module de collecte par source
data/stages.db         base SQLite (créée au premier lancement, jamais sur Git)
profil/cv.pdf          ton CV, utilisé par le scoring dès qu'il est présent (jamais sur Git)
```
