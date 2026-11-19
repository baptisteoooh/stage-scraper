# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Interface web sur mesure (HTML/CSS) servie par un petit serveur Python, qui remplacera les pages Streamlit actuelles.
Toute la logique Python existante (collecte, tri, notation, sélection, dossier, mails) est conservée et appelée par
cette interface. Choix précis du framework (FastAPI proposé) délégué, à confirmer au début de la construction.

## Users

- **Aujourd'hui : BAP**, étudiant ingénieur qui cherche un stage en Île-de-France. Il travaille sur PC, en
  **longues sessions** : il trie les nouvelles offres puis prépare plusieurs candidatures d'affilée (lecture des
  annonces, lettre de motivation, conversation avec l'IA, suivi des relances).
- **Plus tard : tout étudiant** qui cherche un stage, quel que soit son domaine. Pas encore pris en compte : on construit
  d'abord pour BAP, on adaptera ensuite.

## Product Purpose

Les offres de stage sont éparpillées sur une quarantaine de sites. L'outil les collecte automatiquement (alertes
mail, API d'agrégateurs, pages carrières), les dédoublonne, les note avec une IA selon le profil de l'étudiant, puis
l'accompagne jusqu'à la réponse : tri des offres, préparation de la candidature (analyse face au CV, conseils CV,
lettre), envoi, relances, entretiens. Succès : ne rater aucune offre pertinente, trier vite, et envoyer de meilleures
candidatures en moins de temps.

## Positioning

Un seul outil du repérage jusqu'à la réponse : les offres de tous les sites, notées pour un profil précis, et
pour chacune une fiche qui réunit l'annonce, la lettre, les conseils CV et le suivi. L'IA ne s'appuie que sur le CV
réel et l'offre : chaque citation est vérifiée, et toute affirmation absente du CV est signalée.

## Operating Context

- Parcours : **À trier** (nouvelles offres, une décision en un clic : je candidate, pas pour moi, plus tard) →
  **Ma sélection** (offres gardées par étape : En préparation, Envoyées, Entretien, Terminées, avec la prochaine action
  de chacune) → **fiche d'une offre** (offre, lettre, conseils CV, analyse, notes, conversation avec l'IA).
  Autour : **Assistant** (chat sur les offres et les candidatures) et **Plus** (Réglages, Journal, Corbeille).
- Un scrap automatique chaque matin à 8 h, et à la main environ deux fois par jour ; un récap par mail et une alerte
  immédiate pour les meilleures offres.
- Les offres sont en français et en anglais.

## Capabilities and Constraints

- Vocabulaire fixé avec BAP : À trier, Je candidate, Pas pour moi, Plus tard, Ma sélection, fiche, En préparation,
  Envoyées, Entretien, Terminées, Corbeille.
- Notation des offres et Assistant : Gemini (gratuit). Analyse et lettre : Claude, crédit prépayé de 5 $ sans
  recharge (plafonds 1 $/mois, 4,50 $ au total), avec Gemini en secours. Aucun appel payant ne part sans un clic,
  et le prix est affiché sur le bouton.
- Toute décision est annulable juste après ; ce qui est tapé (lettre, notes, dates) est gardé tout seul.
- Données personnelles : le CV et les secrets restent sur la machine ; les IA ne reçoivent que le texte anonymisé
  du CV (sans nom ni coordonnées).
- Sources : pas de compte LinkedIn ou Indeed, pas de contournement de CAPTCHA, respect du robots.txt.
- **Décisions ouvertes :**
  - l'outil deviendra un **site en ligne partagé** avec des comptes (choix de BAP) ; aujourd'hui il tourne en local
    pour BAP seul. Comptes, hébergement, clés d'API et quotas par utilisateur, et sources utilisables par un site
    partagé restent à décider ;
  - l'interface doit exister en **français et en anglais** : textes prévus pour être traduits, le français d'abord.

## Brand Commitments

- Nom actuel : « Stage Scraper ».
- Ton : simple et direct, en tutoiement ; phrases courtes, aucun jargon technique pour l'utilisateur.

## Evidence on Hand

- Données réelles dans la base locale (`data/stages.db`, non versionnée) : plusieurs centaines d'offres collectées,
  notées et triées, et les premières candidatures.
- CV de BAP dans `profil/` (privé, jamais versionné ni montré).
- Aucun témoignage, utilisateur externe ni chiffre d'usage : ne pas en inventer.

## Product Principles

1. **Le moins de clics possible** : chaque décision se prend en un clic, depuis l'endroit où l'on est, et s'annule.
2. **Toujours savoir quoi faire ensuite** : chaque offre gardée affiche sa prochaine action, les urgentes d'abord.
3. **Rien de payant ou d'irréversible sans le dire** : coût affiché avant l'appel, aucun envoi automatique.
4. **L'IA prouve ce qu'elle avance** : elle ne s'appuie que sur le CV et l'offre, et signale ce qu'elle ne peut pas
   justifier.
5. **Pensé pour BAP, prêt pour les autres** : rien en dur qui empêche plus tard un autre profil, une autre langue
   ou un usage en ligne.

## Accessibility & Inclusion

Contraste WCAG AA, navigation au clavier, respect du réglage « réduire les animations » et des modes clair et sombre
du système (déjà appliqués dans l'appli actuelle).
