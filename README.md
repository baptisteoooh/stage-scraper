# Stage Scraper

Outil local qui collecte les offres de stage medtech / santé (profil IA / data), les dédoublonne, les note avec une IA (Gemini), les affiche dans une appli Streamlit, envoie un récap par mail et suit les candidatures.

Le cahier des charges complet est dans `CLAUDE.md`.

## État d'avancement

- [x] 1. Squelette, base SQLite, `config.yaml`, `.env.example`, Git
- [ ] 2. API France Travail (reportée : API suspendue par France Travail)
- [x] 3. Google Jobs (SerpApi) et Careerjet
- [ ] 4. Alertes Gmail (lecture du libellé faite ; parseurs à écrire quand les premiers mails arriveront)
- [ ] 5. Scraping direct LinkedIn et Indeed (mis de côté : LinkedIn l'interdit dans son robots.txt, Indeed bloque les robots avec un CAPTCHA ; on passe par leurs alertes email)
- [x] 6. Pages carrières (Ashby et Workday ; quelques entreprises restent à brancher)
- [x] 7. Dédoublonnage et pré-filtre
- [x] 8. Scoring IA (Gemini, offre gratuite ; il démarre dès que `GEMINI_API_KEY` est dans `.env`)
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

### Scoring IA (Gemini)

Chaque offre gardée par le tri est notée par Gemini (`gemini-3.5-flash-lite`, offre gratuite de Google AI Studio ; modèle réglable dans `config.yaml > scoring.modele`) : note de 0 à 10, catégorie (À postuler vite ≥ 8, À regarder 5–7, Bof < 5), section (Santé, Hors santé mais intéressant, À négocier), résumé, explication, durée et date de début lues dans l'offre, raison d'exclusion éventuelle.

- Clé : `GEMINI_API_KEY` dans `.env` (à créer gratuitement sur https://aistudio.google.com, bouton « Get API key », sans carte bancaire). Sans clé, les offres restent en attente et seront notées au premier passage qui en dispose.
- Le CV (`profil/cv.pdf`) et les offres marquées « pas intéressé » (avec leur raison) sont utilisés automatiquement : l'IA note plus bas les offres qui leur ressemblent.
- Coût : nul. L'offre gratuite limite le nombre de requêtes : les appels sont espacés (`scoring.delai_entre_appels_s`), et si le quota est atteint ou le modèle surchargé, le reste est noté au passage suivant. Les tokens de chaque passage sont dans le journal.

### Mails (alerte et récap)

- **Alerte immédiate**, à chaque passage (manuel ou auto) : offres notées ≥ 8, ou poste IA/data chez une
  entreprise suivie.
- **Récap quotidien**, au passage automatique de 8 h : nouvelles offres notées ≥ 5, pas encore envoyées.
- Une offre n'est jamais envoyée deux fois.
- Envoi par Gmail avec le même mot de passe d'application que la lecture des alertes. Destinataire :
  `EMAIL_DESTINATAIRE` dans `.env` (vide = `GMAIL_ADRESSE`).
- **Désactivé au départ** (`notifications.envoi_actif: false`) : chaque mail est écrit en aperçu dans
  `data/mails/apercu_alerte.html` et `apercu_recap.html`, et les offres restent à envoyer. Pour l'activer :
  vérifie l'aperçu (Plus › Réglages › Mails), lance `run.py --test-mail`, puis active l'interrupteur au même endroit.

## Tests

```
.venv\Scripts\python -m pytest
```

Les tests utilisent une vraie réponse enregistrée (`tests/donnees/`) : ils ne consomment aucun quota et ne touchent pas à ta base.

## Le nouveau site (en construction)

L'interface Streamlit est remplacée peu à peu par un site sur mesure (verre fumé sur Manhattan au crépuscule,
tri des offres d'un geste, façon Tinder).

```
.venv\Scripts\python site_web.py
```

Le site s'ouvre dans le navigateur (http://127.0.0.1:8000) et n'est visible que depuis ce PC.
Pour l'arrêter : `Ctrl + C` dans le terminal.

- **Accueil** : présentation et connexion. Pas encore de vrais comptes (version locale) : « Se connecter » fait entrer.
  La carte d'exemple se glisse déjà, pour essayer le geste.
- **À trier** : une offre à la fois. Glisse la carte **à droite** (Je candidate : elle part dans Ma sélection),
  **à gauche** (Pas pour moi) ou **vers le haut** (Plus tard). Un geste vif suffit, même court. Mêmes décisions
  avec les boutons ronds ou le clavier (← → ↑) ; **Ctrl+Z** annule. « Détails » (ou Entrée) ouvre l'annonce complète.
  Filtres en haut : Santé / Hors santé / À négocier / Plus tard, tri, offres « Bof » (moins de 5/10), recherche.
- **Ma sélection** : les offres gardées, rangées par étape (En préparation, Envoyées, Entretien, Terminées).
  Une fiche par offre : changer d'étape (« C'est envoyé », « J'ai relancé »), dates, notes (gardées toutes seules),
  « Retirer de ma sélection ». Chaque changement s'annule depuis le message en bas. **Offre trouvée ailleurs**
  ajoute une offre vue hors de l'outil.
  **Dossier de candidature** (bouton « Préparer » d'une carte) : l'IA analyse l'offre face à ton CV, propose
  des retouches de CV et rédige un premier jet de lettre (prix affiché avant, ≈ 8 c avec Claude, gratuit avec
  Gemini). Ensuite tu modifies la lettre toi-même (gardée toute seule) ou tu demandes des retouches dans la
  conversation à droite ; chaque version reste dans l'historique. « Télécharger (Word) » remet ton vrai nom.
- **Journal** : crédit Claude restant, dépense du mois, et chaque scrap (clique un passage pour le détail
  source par source, erreurs comprises).
- **Corbeille** : offres écartées par toi, par le tri, ou expirées. Rien n'est supprimé : « Remettre à trier ».
- **Réglages** : critères (ancienneté, contrats, postes et niveaux exclus), entreprises suivies, mails (seuil
  d'alerte, envoi, aperçus, mail de test), tes documents (CV, lettre modèle, et ce que l'IA en reçoit) et
  « Refaire le tri ». Un seul bouton **Enregistrer** (ou Ctrl+S) écrit config.yaml (copie dans config.yaml.bak).
- L'analyse face au CV, les conseils, la lettre et l'Assistant arrivent ensuite : en attendant, ils restent dans
  l'appli Streamlit ci-dessous (les deux utilisent la même base).

Pour essayer sans toucher à tes offres : copie `data\stages.db`, puis
`set STAGE_SCRAPER_BASE=chemin\de\la\copie.db` (CMD) ou `$env:STAGE_SCRAPER_BASE="chemin\de\la\copie.db"`
(PowerShell) avant `python site_web.py`. De même, `STAGE_SCRAPER_CONFIG` désigne une copie de config.yaml
(les Réglages écrivent alors dans la copie).

## Lancement de l'appli

```
.venv\Scripts\streamlit run app.py
```

L'appli s'ouvre dans le navigateur (http://localhost:8501). Elle n'est visible que depuis ce PC.
Elle suit le mode clair ou sombre de Windows (thème dans `.streamlit/config.toml`, styles dans `stage_scraper/style.py`).
Pour l'arrêter : `Ctrl + C` dans le terminal. Le menu en haut : **À trier · Ma sélection · Assistant · Plus**
(Plus = Réglages, Journal, Corbeille). Le style des pages sera revu plus tard : pour l'instant, elles sont simples.

- **À trier** : les offres sur lesquelles tu n'as pas encore décidé, comme une boîte de réception à vider.
  En haut : **🔄 Lancer le scrap** (le menu **⋯** choisit les sources) et une phrase sur le dernier scrap
  (heure, nouvelles offres, sources en erreur). Puis une recherche, le tri (**Plus récentes** par défaut, ou
  **Meilleure note**) et les filtres Toutes / Santé / Hors santé / À négocier / ⏳ Plus tard, avec leur nombre.
  Les offres « Bof » (note < 5) sont masquées : l'interrupteur **Voir les « Bof »** les affiche.
  Chaque vignette (note, entreprise, poste, lieu, durée, début, résumé de l'IA, badge « Nouvelle » pour le
  dernier scrap) a trois décisions en un clic : **✅ Je candidate** (l'offre part dans Ma sélection, aucune IA ne se
  lance), **👎 Pas pour moi** (raison facultative en un clic, réutilisée par l'IA), **⏳ Plus tard** (rangée à part).
  Un bandeau permet d'**annuler** la dernière décision, ou d'**ouvrir la fiche** de l'offre. **🔍 Détails**
  ouvre le détail complet (pourquoi cette note, description, contact, **Voir l'annonce ↗**) avec les mêmes boutons.
- **Ma sélection** : les offres gardées, rangées par étape : **En préparation**, **Envoyées**, **Entretien**,
  **Terminées** (avec leur nombre et le nombre d'actions à faire). Dans chaque étape, les offres qui demandent une
  action passent en premier, avec le bouton pour la faire : ✨ Préparer, 📨 Finir et envoyer, 🔔 J'ai relancé
  (la relance est due 7 jours après l'envoi, réglable dans `config.yaml` > `candidatures.relance_jours`),
  💬 Préparer l'entretien. Chaque action peut être annulée juste après. **＋ Offre trouvée ailleurs** ajoute une
  offre vue hors de l'outil (colle le texte de l'annonce pour que l'IA puisse l'analyser) ; **📥 Exporter en Excel**
  donne un fichier avec deux feuilles, Offres et Candidatures.
- **La fiche d'une offre** (bouton **Ouvrir**) : en haut, la barre **Où en est cette offre ?** (cliquer change
  l'étape et remplit les dates ; à l'étape Entretien, la date et l'heure ; à l'étape Terminée, refus ou accepté),
  **📨 C'est envoyé** et **Voir l'annonce ↗**. Rien ne part tout seul vers l'IA : le bouton **✨ Préparer avec l'IA**
  (prix affiché) lance l'analyse de l'offre face à ton CV puis un premier jet de lettre (à l'étape Entretien :
  l'analyse seule). Les onglets :
  - **L'offre** : résumé, pourquoi cette note, infos clés, description (modifiable pour une offre trouvée ailleurs) ;
  - **Lettre** : modifiable, tes modifications sont gardées toutes seules ; **Annuler**, historique des versions,
    export **Word** signé de ton nom ; une fois la candidature envoyée, la lettre gardée dans la candidature est figée ;
  - **Conseils CV** (avant / après, avec les mots de l'offre) et **Analyse** (exigences couvertes ou non, alertes et
    questions à poser au recruteur) ;
  - **Notes** : dates d'envoi et de relance, notes libres (gardées toutes seules), **Retirer de ma sélection**.

  À droite : la conversation avec l'IA pour demander des retouches (« plus court », « insiste sur mon projet
  Parkinson »), gardée pour reprendre plus tard. L'IA ne s'appuie que sur ton CV et l'offre : le code vérifie chaque
  citation, écarte les conseils qui citent une ligne absente du CV et signale sous la lettre toute affirmation qu'il
  ne retrouve pas dans ton CV. Modèles : Claude Sonnet pour l'analyse et le premier jet, Claude Haiku pour les
  retouches (clé `ANTHROPIC_API_KEY`, crédit prépayé), Gemini gratuit en secours. Un dossier complet coûte environ
  5 à 8 centimes ; le coût de chaque réponse s'affiche sous elle. Plafonds dans `config.yaml > claude` (1 $ par mois,
  4,50 $ au total) : au-delà, Gemini prend le relais.
- **Assistant** : un chat sur les offres collectées (« un stage en computer vision sur l'imagerie médicale »,
  « compare ces deux offres », « où en sont mes candidatures ? »). Il lit les annonces avant de répondre. La
  conversation est gardée ; **Nouvelle conversation** l'efface.
- **Plus › Réglages** : quatre onglets. **Critères** (ancienneté max, exclusions, entreprises suivies),
  **Mes documents** (ton CV en PDF et une lettre modèle ; ils restent dans `profil/`, jamais sur Git, et l'aperçu
  montre exactement le texte envoyé aux IA, sans coordonnées ni nom), **Mails** (seuil de l'alerte, envoi, aperçus,
  mail de test) et **Avancé** (refaire le tri des offres déjà collectées). Les domaines, secteurs, sources et
  modèles d'IA se règlent dans `config.yaml`.
- **Plus › Journal** : une ligne par passage (sources, offres trouvées, nouvelles, gardées, notées 8+, coût,
  erreurs), le crédit Claude restant estimé (le solde exact est dans la console Anthropic) et, en dessous, les appels
  d'IA faits depuis l'appli et le détail source par source.
- **Plus › Corbeille** : les offres écartées par toi (**Remettre à trier**), écartées par le tri automatique (pour
  vérifier qu'il ne se trompe pas) et expirées. Rien n'y est supprimé.

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
config.yaml            paramètres (critères, domaines, entreprises suivies, sources, modèles d'IA)
.env                   secrets (jamais sur Git) ; modèle dans .env.example
run.py                 lancement d'un passage
app.py                 lancement de l'appli (streamlit run app.py)
site_web.py            lancement du nouveau site (python site_web.py)
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
  scoring.py           note de chaque offre par Gemini
  claude.py            client Claude, prix, plafonds du crédit
  gemini.py            client de l'API Gemini
  chat_offres.py       assistant : chat sur les offres (agent qui lit les annonces)
  cv.py                texte anonymisé du CV et de la lettre modèle
  pipeline.py          un passage complet : collecte, tri, scoring
  appli.py             menu de l'appli Streamlit et page Assistant
  page_a_trier.py      page À trier (décisions, bouton de scrap)
  vignettes.py         vignettes d'offres, détail d'une offre, décisions
  selection.py         Ma sélection : étapes, prochaine action, changements d'étape (sans affichage)
  decisions.py         décisions sur une offre (Je candidate, Pas pour moi, Plus tard) et annulation
  presentation.py      mise en forme commune (lieu court, date de début, ancienneté)
  web/serveur.py       serveur du nouveau site (FastAPI) : pages et API
  web/statique/        pages HTML (_menu.html = menu commun), styles (css/), scripts (js/ : swipe.js = le geste,
                       commun.js = outils partagés), images (img/)
  page_selection.py    pages Ma sélection et fiche d'une offre
  page_plus.py         pages Réglages, Journal et Corbeille
  style.py             habillage de l'appli (typographie, cartes, accessibilité)
  requetes.py          lectures et écritures en base pour l'appli
  reglages.py          modification de config.yaml depuis l'appli
  export.py            export Excel
  dossier.py           dossier d'une offre : analyse, conseils CV, lettre, vérification des citations
  page_dossier.py      dossier dans la fiche : lettre, conseils CV, analyse, conversation
  notifications.py     mails d'alerte et de récap
planification/         tâche planifiée Windows (installer_tache.ps1, lancer_auto.cmd, desinstaller_tache.ps1)
tests/                 tests automatiques
data/stages.db         base SQLite (créée au premier lancement, jamais sur Git)
profil/cv.pdf          ton CV (jamais sur Git ; les IA n'en reçoivent que le texte anonymisé)
profil/modele_lettre.txt  une lettre écrite par toi, modèle de style (facultatif)
```
