// Page À trier : le paquet de cartes, les filtres, les décisions (geste, boutons, clavier), l'annulation,
// la fiche détaillée et le scrap manuel.
import { Glisseur } from './swipe.js';
import { $, h, api, toast, cacherToast, afficherScrap, brancherScrap, detailOffre } from './commun.js';

const SECTIONS = [
  { cle: 'toutes', nom: 'Toutes les offres' },
  { cle: 'Santé', nom: 'Mon secteur' },          // la section de l'IA garde son nom en base
  { cle: 'Hors santé mais intéressant', nom: 'Autres secteurs' },
  { cle: 'À négocier', nom: 'À négocier' },
  { cle: 'plus_tard', nom: 'Plus tard' },
];
const ORDRES = [{ cle: 'recentes', nom: 'Plus récentes' }, { cle: 'note', nom: 'Meilleure note' }];
const RAISONS = ['Trop long (6 mois)', 'Commercial / pas technique', 'Pas mon domaine', 'Dates incompatibles',
  'Hors Île-de-France', 'Entreprise'];
const ACTION = { droite: 'candidate', gauche: 'ecarte', haut: 'plus_tard' };
const TEXTE_ACTION = { candidate: 'ajoutée à Ma sélection', ecarte: 'écartée', plus_tard: 'rangée pour plus tard',
  remettre: 'remise à trier' };

const etat = {
  toutes: [],          // toutes les offres à trier (y compris « plus tard » et « bof »)
  section: 'toutes',
  tri: 'recentes',     // ou 'note'
  bof: false,
  recherche: '',
  historique: [],      // décisions de la visite, pour Ctrl+Z
  glisseur: null,
  occupe: false,       // une carte est en train de partir
};

// ======================================================================= données

async function charger() {
  const d = await api('/api/a-trier');
  etat.toutes = d.offres;
  $('#nb-selection').textContent = d.selection || '';
  afficherScrap(d.scrap);
  if (d.ia_manquante) toast("Des offres attendent la note de l'IA : ajoute GEMINI_API_KEY dans .env.");
  rafraichir();
}

function correspond(o, recherche) {
  const texte = [o.titre, o.entreprise, o.lieu, o.resume].join(' ').toLowerCase();
  return recherche.toLowerCase().split(/\s+/).filter(Boolean).every(m => texte.includes(m));
}

function visibles() {
  let liste = etat.toutes.filter(o => (etat.section === 'plus_tard') === o.plus_tard);
  if (etat.section !== 'toutes' && etat.section !== 'plus_tard') liste = liste.filter(o => o.section === etat.section);
  if (!etat.bof && etat.section !== 'plus_tard') liste = liste.filter(o => !o.bof);
  if (etat.recherche.trim()) liste = liste.filter(o => correspond(o, etat.recherche));
  const note = o => (o.score === null ? -1 : o.score);
  return liste.sort(etat.tri === 'note'
    ? (a, b) => note(b) - note(a) || b.date.localeCompare(a.date) || b.id - a.id
    : (a, b) => b.date.localeCompare(a.date) || note(b) - note(a) || b.id - a.id);
}

// ======================================================================= barre du haut

function compteSection(cle) {
  return etat.toutes.filter(o => cle === 'plus_tard' ? o.plus_tard
    : !o.plus_tard && (etat.bof || !o.bof) && (cle === 'toutes' || o.section === cle)).length;
}

// Le bouton dit ce qui est affiché : « Mon secteur 30 · meilleure note · Bof inclus ».
function dessinerBarre() {
  $('#filtres-libelle').textContent = SECTIONS.find(s => s.cle === etat.section).nom;
  $('#filtres-nb').textContent = String(compteSection(etat.section));
  $('#filtres-details').replaceChildren(
    ...(etat.tri === 'note' ? [h('span', {}, 'meilleure note')] : []),
    ...(etat.bof && etat.section !== 'plus_tard' ? [h('span', {}, 'Bof inclus')] : []));
  $('#nb-a-trier').textContent = compteSection('toutes') || '';
  if (menuOuvert()) dessinerMenu();
}

// ======================================================================= menu des filtres

// Coche d'un choix (un SVG doit être créé dans son propre espace de noms : on passe par innerHTML, texte fixe).
function coche() {
  const s = document.createElement('span');
  s.className = 'coche';
  s.setAttribute('aria-hidden', 'true');
  s.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" '
    + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  return s;
}

function element(role, choisi, contenu, choisir) {
  return h('button', { type: 'button', role, 'aria-checked': String(choisi), tabindex: '-1', onclick: choisir }, contenu);
}

function dessinerMenu() {
  const nbBof = etat.toutes.filter(o => o.bof && !o.plus_tard).length;
  $('#menu-filtres').replaceChildren(
    h('h3', { role: 'presentation' }, 'Afficher'),
    ...SECTIONS.map(s => element('menuitemradio', etat.section === s.cle,
      [coche(), h('span', { class: 'nom' }, s.nom), h('span', { class: 'nb' }, String(compteSection(s.cle)))],
      () => choisir({ section: s.cle }))),
    h('hr', { role: 'separator' }),
    h('h3', { role: 'presentation' }, 'Ordre'),
    ...ORDRES.map(o => element('menuitemradio', etat.tri === o.cle,
      [coche(), h('span', { class: 'nom' }, o.nom)], () => choisir({ tri: o.cle }))),
    h('hr', { role: 'separator' }),
    element('menuitemcheckbox', etat.bof,
      [h('span', { class: 'nom' }, `Montrer les Bof (${nbBof})`, h('small', {}, 'Offres notées moins de 5/10')),
        h('span', { class: 'interrupteur', 'aria-hidden': 'true' }, h('i'))],
      () => choisir({ bof: !etat.bof })));
}

function menuOuvert() { return $('#menu-filtres').classList.contains('ouvert'); }

function ouvrirMenu() {
  dessinerMenu();
  $('#menu-filtres').classList.add('ouvert');
  $('#filtres').setAttribute('aria-expanded', 'true');
  const items = elementsMenu();
  (items.find(b => b.getAttribute('aria-checked') === 'true') || items[0])?.focus();
}

function fermerMenu({ rendreFocus = true } = {}) {
  if (!menuOuvert()) return false;
  $('#menu-filtres').classList.remove('ouvert');
  $('#filtres').setAttribute('aria-expanded', 'false');
  if (rendreFocus) $('#filtres').focus();
  return true;
}

function elementsMenu() { return [...$('#menu-filtres').querySelectorAll('[role^="menuitem"]')]; }

// Un choix referme le menu (on voit tout de suite le paquet changer) ; l'interrupteur Bof aussi.
function choisir(changement) {
  Object.assign(etat, changement);
  fermerMenu();
  rafraichir({ distribuer: true });
}

function clavierMenu(e) {
  const items = elementsMenu();
  const i = items.indexOf(document.activeElement);
  const aller = (n) => { e.preventDefault(); items[(n + items.length) % items.length].focus(); };
  if (e.key === 'ArrowDown') aller(i + 1);
  else if (e.key === 'ArrowUp') aller(i - 1);
  else if (e.key === 'Home') aller(0);
  else if (e.key === 'End') aller(items.length - 1);
  else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); fermerMenu(); }
  else if (e.key === 'Tab') fermerMenu({ rendreFocus: false });
}

// ======================================================================= cartes

// Carte d'une offre : tout ce qu'il faut pour décider sans ouvrir les détails (résumé de la mission en entier,
// extrait de l'annonce ; la raison de la note reste dans « Détails »). Si c'est long, le milieu défile dans la carte au lieu d'être coupé.
function contenuCarte(o) {
  const meta = [o.anciennete, o.site].filter(Boolean).join(' · ');
  return [
    h('span', { class: 'tampon tard', 'aria-hidden': 'true' }, etat.section === 'plus_tard' ? 'À trier' : 'Plus tard'),
    h('div', { class: 'haut' },
      h('span', { class: 'qui' }, h('b', {}, o.entreprise), o.lieu ? ` · ${o.lieu}` : '',
        o.nouvelle ? h('span', { class: 'etiquette' }, 'Nouvelle') : null),
      o.score === null
        ? h('span', { class: 'score', title: "Pas encore notée par l'IA" }, '—')
        : h('span', { class: 'score', 'aria-label': `Note ${o.score} sur 10` }, String(o.score), h('small', {}, '/10'))),
    h('h3', {}, o.titre),
    h('div', { class: 'puces' }, o.puces.map(p => h('span', { class: p.type }, p.texte))),
    h('div', { class: 'defile' },
      o.resume ? h('p', { class: 'resume' }, o.resume) : null,
      o.extrait ? h('div', { class: 'extrait' }, h('h4', {}, "Dans l'annonce"), h('p', { translate: 'no' }, o.extrait)) : null),
    h('div', { class: 'pied' },
      o.lien ? h('a', { href: o.lien, target: '_blank', rel: 'noopener' }, "Voir l'annonce ↗") : null,
      h('button', { type: 'button', onclick: () => ouvrirFiche(o.id) }, 'Détails'),
      h('span', { class: 'meta' }, meta)),
  ];
}

function niveau(score) { return score === null ? 'aucun' : score >= 8 ? 'haut' : score >= 5 ? 'moyen' : 'bas'; }

function nouvelleCarte(o, pos) {
  return h('article', { class: `carte pos${pos}`, 'data-id': o.id, 'data-niveau': niveau(o.score), 'aria-label': `${o.titre}, ${o.entreprise}` },
    contenuCarte(o));
}

// Reconstruit le paquet (après un filtre, un chargement, une annulation).
// distribuer : après un changement de filtre, les cartes arrivent l'une après l'autre (on voit que ça a changé,
// même quand la première carte reste la même).
function rafraichir({ distribuer = false } = {}) {
  dessinerBarre();
  const liste = visibles();
  const pile = $('#pile');
  etat.glisseur?.detruire();
  etat.glisseur = null;
  pile.replaceChildren();
  liste.slice(0, 3).reverse().forEach((o, i, t) => pile.append(nouvelleCarte(o, t.length - 1 - i)));
  activerDessus();
  majCompte();
  if (distribuer) distribuerPaquet();
}

// Le paquet entier apparaît d'un bloc (l'opacité s'applique au groupe : on ne voit pas une carte à travers
// l'autre), et les cartes du dessous glissent à leur place juste après, comme un paquet qu'on redistribue.
function distribuerPaquet() {
  const pile = $('#pile');
  const reduit = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const courbe = 'cubic-bezier(.22, .8, .32, 1)';
  pile.animate(reduit ? [{ opacity: 0 }, { opacity: 1 }]
    : [{ opacity: 0, translate: '0 22px', scale: '.98' }, { opacity: 1, translate: '0 0', scale: '1' }],
  { duration: reduit ? 160 : 380, easing: courbe });
  if (!reduit) {
    for (const el of pile.querySelectorAll('.carte.pos1, .carte.pos2')) {
      const pos = el.classList.contains('pos2') ? 2 : 1;
      el.animate([{ translate: `0 ${-12 * pos}px` }, { translate: '0 0' }],
        { duration: 420, delay: 120 + pos * 50, easing: 'cubic-bezier(.2, .9, .3, 1.15)', fill: 'backwards' });
    }
  }
  $('#compte').animate([{ opacity: .2 }, { opacity: 1 }], { duration: 400, easing: 'ease-out' });
}

function majCompte() {
  const n = visibles().length;
  $('#compte').textContent = n ? `1 sur ${n}` : '';
  const vide = n === 0;
  for (const b of ['#bouton-non', '#bouton-tard', '#bouton-oui', '#fleche-non', '#fleche-oui']) $(b).disabled = vide;
  if (vide && !$('#pile .vide')) $('#pile').append(messageVide());
}

function messageVide() {
  if (etat.recherche.trim()) return h('div', { class: 'vide' }, h('h3', {}, 'Rien ne correspond'),
    h('p', {}, 'Aucune offre à trier ne contient ces mots.'));
  if (etat.section === 'plus_tard') return h('div', { class: 'vide' }, h('h3', {}, 'Rien de côté'),
    h('p', {}, 'Glisse une carte vers le haut pour la garder pour plus tard.'));
  if (etat.section !== 'toutes') return h('div', { class: 'vide' }, h('h3', {}, 'Section vide'),
    h('p', {}, 'Plus aucune offre à trier ici.'));
  return h('div', { class: 'vide' }, h('h3', {}, 'Tout est trié'),
    h('p', {}, 'Les nouvelles offres arrivent tous les jours à 8 h, ou quand tu lances un scrap.'),
    h('button', { class: 'bouton principal', type: 'button', onclick: () => $('#scrap').click() }, 'Lancer le scrap'));
}

function carteDessus() { return $('#pile .carte.pos0'); }

function activerDessus() {
  const carte = carteDessus();
  if (!carte) return;
  const suivante = $('#pile .carte.pos1');
  etat.glisseur = new Glisseur(carte, {
    haut: true,
    auBouger: ({ dir, force, retour, depart }) => suivreGeste(carte, suivante, dir, force, retour, depart),
    auLacher: (dir, fin) => decider(dir, fin),
  });
}

// Pendant le geste : flèche du côté qui grossit, carte suivante qui se rapproche (tampon seulement vers le haut : « Plus tard »).
function suivreGeste(carte, suivante, dir, force, retour, depart) {
  carte.querySelector('.tampon.tard').style.opacity = dir === 'haut' ? force : 0;
  const g = $('#fleche-non'), d = $('#fleche-oui');
  g.style.setProperty('--force', dir === 'gauche' ? force : 0);
  d.style.setProperty('--force', dir === 'droite' ? force : 0);
  g.classList.toggle('actif', dir === 'gauche' && force > .99);
  d.classList.toggle('actif', dir === 'droite' && force > .99);
  if (!suivante) return;
  if (retour || depart) {
    suivante.style.transition = '';
    suivante.style.transform = depart ? 'translateY(0) scale(1)' : '';
    suivante.style.setProperty('--revele', depart ? 1 : 0);
    return;
  }
  suivante.style.transition = 'none';
  suivante.style.transform = `translateY(${14 * (1 - force)}px) scale(${.955 + .045 * force})`;
  suivante.style.setProperty('--revele', force);
}

// ======================================================================= décisions

// fin : promesse de l'animation déjà lancée par le geste ; sinon (bouton, clavier) on lance la carte ici.
async function decider(dir, fin = null) {
  const carte = carteDessus();
  if (!carte || etat.occupe || !etat.glisseur) return;
  etat.occupe = true;
  const id = Number(carte.dataset.id);
  const o = etat.toutes.find(x => x.id === id);
  const action = dir === 'haut' && etat.section === 'plus_tard' ? 'remettre' : ACTION[dir];
  const envoi = api('/api/decision', { offre_id: id, action });     // en même temps que l'animation
  await (fin || etat.glisseur.envoyer(dir, 0));
  avancer(o, action);
  etat.occupe = false;
  try {
    const decision = await envoi;
    etat.historique.push({ decision, offre: o, dir });
    toastDecision(decision, o);
  } catch (e) {
    console.error(e);
    remettre(o, action);
    toast("La décision n'a pas été enregistrée : réessaie.");
  }
}

// La carte est partie : on la retire de la liste, la suivante prend sa place (en glissant), une autre apparaît.
function avancer(o, action) {
  if (action === 'candidate' || action === 'ecarte') etat.toutes = etat.toutes.filter(x => x.id !== o.id);
  else o.plus_tard = action === 'plus_tard';
  dessinerBarre();
  etat.glisseur?.detruire();
  etat.glisseur = null;
  const pile = $('#pile');
  pile.querySelector('.carte.pos0')?.remove();
  const p1 = pile.querySelector('.carte.pos1'), p2 = pile.querySelector('.carte.pos2');
  if (p1) { p1.classList.replace('pos1', 'pos0'); p1.style.transform = ''; p1.style.transition = ''; p1.style.removeProperty('--revele'); }
  if (p2) p2.classList.replace('pos2', 'pos1');
  const troisieme = visibles()[2];
  if (troisieme) {
    const c = nouvelleCarte(troisieme, 2);
    c.classList.add('nouvelle');
    pile.prepend(c);
    requestAnimationFrame(() => requestAnimationFrame(() => c.classList.remove('nouvelle')));
  }
  for (const f of ['#fleche-non', '#fleche-oui']) { $(f).style.setProperty('--force', 0); $(f).classList.remove('actif'); }
  activerDessus();
  majCompte();
}

function remettre(o, action) {
  if ((action === 'candidate' || action === 'ecarte') && !etat.toutes.some(x => x.id === o.id)) etat.toutes.push(o);
  if (action === 'plus_tard') o.plus_tard = false;
  if (action === 'remettre') o.plus_tard = true;
}

async function annulerDerniere() {
  const derniere = etat.historique.pop();
  if (!derniere || etat.occupe) return;
  cacherToast();
  try {
    await api('/api/annuler', derniere.decision);
  } catch (e) {
    console.error(e);
    etat.historique.push(derniere);
    toast("Impossible d'annuler pour l'instant.");
    return;
  }
  remettre(derniere.offre, derniere.decision.action);
  // On revient sur la section où était la carte, et elle repasse sur le dessus du paquet.
  if (derniere.decision.action === 'remettre') etat.section = 'plus_tard';
  else if (etat.section === 'plus_tard') etat.section = 'toutes';
  const liste = visibles();
  rafraichir();
  if (liste[0]?.id !== derniere.offre.id) {      // filtrée ou triée plus loin : on la met devant pour la revoir
    const pile = $('#pile');
    pile.querySelectorAll('.carte').forEach(c => c.remove());
    const autres = liste.filter(x => x.id !== derniere.offre.id).slice(0, 2);
    [derniere.offre, ...autres].slice(0, 3).reverse().forEach((o, i, t) => pile.append(nouvelleCarte(o, t.length - 1 - i)));
    pile.querySelector('.vide')?.remove();
    activerDessus();
  }
  etat.glisseur?.entrer(derniere.dir);
  toast(`« ${derniere.offre.titre} » est revenue.`);
}

// ======================================================================= toast

function toastDecision(decision, o) {
  const boutons = [h('button', { type: 'button', onclick: annulerDerniere }, 'Annuler')];
  const nom = o.entreprise ? `${o.entreprise} : ` : '';
  if (decision.action !== 'ecarte') {
    toast(`${nom}${TEXTE_ACTION[decision.action]}`, boutons);
    return;
  }
  const choix = h('div', { class: 'raisons', role: 'group', 'aria-label': 'Pourquoi ? (facultatif)' },
    RAISONS.map(r => h('button', {
      type: 'button', 'aria-pressed': 'false',
      onclick: async (e) => {
        const b = e.currentTarget, deja = b.getAttribute('aria-pressed') === 'true';
        choix.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', 'false'));
        b.setAttribute('aria-pressed', String(!deja));
        await api('/api/raison', { offre_id: decision.offre_id, raison: deja ? null : r }).catch(console.error);
        if (!deja) setTimeout(cacherToast, 600);
      },
    }, r)));
  const pourquoi = h('button', {
    type: 'button', onclick: () => toast(`${nom}écartée. Pourquoi ? (facultatif, l'IA s'en servira)`, boutons,
      { raisons: choix, duree: 12000 }),
  }, 'Pourquoi ?');
  toast(`${nom}écartée`, [pourquoi, ...boutons]);
}

// ======================================================================= détails : la carte grossit

// La carte du dessus et la grande vue portent tour à tour le même nom de transition : le navigateur anime le
// passage de l'une à l'autre (position, taille, coins), comme si la carte grossissait. Sans View Transitions
// (ou avec « réduire les animations »), la grande vue apparaît simplement.
const ANIMER = () => document.startViewTransition && !matchMedia('(prefers-reduced-motion: reduce)').matches;
let ouverteSur = null;

function transition(changer) {
  if (!ANIMER()) { changer(); return Promise.resolve(); }
  return document.startViewTransition(changer).finished.catch(() => {});
}

function carteDe(id) { return $(`#pile .carte[data-id="${id}"]`); }

async function ouvrirFiche(id) {
  if (ouverteSur !== null) return;
  ouverteSur = id;
  let o;
  try { o = await api(`/api/offres/${id}`); } catch (e) {
    ouverteSur = null;
    toast("Impossible de charger l'offre.");
    return;
  }
  const estDessus = Number(carteDessus()?.dataset.id) === id;
  const choix = (dir) => () => fermerFiche(false).then(() => decider(dir));
  $('#grande-corps').replaceChildren(...detailOffre(o));
  $('#grande-pied').replaceChildren(...(estDessus ? [
    h('button', { class: 'bouton discret non', type: 'button', onclick: choix('gauche') }, 'Pas intéressé'),
    h('button', { class: 'bouton discret', type: 'button', onclick: choix('haut') },
      etat.section === 'plus_tard' ? 'Remettre à trier' : 'Plus tard'),
    h('button', { class: 'bouton oui', type: 'button', onclick: choix('droite') }, 'Intéressé'),
  ] : []));
  $('#grande-corps').scrollTop = 0;
  const carte = carteDe(id);
  if (carte) carte.style.viewTransitionName = 'agrandie';
  await transition(() => {
    if (carte) carte.style.viewTransitionName = '';
    const g = $('#grande');
    g.style.viewTransitionName = 'agrandie';
    g.hidden = false;
    $('#voile').hidden = false;
    document.body.classList.add('detail-ouvert');
  });
  $('#grande').focus({ preventScroll: true });
}

// animer = false : on ferme pour décider ; la carte repart tout de suite dans le paquet, sans rétrécir.
function fermerFiche(animer = true) {
  const g = $('#grande');
  if (g.hidden) return false;
  const id = ouverteSur;
  ouverteSur = null;
  const carte = carteDe(id);
  const fermer = () => {
    g.hidden = true;
    g.style.viewTransitionName = '';
    $('#voile').hidden = true;
    document.body.classList.remove('detail-ouvert');
    if (carte && animer) carte.style.viewTransitionName = 'agrandie';
  };
  if (!animer) { fermer(); return Promise.resolve(); }
  return transition(fermer).then(() => {
    if (carte) { carte.style.viewTransitionName = ''; carte.querySelector('.pied button')?.focus({ preventScroll: true }); }
  });
}

// ======================================================================= scrap

async function apresScrap(s) {
  const avant = new Set(etat.toutes.map(o => o.id));
  const ancienDessus = carteDessus()?.dataset.id;
  const d = await api('/api/a-trier');
  etat.toutes = d.offres;
  afficherScrap(d.scrap);
  const nouvelles = d.offres.filter(o => !avant.has(o.id)).length;
  if (!carteDessus() || visibles()[0]?.id !== Number(ancienDessus)) rafraichir(); else { dessinerBarre(); majCompte(); }
  toast(s.erreur ? `Le scrap a planté : ${s.erreur}`
    : nouvelles ? `Scrap terminé : ${nouvelles} nouvelle${nouvelles > 1 ? 's' : ''} offre${nouvelles > 1 ? 's' : ''} à trier.`
      : 'Scrap terminé : pas de nouvelle offre.');
}

// ======================================================================= branchements

function brancher() {
  $('#bouton-oui').addEventListener('click', () => decider('droite'));
  $('#bouton-non').addEventListener('click', () => decider('gauche'));
  $('#bouton-tard').addEventListener('click', () => decider('haut'));
  $('#fleche-oui').addEventListener('click', () => decider('droite'));
  $('#fleche-non').addEventListener('click', () => decider('gauche'));
  $('#grande-fermer').addEventListener('click', () => fermerFiche());
  $('#voile').addEventListener('click', () => fermerFiche());
  brancherScrap(apresScrap);
  $('#filtres').addEventListener('click', () => (menuOuvert() ? fermerMenu() : ouvrirMenu()));
  $('#filtres').addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' && !menuOuvert()) { e.preventDefault(); ouvrirMenu(); }
  });
  $('#menu-filtres').addEventListener('keydown', clavierMenu);
  document.addEventListener('pointerdown', (e) => {
    if (menuOuvert() && !e.target.closest('.filtres')) fermerMenu({ rendreFocus: false });
  });
  let attente = 0;
  $('#recherche').addEventListener('input', (e) => {
    clearTimeout(attente);
    attente = setTimeout(() => { etat.recherche = e.target.value; rafraichir({ distribuer: true }); }, 220);
  });

  document.addEventListener('keydown', (e) => {
    if (menuOuvert()) return;                            // le menu des filtres gère ses touches
    if (e.key === 'Escape' && !$('#grande').hidden) { e.preventDefault(); fermerFiche(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); annulerDerniere(); return; }
    if (e.target.closest('input, textarea') || e.altKey || e.ctrlKey || e.metaKey) return;
    if (!$('#grande').hidden) return;
    const dir = { ArrowRight: 'droite', ArrowLeft: 'gauche', ArrowUp: 'haut' }[e.key];
    if (dir) { e.preventDefault(); decider(dir); }
    else if (e.key === 'Enter' && carteDessus() && !e.target.closest('button, a')) {
      e.preventDefault(); ouvrirFiche(Number(carteDessus().dataset.id));
    }
  });
}

brancher();
charger().catch((e) => { console.error(e); toast('Impossible de charger les offres : le serveur tourne-t-il ?'); });
