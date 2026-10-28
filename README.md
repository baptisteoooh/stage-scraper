# Stage Scraper

Outil local qui collecte les offres de stage medtech / santé (profil IA / data), les dédoublonne, les note avec Claude, les affiche dans une appli Streamlit, envoie un récap par mail et suit les candidatures.

Le cahier des charges complet est dans `CLAUDE.md`.

## État d'avancement

- [x] 1. Squelette, base SQLite, `config.yaml`, `.env.example`, Git
- [ ] 2. API France Travail (reportée : API suspendue par France Travail)
- [x] 3. Google Jobs (SerpApi) et Careerjet
- [ ] 4. Alertes Gmail (lecture du libellé faite ; parseurs à écrire quand les premiers mails arriveront)
- [ ] 5. Scraping direct LinkedIn et Indeed (mis de côté : LinkedIn l'interdit dans son robots.txt, Indeed bloque les robots avec un CAPTCHA ; on passe par leurs alertes email)
- [x] 6. Pages carrières (Ashby et Workday ; quelques entreprises restent à brancher)
- [x] 7. Dédoublonnage et pré-filtre
- [x] 8. Scoring Claude (prêt ; il démarre dès que `ANTHROPIC_API_KEY` est dans `.env`)
- [x] 9. Appli Streamlit
- [x] 10. Mails (prêts ; envoi désactivé tant que tu n'as pas validé l'aperçu)
- [x] 11. Tâche planifiée Windows (scripts prêts ; à installer toi-même, une commande)
- [x] 12. Feedback « pas intéressé » et lettres de motivation

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
| `run.py --noter` | note avec l'IA les offres en attente, sans collecter (par exemple juste après avoir ajouté la clé) |
| `run.py --test-mail` | envoie un mail de test à ton adresse, pour vérifier l'envoi Gmail |
| `run.py --retraiter` | refait le tri (pré-filtre et doublons) de toutes les offres, sans collecter : à lancer après avoir modifié les critères de `config.yaml` |

### Quota Google Jobs (SerpApi)

L'offre gratuite donne 250 recherches par mois. Par défaut, Google Jobs ne tourne qu'au passage automatique, avec 7 recherches par passage, soit environ 217 par mois. Avant de commencer, le programme demande à SerpApi combien de recherches il reste (cet appel est gratuit). Une recherche identique relancée dans l'heure est servie depuis le cache de SerpApi et n'est pas décomptée. Réglages : `sources.google_jobs` dans `config.yaml`.

### Careerjet

Careerjet tourne à chaque passage, manuel ou auto, avec les 13 recherches de `config.yaml`. Il exige :
- la clé `CAREERJET_API_KEY` dans `.env` ;
- que l'adresse IP de ta box soit autorisée dans ton espace partenaire Careerjet ;
- l'en-tête Referer `https://ton-pseudo.github.io/`, ta page de présentation (réglage `sources.careerjet.referer`).

Si le journal affiche « Unauthorized access from IP », c'est que l'adresse IP de ta box a changé : ajoute la nouvelle adresse dans l'espace partenaire Careerjet.

### Alertes Gmail

Le programme lit, en lecture seule, les mails rangés sous le libellé `Alertes stage` (réglage `sources.gmail.libelle`) reçus ces 14 derniers jours. Il faut :
- `GMAIL_ADRESSE` et `GMAIL_MOT_DE_PASSE_APPLI` dans `.env` (mot de passe d'application créé sur https://myaccount.google.com/apppasswords, la validation en deux étapes doit être activée) ;
- un filtre Gmail qui range les mails d'alerte sous ce libellé (depuis un mail d'alerte : ⋮ > Filtrer les messages similaires).

Pour étudier le format des mails avant d'écrire un parseur :

```
.venv\Scripts\python -m stage_scraper.sources.gmail --telecharger
```

Les mails sont enregistrés dans `data/emails/` (jamais sur Git).

### Pages carrières

Les entreprises suivies qui ont un bloc `carrieres` dans `config.yaml` sont collectées directement sur leur outil de recrutement, via ses données JSON publiques. Seuls les stages et les CDD sont gardés. Outils gérés :
- **Ashby** (Doctolib, Owkin, Nabla, Lifen) : `carrieres: {outil: ashby, id: doctolib}`, l'identifiant étant la fin de l'adresse `jobs.ashbyhq.com/<identifiant>` ;
- **Workday** (Medtronic, J&J, GE HealthCare, Philips, Abbott, Stryker, BD) : `carrieres: {outil: workday, url: <adresse de la page carrières>}`, du type `https://<groupe>.wdN.myworkdayjobs.com/<site>`. Seules les offres en France sont lues : le module trouve tout seul le bon filtre.

### Tri des offres (pré-filtre et doublons)

Après chaque collecte, les nouvelles offres sont triées, sans appel à l'IA :
- **pré-filtre** : exclut d'après le titre les contrats refusés (alternance, CDI, VIE, fin d'études…), les postes non techniques et les niveaux senior ; puis les lieux hors Île-de-France, les offres trop anciennes, les durées et les dates de début hors critères (`criteres` et `exclusions` dans `config.yaml`). Une offre douteuse est gardée : l'IA tranchera. La raison de chaque exclusion est enregistrée (colonne `exclusion_prefiltre`) ;
- **doublons** : même entreprise (alias compris), titres très proches et même région. La première offre vue reste l'originale.

### Scoring IA (Claude)

Chaque offre gardée par le tri est notée par `claude-haiku-5-5` : note de 0 à 10, catégorie (À postuler vite ≥ 8, À regarder 5–7, Bof < 5), section (Santé, Hors santé mais intéressant, À négocier), résumé, explication, durée et date de début lues dans l'offre, raison d'exclusion éventuelle.

- Clé : `ANTHROPIC_API_KEY` dans `.env` (à créer sur https://console.anthropic.com, rubrique API Keys). Sans clé, les offres restent en attente et seront notées au premier passage qui en dispose.
- Le CV (`profil/cv.pdf`) et les offres marquées « pas intéressé » (avec leur raison) sont utilisés automatiquement : l'IA note plus bas les offres qui leur ressemblent.
- Coût : les consignes fixes sont mises en cache, seule l'offre change. Les tokens et le coût de chaque passage sont dans le journal ; le scoring s'arrête tout seul quand `scoring.budget_mensuel_usd` (2 $) est atteint dans le mois.

### Mails (alerte et récap)

- **Alerte immédiate**, à chaque passage (manuel ou auto) : offres notées ≥ 8, ou poste IA/data chez une
  entreprise suivie.
- **Récap quotidien**, au passage automatique de 8 h : nouvelles offres notées ≥ 5, pas encore envoyées.
- Une offre n'est jamais envoyée deux fois.
- Envoi par Gmail avec le même mot de passe d'application que la lecture des alertes. Destinataire :
  `EMAIL_DESTINATAIRE` dans `.env` (vide = `GMAIL_ADRESSE`).
- **Désactivé au départ** (`notifications.envoi_actif: false`) : chaque mail est écrit en aperçu dans
  `data/mails/apercu_alerte.html` et `apercu_recap.html`, et les offres restent à envoyer. Pour l'activer :
  vérifie l'aperçu (page Réglages > Mails), lance `run.py --test-mail`, puis active l'interrupteur dans Réglages.

## Tests

```
.venv\Scripts\python -m pytest
```

Les tests utilisent une vraie réponse enregistrée (`tests/donnees/`) : ils ne consomment aucun quota et ne touchent pas à ta base.

## Lancement de l'appli

```
.venv\Scripts\streamlit run app.py
```

L'appli s'ouvre dans le navigateur (http://localhost:8501). Elle n'est visible que depuis ce PC.
Elle suit le mode clair ou sombre de Windows (thème dans `.streamlit/config.toml`, styles dans `stage_scraper/style.py`).
Pour l'arrêter : `Ctrl + C` dans le terminal. Les pages sont dans le menu en haut.

- **Offres** : bouton **Lancer le scrap** (le menu **⋯** à côté choisit les sources et exporte en Excel), puis les offres
  en vignettes, de la mieux notée à la moins bien notée, en onglets
  Toutes sections / Santé / Hors santé mais intéressant / À négocier / En attente de note IA.
  **Toutes** (par défaut) : toutes les offres gardées, l'étiquette « Nouvelle » marque celles pas encore ouvertes ;
  **Nouvelles** : seulement celles-là ; **Dernier passage** : celles trouvées par le dernier scrap.
  Chaque vignette montre la note, l'entreprise, le poste, le lieu, la durée, le début, le télétravail, la
  gratification (si connue), le résumé de l'IA, un extrait de l'annonce et la date de publication. 24 vignettes s'affichent d'abord,
  **Afficher plus** ajoute les suivantes. **Voir la fiche** ouvre le détail : explication de la note, contact, liens,
  description (Careerjet ne transmet qu'un extrait : le texte complet est sur le site), boutons **Postuler** (crée une candidature), **Pas intéressé** (avec une raison
  facultative, réutilisée par l'IA) et **Lettre de motivation**. **Ouvrir l'offre ↗** mène directement au site.
  En bas, la liste des offres écartées par le tri, pour vérifier qu'il ne se trompe pas.
- **Candidatures** : une colonne par étape (À postuler, Postulé, Relancé, Entretien), une carte par
  candidature ; les candidatures terminées (acceptées ou refusées) sont rangées dans le volet **Terminées**. Le bouton bleu de la carte passe à l'étape suivante et remplit les dates (envoi, rappel de relance
  7 jours après, réglable dans `config.yaml` > `candidatures.relance_jours`). **Détails** ouvre une fenêtre pour tout
  modifier ou supprimer ; chaque action peut être annulée juste après. **＋ Nouvelle candidature** pour une
  candidature faite hors de l'outil. Une vue tableau reste disponible en bas de page.
- **Lettres** : choisis une offre (ou clique **Lettre de motivation** sur sa fiche), ajoute des
  consignes si tu veux, puis **Rédiger le brouillon**. Claude s'appuie sur l'offre, ton profil et ton CV, sans rien
  inventer : les repères [à compléter : …] sont pour toi. Le brouillon se modifie, se télécharge en .txt ou se garde
  dans la candidature. Coût : moins d'un centime par lettre, compté dans le même budget mensuel que le scoring.
- **Journal** : historique des passages et coût IA (mois en cours et cumulé).
- **Exporter en Excel** (en haut de la page Candidatures, ou menu **⋯** de la page Offres) : un fichier avec deux feuilles, Offres et Candidatures.

## Tâche planifiée

Un passage automatique chaque jour à 8 h (`run.py --auto`) : collecte (y compris Google Jobs), tri, notation IA,
alerte et récap par mail. Si le PC est éteint ou en veille à 8 h, le passage se fait dès que possible après.
La tâche tourne avec ton compte Windows, quand ta session est ouverte.

Installer (ou mettre à jour) la tâche, depuis le dossier du projet, dans PowerShell ou CMD :

```
powershell -ExecutionPolicy Bypass -File planification\installer_tache.ps1
```

Autre heure : ajoute `-Heure 07:30` à la fin.

- Tester tout de suite : `powershell -Command "Start-ScheduledTask -TaskName 'Stage Scraper'"`
  (ou Planificateur de tâches > Bibliothèque > Stage Scraper > Exécuter).
- Messages des passages automatiques : `logs\auto.log`.
- Supprimer la tâche : `powershell -ExecutionPolicy Bypass -File planification\desinstaller_tache.ps1`
- Vérifier le lanceur sans rien collecter : `planification\lancer_auto.cmd --verifier` (le résultat est dans `logs\auto.log`).

## Organisation des fichiers

```
config.yaml            paramètres (critères, mots-clés, entreprises suivies, sources)
.env                   secrets (jamais sur Git) ; modèle dans .env.example
run.py                 lancement d'un passage
app.py                 lancement de l'appli (streamlit run app.py)
.streamlit/config.toml réglages de l'appli (visible seulement depuis ce PC)
stage_scraper/
  config.py            lecture de config.yaml et .env
  db.py                tables SQLite, enregistrement des offres, journal
  offre.py             format commun d'une offre
  collecte.py          lance chaque source, isole les pannes, écrit le journal
  sources/             un module de collecte par source (google_jobs.py, careerjet.py, ...)
  prefiltre.py         exclusions et critères (contrat, lieu, durée, dates)
  dedoublonnage.py     repérage d'une même offre publiée sur plusieurs sites
  traitement.py        pré-filtre + doublons des nouvelles offres
  scoring.py           note de chaque offre par Claude
  pipeline.py          un passage complet : collecte, tri, scoring
  appli.py             pages de l'appli Streamlit
  suivi.py             page Candidatures (colonnes par étape, cartes, fenêtres)
  style.py             habillage de l'appli (typographie, cartes, accessibilité)
  requetes.py          lectures et écritures en base pour l'appli
  reglages.py          modification de config.yaml depuis l'appli
  export.py            export Excel
  lettre.py            brouillons de lettres de motivation
  notifications.py     mails d'alerte et de récap
planification/         tâche planifiée Windows (installer_tache.ps1, lancer_auto.cmd, desinstaller_tache.ps1)
tests/                 tests automatiques
data/stages.db         base SQLite (créée au premier lancement, jamais sur Git)
profil/cv.pdf          ton CV, utilisé par le scoring dès qu'il est présent (jamais sur Git)
```
