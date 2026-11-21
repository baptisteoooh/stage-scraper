# DESIGN.md — Stage Scraper (site web)

Système visuel du site FastAPI (`python site_web.py`), relevé sur le code livré en novembre 2026.
Direction **« Brume mauve »**, choisie par BAP le 19/11/2026. Le produit (pour qui, quoi, vocabulaire) est
dans `PRODUCT.md`. Les fichiers de style sont dans `stage_scraper/web/statique/css/`.

## Idée
Une offre à la fois, posée en carte de verre sur une ville au crépuscule ; on trie d'un geste, comme un paquet
de cartes. Look Apple : aéré, fluide, reposant, peu d'informations à la fois, le moins de clics possible.
Refusé par BAP : look « site IA » (sphère, dégradé ou bouton violet), bleu et noir sur les boutons, orange,
coins droits ou coupés, coins trop ronds, police Unbounded, contour vert sur la carte.

## Fond
- Photo de **Manhattan au crépuscule fournie par BAP** (`stage_scraper/web/statique/img/fond-manhattan.jpg`), floutée et assombrie à
  gauche et en haut (`.fond`), version uniforme plus sombre sur les pages de travail (`.fond.uni`).
- Le mauve vit dans la photo ; l'interface reste neutre (blanc cassé, lavande claire).

## Couleurs (`site.css`, `:root`)
| Jeton | Valeur | Rôle |
|---|---|---|
| `--texte` | `#F3EEF7` | texte principal |
| `--doux` | `#BDB2C9` | texte secondaire |
| `--faible` | `#9E92AD` | légendes, aides |
| `--accent` / `--sur-accent` | `#EDE6F6` / `#221A2E` | bouton principal (pilule blanc lilas, texte prune) |
| `--lavande` | `#CDB8E8` | contour de la carte active, état « sélection » |
| `--note` | `#E3D4F2` | la note /10 |
| `--oui` / `--non` | `#BFE5C9` / `#F2B5BF` | Je candidate / Pas pour moi (vert et rose pâles) |
| `--verre`, `--verre-fort` | prune translucide à 62 % / 90 % | fenêtre, cartes, panneau |
| `--ligne`, `--ligne-forte` | blanc à 12 % / 20 % | filets |
| ambre doux `#F4D9A8` | — | alertes de l'IA, « à vérifier », adéquation partielle |

Thème sombre seulement (`color-scheme: dark`).

## Typographie
- **Sora** (600) pour les titres, avec un léger resserrement (`letter-spacing: -.03em`) ; **Geist** pour le
  texte (choix de BAP, exception notée dans `.impeccable/config.json`).
- Corps 14–15 px, interligne 1.5–1.7 ; légendes 12–13,5 px en `--doux` ou `--faible` ; chiffres alignés
  (`tabular-nums`) dans les compteurs et le journal.

## Formes et matières
- Arrondis : carte **8 px** (`--r-carte`), panneaux 12 px, fenêtre 18 px ; pilules pour les filtres et
  boutons secondaires (`.pastille`) ; boutons ronds pour le tri.
- Verre : `backdrop-filter: blur(24–30px)`, filet intérieur blanc à 10–12 %, ombre portée prune très douce.
- La carte au-dessus du paquet a un **contour lavande** ; les deux suivantes dépassent dessous, floutées.
- Note affichée « NOTE 9/10 » (« SCORE » en anglais), grand chiffre Sora.

## Mouvement
- Courbes : `--ressort` `cubic-bezier(.2, .9, .3, 1.15)` (léger rebond) et `--sortie`
  `cubic-bezier(.22, .8, .32, 1)`.
- **Signature : le glissement de carte** (`stage_scraper/web/statique/js/swipe.js`, Pointer Events + Web Animations) : la carte suit le
  doigt, s'incline, se teinte vert ou rose, part ; la suivante monte du paquet. Mesuré à ~60 images/s
  (écart médian 16,7 ms), en français comme en anglais.
- Changement d'étape dans Ma sélection : View Transitions ; panneau de droite qui glisse ; entrées en fondu
  montant (`@keyframes entre`) ; trois points qui sautillent seulement pendant qu'une réponse d'IA arrive.
- « Réduire les animations » : fondus simples, pas de rebond ni de points animés.

## Composants
- **Coquille** (`app.css`, `_menu.html`) : fenêtre de verre centrée, menu à gauche (marque, Lancer le scrap,
  À trier / Ma sélection / Assistant, Plus : Mon profil / Réglages / Journal / Corbeille, encart « Dernier scrap »,
  sélecteur FR · EN). Sur téléphone (≤ 900 px) : barre du haut, menu masqué.
- **Panneau de détail** (`.fiche`) : glisse depuis la droite, Échap pour fermer ; s'élargit à 1180 px pour le
  dossier de candidature (lettre et onglets à gauche, conversation à droite).
- **Toast** en bas : message court + « Annuler » (toute décision s'annule).
- **Bulles de conversation** (`.bulle.ia` / `.bulle.moi`) et zone de saisie (`.saisie`), communes au dossier
  et à l'Assistant.
- **Fiche calme** (Mon profil, `stage_scraper/web/statique/css/profil.css`) : la phrase de recherche en grand, puis UNE ligne par
  rubrique (`.ligne-lue` : titre gris, résumé, **Modifier** discret ; toute la ligne ouvre la rubrique), séparées
  par un filet, sans cartes ; au-delà de 3 éléments, un compteur `+6` (`.en-plus`). Les réglages techniques
  (recherches, filtres fins) sont repliés sous un lien. Le chat ne montre que le dernier échange (les anciens
  derrière « Voir les N messages précédents ») et 3 suggestions en un clic tirées du profil. Le chat est une
  carte de verre posée dans la page (coins 18px, léger dégradé lavande en haut), les messages de l'étudiant en
  lavande translucide, la saisie une seule pilule avec le bouton d'envoi dedans (éteint tant qu'elle est vide).
- **À revoir** (`.a-revoir`, Mon profil) : encadré lavande translucide en haut de la fiche, titre en petites
  capitales lavande avec un compteur ; chaque proposition = constat en gris, question en clair, **Oui** (pilule
  claire) et **Non** (texte). La proposition traitée se replie en douceur. Absent quand il n'y a rien à revoir. Une seule rubrique s'ouvre à la fois (`.ouverte` : verre plus clair, contour lavande, ombre douce ;
  les autres passent à 34 % d'opacité et deviennent inertes) avec son pied **Annuler / Enregistrer** collé en
  bas de l'écran. Les rubriques modifiées par l'agent s'éclairent un instant en lavande (`.flash`). Les valeurs
  en phrases (dates, durées) sont écrites entières dans chaque langue (dans `profil.js`).
- **Surfaces du navigateur** (`site.css`) : barres de défilement fines lavande sans rail (presque invisibles au
  repos, plus nettes au survol de la zone), sélection de texte lavande, curseur de saisie lavande.
- **Pastilles** d'information sur les cartes (`.puces`) : IA / data, CDD, durée, début, gratification ;
  « Durée ? » en gris si inconnue.

## Langues
Français d'abord ; anglais via `stage_scraper/web/statique/i18n/en.json` (voir README). Les offres et les textes de l'IA ne sont
jamais traduits (zones `translate="no"`).

## Contrôles
Essais dans Chrome sans fenêtre (Playwright) à 1440×900, 1280×720 et 390×844 : pas de défilement horizontal,
aucune erreur de console, tout utilisable au clavier (← → ↑, Ctrl+Z, Ctrl+S dans Réglages, Entrée pour envoyer).
