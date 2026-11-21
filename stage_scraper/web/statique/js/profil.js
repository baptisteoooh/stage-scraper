// Mon profil : une fiche qui se lit en trois secondes. La phrase « ce que tu cherches », puis UNE ligne par rubrique
// (titre, résumé, « Modifier ») ; le détail n'apparaît qu'en ouvrant la rubrique (une à la fois). Les réglages
// techniques (recherches, filtres fins) sont repliés. « Enregistrer » écrit config.yaml, le message en bas propose
// « Annuler ». À droite, une conversation avec Gemini modifie le profil : seul le dernier échange est affiché.
import { $, h, api, toast, brancherScrap, majMenu, LOCALE, LANGUE } from './commun.js';

const etat = {
  d: null, p: null, alertes: [], messages: [], enCours: false, triEnAttente: false, annules: new Set(),
  ouverte: null, brouillon: null,   // rubrique en cours de modification et ses valeurs pas encore enregistrées
  techniques: false, toutFil: false,   // réglages techniques dépliés ; tout l'historique de la conversation affiché
  aRevoir: [],   // propositions tirées des offres écartées : [{cle, constat, question, valeurs}]
};
const GROUPES_TITRES = [
  ['priorite_absolue', 'Priorité absolue'], ['scale_up', 'Scale-ups'], ['grand_groupe', 'Grands groupes'], ['ecosysteme', 'Écosystèmes'],
];
const OUTILS = { '': 'Aucun', ashby: 'Ashby', workday: 'Workday' };
const reduit = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

// ======================================================================= mise en forme des valeurs

const dateLongue = (iso, annee = true) => {
  const texte = new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'long', ...(annee ? { year: 'numeric' } : {}) })
    .format(new Date(`${iso}T12:00:00`));
  return LANGUE === 'fr' ? texte.replace(/^1 /, '1er ') : texte;
};
const rang = (n) => (LANGUE === 'en' ? `${n}${[, 'st', 'nd', 'rd'][n % 100 > 10 && n % 100 < 14 ? 0 : n % 10] || 'th'}` : `${n}${n === 1 ? 're' : 'e'}`);
const virgule = (n) => (LANGUE === 'en' ? String(n) : String(n).replace('.', ','));
const mois = (n) => (LANGUE === 'en' ? `${n} month${n > 1 ? 's' : ''}` : `${virgule(n)} mois`);

// Les résumés, entiers dans chaque langue (les libellés fixes passent par en.json).
const P = LANGUE === 'en' ? {
  duree: (a, b) => (a === b ? mois(a) : `${a}–${mois(b)}`),
  contrats: { 'stage,cdd': 'Internship or fixed-term', stage: 'Internship only', cdd: 'Fixed-term only' },
  six: { a_negocier: 'Negotiable at your followed companies', exclure: 'Always excluded' },
  toute: 'All of Île-de-France',
  teletravail: (hy, re) => (hy && re ? 'hybrid or remote' : hy ? 'hybrid' : re ? 'remote' : 'on site'),
  moins: (s) => `less: ${s}`, aucunSecteur: 'No target sector',
  entreprises: (n, prio) => `${n} followed` + (prio ? ` · ${prio} first` : ''),
  recherches: (n) => `${n} search${n > 1 ? 'es' : ''} sent to the job sites`,
  fins: (n, j) => `${n} exclusions · offers under ${j} days old`,
  vide: 'Describe in one sentence the internship you want: the AI uses it to score offers.',
  anciens: (n) => (n > 1 ? `See the ${n} previous messages` : 'See the previous message'),
  jours: (n) => `${n} days`, rien: 'None', oui: 'yes', non: 'no',
  raccourcis: { idf: 'Search all of Île-de-France', hybride: 'Accept hybrid too', six: 'Accept 6-month internships too',
    domaine: 'Add a field', entreprise: 'Follow another company', tard: 'I want to start later' },
} : {
  duree: (a, b) => (a === b ? mois(a) : `${virgule(a)} à ${mois(b)}`),
  contrats: { 'stage,cdd': 'Stage ou CDD', stage: 'Stage seulement', cdd: 'CDD seulement' },
  six: { a_negocier: 'À négocier chez tes entreprises suivies', exclure: 'Toujours exclues' },
  toute: 'Toute l\'Île-de-France',
  teletravail: (hy, re) => (hy && re ? 'hybride ou à distance' : hy ? 'hybride' : re ? 'à distance' : 'sur place'),
  moins: (s) => `moins : ${s}`, aucunSecteur: 'Aucun secteur visé',
  entreprises: (n, prio) => `${n} suivie${n > 1 ? 's' : ''}` + (prio ? ` · ${prio} en priorité` : ''),
  recherches: (n) => `${n} recherche${n > 1 ? 's' : ''} envoyée${n > 1 ? 's' : ''} aux sites d'offres`,
  fins: (n, j) => `${n} exclusions · offres de moins de ${j} jours`,
  vide: 'Décris en une phrase le stage que tu cherches : l\'IA s\'en sert pour noter les offres.',
  anciens: (n) => (n > 1 ? `Voir les ${n} messages précédents` : 'Voir le message précédent'),
  jours: (n) => `${n} jours`, rien: 'Aucun', oui: 'oui', non: 'non',
  raccourcis: { idf: 'Cherche dans toute l\'Île-de-France', hybride: 'Accepte aussi l\'hybride', six: 'Accepte aussi les stages de 6 mois',
    domaine: 'Ajoute un domaine', entreprise: 'Suis une autre entreprise', tard: 'Je veux commencer plus tard' },
};

function valeurTexte(champ, v) {
  const type = etat.d.champs[champ].type;
  if (type === 'date') return dateLongue(v);
  if (type === 'nombre') return champ === 'anciennete_max_jours' ? P.jours(v) : mois(v);
  if (type === 'booleen') return v ? P.oui : P.non;
  if (type === 'choix') return P.six[v];
  if (type === 'texte') return v ? `« ${v} »` : '—';
  return String(v);
}

// « a · b · c +6 » : les premiers éléments, puis le nombre de ceux qu'on ne montre pas (ils sont dans « Modifier »).
const premiers = (l, max, { fort = false } = {}) => [
  ...l.slice(0, max).flatMap((x, i) => [i ? ' · ' : '', fort && !i ? h('b', {}, x) : x]),
  l.length > max ? h('span', { class: 'en-plus', title: l.slice(max).join(', ') }, `+${l.length - max}`) : '',
];

const RUBRIQUES = [
  { id: 'qui', titre: 'Ce que tu cherches', champs: ['recherche', 'ecole', 'annee', 'majeure', 'competences'], resume: resumeQui, edition: editerQui },
  { id: 'quand', titre: 'Quand', champs: ['contrats', 'debut_au_plus_tot', 'debut_ideal', 'debut_au_plus_tard', 'fin_au_plus_tard', 'duree_min', 'duree_max', 'six_mois'], resume: resumeQuand, edition: editerQuand },
  { id: 'ou', titre: 'Où', champs: ['departements', 'hybride', 'full_remote'], resume: resumeOu, edition: editerOu },
  { id: 'domaines', titre: 'Domaines', champs: ['domaines'], resume: (p) => premiers(p.domaines, 3, { fort: true }), edition: editerDomaines },
  { id: 'secteurs', titre: 'Secteurs', champs: ['secteurs_cible', 'secteurs_ok', 'secteurs_moins', 'autres_secteurs_domaines', 'tailles'], aussi: ['domaines'], resume: resumeSecteurs, edition: editerSecteurs },
  { id: 'entreprises', titre: 'Entreprises', champs: ['entreprises'], resume: resumeEntreprises, edition: editerEntreprises },
  { id: 'recherches', titre: 'Recherches', champs: ['requetes'], technique: true, resume: (p) => P.recherches(p.requetes.length), edition: editerRecherches },
  { id: 'fins', titre: 'Filtres fins', champs: ['postes_exclus', 'contrats_exclus', 'niveaux_exclus', 'anciennete_max_jours'], technique: true, resume: resumeFins, edition: editerFins },
];
const rubrique = (id) => RUBRIQUES.find(r => r.id === id);

function resumeQui(p) {
  return h('p', { class: `phrase-recherche${p.recherche ? '' : ' vide'}`, translate: p.recherche ? 'no' : null }, p.recherche || P.vide);
}

function resumeQuand(p) {
  const debut = dateLongue(p.debut_ideal, p.debut_ideal.slice(0, 4) !== p.fin_au_plus_tard.slice(0, 4));
  return `${P.contrats[p.contrats.join(',')]} · ${debut} → ${dateLongue(p.fin_au_plus_tard)} · ${P.duree(p.duree_min, p.duree_max)}`;
}

function resumeOu(p) {
  const tous = Object.keys(etat.d.departements).every(c => p.departements.includes(c));
  return [...(tous ? [P.toute] : premiers(p.departements.map(c => etat.d.departements[c]), 2)), ' · ', P.teletravail(p.hybride, p.full_remote)];
}

function resumeSecteurs(p) {
  if (!p.secteurs_cible.length) return P.aucunSecteur;
  return [...premiers(p.secteurs_cible, 2), p.secteurs_moins.length ? ` · ${P.moins(p.secteurs_moins[0])}` : ''];
}

function resumeEntreprises(p) {
  const prio = p.entreprises.filter(e => e.groupe === 'priorite_absolue').map(e => e.nom);
  return P.entreprises(p.entreprises.length, prio.slice(0, 2).join(', '));
}

function resumeFins(p) {
  return P.fins(p.postes_exclus.length + p.contrats_exclus.length + p.niveaux_exclus.length, p.anciennete_max_jours);
}

// Suggestions en un clic sous la conversation : d'abord ce qui élargirait un profil restreint, puis des demandes courantes.
function raccourcis(p) {
  const R = P.raccourcis;
  const l = [];
  if (!Object.keys(etat.d.departements).every(c => p.departements.includes(c))) l.push(R.idf);
  if (!p.hybride) l.push(R.hybride);
  if (p.duree_max < 6) l.push(R.six);
  return [...l, R.domaine, R.entreprise, R.tard].slice(0, 3);
}

// ======================================================================= dessin

async function charger() {
  const d = await api('/api/profil');
  majMenu(d.menu);
  Object.assign(etat, { d, p: d.profil, alertes: d.alertes, messages: d.messages, aRevoir: d.a_revoir || [] });
  const section = (r) => h('section', { class: 'rubrique', id: `r-${r.id}`, 'aria-labelledby': `t-${r.id}` });
  $('#feuille').replaceChildren(h('div', { id: 'bandeaux' }), h('div', { id: 'a-revoir' }), ...RUBRIQUES.filter(r => !r.technique).map(section),
    h('button', { class: 'techniques', id: 'techniques', type: 'button', 'aria-expanded': 'false', onclick: () => montrerTechniques(!etat.techniques) },
      icone(BAS), h('span', {})),
    ...RUBRIQUES.filter(r => r.technique).map(section));
  RUBRIQUES.forEach(r => dessinerRubrique(r));
  montrerTechniques(etat.techniques);
  dessinerARevoir();
  dessinerBandeaux();
  dessinerFil();
}

function dessinerRubrique(r) {
  const el = $(`#r-${r.id}`);
  const ouverte = etat.ouverte === r.id;
  el.classList.toggle('ouverte', ouverte);
  el.classList.toggle('en-retrait', !!etat.ouverte && !ouverte);
  el.inert = !!etat.ouverte && !ouverte;   // une seule rubrique à la fois : les autres attendent
  el.hidden = !!r.technique && !etat.techniques && !ouverte;
  if (ouverte) {
    el.replaceChildren(h('header', { class: 'rubrique-tete' }, h('h2', { id: `t-${r.id}` }, r.titre)), formulaire(r));
    return;
  }
  // Une ligne : titre, résumé, « Modifier ». Un clic n'importe où sur la ligne l'ouvre aussi (le bouton reste pour le clavier).
  const resume = r.resume(etat.p);
  el.replaceChildren(h('header', { class: 'rubrique-tete ligne-lue', onclick: (e) => { if (!e.target.closest('button')) ouvrir(r.id); } },
    h('h2', { id: `t-${r.id}`, class: r.id === 'qui' ? 'sr-only' : null }, r.titre),
    resume instanceof Node ? resume : h('p', { class: 'resume', translate: 'no' }, resume),
    h('button', { type: 'button', class: 'modifier', 'data-rubrique': r.id, 'aria-describedby': `t-${r.id}`, onclick: () => ouvrir(r.id) }, 'Modifier')));
}

function montrerTechniques(oui) {
  etat.techniques = oui;
  const b = $('#techniques');
  b.setAttribute('aria-expanded', String(oui));
  b.querySelector('span').textContent = oui ? 'Masquer les réglages techniques' : 'Réglages techniques';
  RUBRIQUES.filter(r => r.technique).forEach(r => dessinerRubrique(r));
}

function dessinerBandeaux() {
  const zone = $('#bandeaux');
  if (!zone) return;
  zone.replaceChildren(
    ...etat.alertes.map(a => h('div', { class: 'bandeau alerte', role: 'status' }, h('p', {}, a))),
    ...(etat.triEnAttente ? [h('div', { class: 'bandeau tri' },
      h('p', {}, 'Tes critères ont changé. Les offres déjà collectées n\'ont pas encore été retriées.'),
      h('button', { class: 'pastille', type: 'button', onclick: refaireTri }, 'Refaire le tri'))] : []));
}

// « À revoir » : ce que tes offres écartées suggèrent de changer. Un clic sur Oui applique (annulable), Non ne revient plus.
function dessinerARevoir() {
  const zone = $('#a-revoir');
  if (!zone) return;
  if (!etat.aRevoir.length) { zone.replaceChildren(); return; }
  zone.replaceChildren(h('section', { class: 'a-revoir', 'aria-labelledby': 't-a-revoir' },
    h('h2', { id: 't-a-revoir' }, 'À revoir', h('span', { class: 'nb-revoir' }, String(etat.aRevoir.length))),
    etat.aRevoir.map(prop => h('div', { class: 'proposition', 'data-cle': prop.cle },
      h('div', { class: 'texte-prop', translate: 'no' }, h('p', { class: 'constat' }, prop.constat), h('p', { class: 'question' }, prop.question)),
      h('div', { class: 'choix-prop' },
        h('button', { class: 'pastille oui', type: 'button', onclick: (e) => repondre(prop, true, e.currentTarget) }, 'Oui'),
        h('button', { class: 'non', type: 'button', onclick: (e) => repondre(prop, false, e.currentTarget) }, 'Non'))))));
}

async function repondre(prop, oui, bouton) {
  const ligne = bouton.closest('.proposition');
  ligne.querySelectorAll('button').forEach(b => { b.disabled = true; });
  try {
    const r = oui ? await api('/api/profil', { valeurs: prop.valeurs }) : await api('/api/profil/a-revoir/ignorer', { cle: prop.cle });
    await replier(ligne);
    if (oui) {
      appliquer(r, { flash: true });
      toast('Modifications enregistrées.', [h('button', { type: 'button', onclick: () => annuler(r.changements) }, 'Annuler')]);
    } else {
      etat.aRevoir = r.a_revoir;
      dessinerARevoir();
      toast('D\'accord, je ne te le proposerai plus.');
    }
  } catch (e) {
    ligne.querySelectorAll('button').forEach(b => { b.disabled = false; });
    toast(`Pas enregistré : ${e.message}`);
  }
}

// La proposition traitée se replie en douceur avant de disparaître.
function replier(el) {
  if (reduit()) return Promise.resolve();
  const haut = el.offsetHeight;
  return el.animate([{ opacity: 1, height: `${haut}px` }, { opacity: 0, height: '0px', paddingTop: '0px', paddingBottom: '0px' }],
    { duration: 280, easing: 'cubic-bezier(.2, .8, .2, 1)', fill: 'forwards' }).finished;
}

async function refaireTri(e) {
  const b = e.currentTarget;
  b.disabled = true; b.textContent = 'Tri en cours…';
  try {
    const r = await api('/api/reglages/retrier', {});
    etat.triEnAttente = false;
    dessinerBandeaux();
    toast(r.texte, [], { duree: 8000 });
    api('/api/profil').then(d => majMenu(d.menu)).catch(() => {});
  } catch (err) { toast(err.message); b.disabled = false; b.textContent = 'Refaire le tri'; }
}

// Après un enregistrement, une annulation ou un message de l'agent : redessine les rubriques touchées.
function appliquer(r, { flash = false } = {}) {
  etat.p = r.profil;
  etat.alertes = r.alertes;
  if (r.a_revoir) { etat.aRevoir = r.a_revoir; dessinerARevoir(); }
  const champs = r.changements.map(c => c.champ);
  if (champs.some(c => etat.d.champs_tri.includes(c))) etat.triEnAttente = true;
  const touchees = RUBRIQUES.filter(x => champs.some(c => x.champs.includes(c) || x.aussi?.includes(c)));
  if (touchees.some(x => x.id === etat.ouverte)) fermer();   // l'agent a changé la rubrique ouverte : on la relit
  if (flash && touchees.some(x => x.technique && x.champs.some(c => champs.includes(c)))) montrerTechniques(true);
  touchees.forEach(x => dessinerRubrique(x));
  dessinerBandeaux();
  dessinerFil({ defiler: false });   // les suggestions en un clic dépendent du profil
  if (flash) {
    const vraies = RUBRIQUES.filter(x => champs.some(c => x.champs.includes(c)));
    vraies.forEach((x) => { const el = $(`#r-${x.id}`); el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash'); });
    vraies[0] && $(`#r-${vraies[0].id}`).scrollIntoView({ block: 'nearest', behavior: reduit() ? 'auto' : 'smooth' });
  }
}

async function annuler(changements, { depuisChat = null } = {}) {
  try {
    const r = await api('/api/profil', { valeurs: Object.fromEntries(changements.map(c => [c.champ, c.avant])) });
    if (depuisChat !== null) etat.annules.add(depuisChat);
    appliquer(r, { flash: true });
    toast(changements.length > 1 ? 'Changements annulés.' : 'Changement annulé.');
  } catch (e) { toast(`Impossible d'annuler : ${e.message}`); }
}

// ======================================================================= ouvrir, enregistrer, fermer

function ouvrir(id) {
  if (etat.ouverte) return;
  const r = rubrique(id);
  etat.ouverte = id;
  etat.brouillon = structuredClone(Object.fromEntries(r.champs.map(c => [c, etat.p[c]])));
  RUBRIQUES.forEach(x => dessinerRubrique(x));
  const el = $(`#r-${id}`);
  el.scrollIntoView({ block: 'start', behavior: reduit() ? 'auto' : 'smooth' });
  el.querySelector('input, textarea, select, button:not(.retour)')?.focus({ preventScroll: true });
}

function fermer({ rendreFocus = false } = {}) {
  const id = etat.ouverte;
  if (!id) return;
  etat.ouverte = null;
  etat.brouillon = null;
  RUBRIQUES.forEach(x => dessinerRubrique(x));
  if (rendreFocus) document.querySelector(`[data-rubrique="${id}"]`)?.focus();
}

const modifies = () => Object.keys(etat.brouillon).filter(c => JSON.stringify(etat.brouillon[c]) !== JSON.stringify(etat.p[c]));

function majPied() {
  const b = $('#enregistrer-rubrique');
  if (b) b.disabled = !modifies().length;
}

// Les contrôles changent le brouillon, puis appellent changer() : le bouton « Enregistrer » s'allume.
function changer(champ, valeur) {
  etat.brouillon[champ] = valeur;
  $('#erreur-rubrique')?.replaceChildren();
  majPied();
}

async function enregistrerRubrique(e) {
  e?.preventDefault();
  const champs = modifies();
  if (!champs.length) { fermer({ rendreFocus: true }); return; }
  const bouton = $('#enregistrer-rubrique');
  bouton.disabled = true;
  bouton.textContent = 'Enregistrement…';
  let rep;
  try {
    rep = await api('/api/profil', { valeurs: Object.fromEntries(champs.map(c => [c, etat.brouillon[c]])) });
  } catch (err) {
    bouton.textContent = 'Enregistrer';
    bouton.disabled = false;
    bouton.focus();
    const m = err.message.replace(/^Pas enregistré : /, '');
    $('#erreur-rubrique').replaceChildren(m.charAt(0).toUpperCase() + m.slice(1));
    return;
  }
  const id = etat.ouverte;
  appliquer(rep);   // referme la rubrique et la redessine
  fermer();
  document.querySelector(`[data-rubrique="${id}"]`)?.focus();
  if (rep.changements.length) {
    toast('Modifications enregistrées.', [h('button', { type: 'button', onclick: () => annuler(rep.changements) }, 'Annuler')]);
  }
}

function formulaire(r) {
  return h('form', {
    class: 'edition', novalidate: true, onsubmit: enregistrerRubrique,
    onkeydown: (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); fermer({ rendreFocus: true }); } },
  }, r.edition(etat.brouillon),
  h('div', { class: 'pied' },
    h('p', { class: 'erreur', id: 'erreur-rubrique', role: 'alert' }),
    h('button', { class: 'pastille retour', type: 'button', onclick: () => fermer({ rendreFocus: true }) }, 'Annuler'),
    h('button', { class: 'bouton principal', id: 'enregistrer-rubrique', type: 'submit', disabled: true }, 'Enregistrer')));
}

// ======================================================================= contrôles

const champ = (libelle, controle, aide) => h('label', { class: 'champ-ligne' }, h('span', { class: 'libelle' }, libelle), controle,
  aide ? h('span', { class: 'aide' }, aide) : null);

function texte(cle, { long = false, placeholder = '' } = {}) {
  const el = h(long ? 'textarea' : 'input', {
    class: 'champ', type: long ? null : 'text', maxlength: '400', placeholder, translate: 'no', rows: long ? '2' : null,
    oninput: (e) => changer(cle, e.target.value),
    onkeydown: long ? (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.target.form.requestSubmit(); } } : null,
  });
  el.value = etat.brouillon[cle];
  return el;
}

function dateChamp(cle) {
  return h('input', { class: 'champ', type: 'date', value: etat.brouillon[cle], required: true, oninput: (e) => changer(cle, e.target.value) });
}

function nombre(cle, { min = 1, max = 12, pas = 0.5 } = {}) {
  return h('input', {
    class: 'champ nombre', type: 'number', min: String(min), max: String(max), step: String(pas), value: String(etat.brouillon[cle]),
    oninput: (e) => changer(cle, e.target.value === '' ? '' : Number(e.target.value)),
  });
}

// Pastilles à cocher (plusieurs choix) ou à choisir (un seul, `unique`).
function pastilles(cle, options, { unique = false, etiquette } = {}) {
  const zone = h('div', { class: 'choix', role: unique ? 'radiogroup' : 'group', 'aria-label': etiquette });
  const dessiner = () => zone.replaceChildren(...Object.entries(options).map(([valeur, libelle]) => {
    const pris = unique ? etat.brouillon[cle] === valeur : etat.brouillon[cle].includes(valeur);
    return h('button', {
      type: 'button', class: 'pastille', role: unique ? 'radio' : null, 'aria-checked': unique ? String(pris) : null,
      'aria-pressed': String(pris),
      onclick: () => {
        if (unique) changer(cle, valeur);
        else changer(cle, pris ? etat.brouillon[cle].filter(x => x !== valeur) : [...etat.brouillon[cle], valeur]);
        dessiner();
        zone.querySelectorAll('button')[Object.keys(options).indexOf(valeur)]?.focus();
      },
    }, libelle);
  }));
  dessiner();
  return zone;
}

function interrupteur(cle, libelle) {
  const b = h('button', {
    type: 'button', class: 'interrupteur', role: 'switch', 'aria-checked': String(etat.brouillon[cle]),
    onclick: () => { changer(cle, !etat.brouillon[cle]); b.setAttribute('aria-checked', String(etat.brouillon[cle])); },
  }, h('i'));
  return h('div', { class: 'bascule' }, b, h('span', { onclick: () => b.click() }, libelle));
}

// Liste de mots : une pastille par mot, × pour retirer, Entrée pour ajouter.
function mots(cle, placeholder) {
  const zone = h('div', { class: 'mots' });
  const ajout = h('input', { class: 'champ ajout', type: 'text', placeholder, 'aria-label': placeholder, maxlength: '80' });
  ajout.addEventListener('keydown', (e) => {
    const l = etat.brouillon[cle];
    if (e.key === 'Backspace' && !ajout.value && l.length) { changer(cle, l.slice(0, -1)); dessiner(); return; }
    if (e.key !== 'Enter' && e.key !== ',') return;
    e.preventDefault();
    const v = ajout.value.trim();
    if (v && !l.some(x => x.toLowerCase() === v.toLowerCase())) { changer(cle, [...l, v]); dessiner(); }
    ajout.value = '';
  });
  const dessiner = () => {
    zone.replaceChildren(...etat.brouillon[cle].map((m, i) => h('span', { class: 'mot', translate: 'no' }, m, h('button', {
      type: 'button', 'aria-label': `Retirer ${m}`,
      onclick: () => { changer(cle, etat.brouillon[cle].filter((_, j) => j !== i)); dessiner(); ajout.focus(); },
    }, '×'))), ajout);
  };
  dessiner();
  return zone;
}

function icone(d) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', 'ic'); s.setAttribute('aria-hidden', 'true');
  s.innerHTML = `<path d="${d}"/>`;   // tracé fixe, écrit ici (jamais de donnée)
  return s;
}
const HAUT = 'M6 15l6-6 6 6';
const BAS = 'M6 9l6 6 6-6';
const CROIX = 'M6 6l12 12M18 6L6 18';
const PLUS = 'M5 12h14M12 5v14';

// ======================================================================= formulaires des rubriques

function editerQui() {
  return [
    champ('Ce que tu cherches, en une phrase', texte('recherche', { long: true, placeholder: 'Ex. : un stage en IA appliquée à l\'imagerie médicale' }),
      'L\'IA s\'en sert pour noter chaque offre.'),
    h('div', { class: 'grille-3' }, champ('École', texte('ecole')), champ('Année', texte('annee')), champ('Majeure', texte('majeure'))),
    h('div', { class: 'champ-ligne' }, h('span', { class: 'libelle' }, 'Compétences'), mots('competences', 'Ajouter une compétence')),
  ];
}

function editerQuand() {
  return [
    h('div', { class: 'champ-ligne' }, h('span', { class: 'libelle' }, 'Contrats acceptés'),
      pastilles('contrats', etat.d.contrats, { etiquette: 'Contrats acceptés' })),
    h('div', { class: 'grille-2' },
      champ('Début au plus tôt', dateChamp('debut_au_plus_tot')), champ('Début au plus tard', dateChamp('debut_au_plus_tard')),
      champ('Début idéal', dateChamp('debut_ideal')), champ('Fin au plus tard', dateChamp('fin_au_plus_tard'))),
    h('div', { class: 'grille-2' },
      champ('Durée minimale (mois)', nombre('duree_min')), champ('Durée maximale (mois)', nombre('duree_max'))),
    h('div', { class: 'champ-ligne' }, h('span', { class: 'libelle' }, 'Offres de 6 mois fixes'),
      pastilles('six_mois', P.six, { unique: true, etiquette: 'Offres de 6 mois fixes' })),
  ];
}

function editerOu() {
  return [
    h('div', { class: 'champ-ligne' }, h('span', { class: 'libelle' }, 'Départements'),
      pastilles('departements', etat.d.departements, { etiquette: 'Départements' }),
      h('span', { class: 'aide' }, 'L\'outil ne couvre pour l\'instant que l\'Île-de-France.')),
    interrupteur('hybride', 'Hybride accepté'),
    interrupteur('full_remote', 'Télétravail complet accepté'),
  ];
}

function editerDomaines() {
  const zone = h('ol', { class: 'domaines-edit' });
  const ajout = h('input', { class: 'champ', type: 'text', placeholder: 'Ajouter un domaine, puis Entrée', 'aria-label': 'Ajouter un domaine', maxlength: '80' });
  const dessiner = (focus) => {
    const l = etat.brouillon.domaines;
    zone.replaceChildren(...l.map((nom, i) => h('li', {},
      h('span', { class: 'rang' }, String(i + 1)), h('span', { class: 'nom', translate: 'no' }, nom),
      h('span', { class: 'outils-ligne' },
        h('button', { type: 'button', 'aria-label': `Monter ${nom}`, disabled: i === 0, 'data-cle': `h-${nom}`, onclick: () => deplacer(i, -1, `h-${nom}`) }, icone(HAUT)),
        h('button', { type: 'button', 'aria-label': `Descendre ${nom}`, disabled: i === l.length - 1, 'data-cle': `b-${nom}`, onclick: () => deplacer(i, 1, `b-${nom}`) }, icone(BAS)),
        h('button', { type: 'button', class: 'retirer', 'aria-label': `Retirer ${nom}`, onclick: () => { changer('domaines', l.filter(x => x !== nom)); dessiner(); ajout.focus(); } }, icone(CROIX))))));
    if (focus) zone.querySelector(`[data-cle="${CSS.escape(focus)}"]:not([disabled])`)?.focus();
  };
  const deplacer = (i, d, focus) => {
    const l = [...etat.brouillon.domaines];
    [l[i], l[i + d]] = [l[i + d], l[i]];
    changer('domaines', l);
    dessiner(focus);
  };
  ajout.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const v = ajout.value.trim();
    if (v && !etat.brouillon.domaines.some(x => x.toLowerCase() === v.toLowerCase())) { changer('domaines', [...etat.brouillon.domaines, v]); dessiner(); }
    ajout.value = '';
  });
  dessiner();
  return [zone, ajout, h('p', { class: 'aide' }, 'Le premier domaine compte le plus dans la note de l\'IA.')];
}

function editerSecteurs() {
  const domaines = Object.fromEntries(etat.p.domaines.map(d => [d, d]));
  return [
    h('div', { class: 'champ-ligne' }, h('span', { class: 'libelle' }, 'Visés'), mots('secteurs_cible', 'Ajouter un secteur')),
    h('div', { class: 'champ-ligne' }, h('span', { class: 'libelle' }, 'Bien aussi'), mots('secteurs_ok', 'Ajouter un secteur')),
    h('div', { class: 'champ-ligne' }, h('span', { class: 'libelle' }, 'Moins intéressants'), mots('secteurs_moins', 'Ajouter un secteur')),
    h('div', { class: 'champ-ligne' }, h('span', { class: 'libelle' }, 'Hors de ces secteurs, garder seulement'),
      h('div', { translate: 'no' }, pastilles('autres_secteurs_domaines', domaines, { etiquette: 'Domaines gardés hors de tes secteurs' })),
      h('span', { class: 'aide' }, 'Ces offres vont dans « Autres secteurs » sur la page À trier.')),
    h('div', { class: 'champ-ligne' }, h('span', { class: 'libelle' }, 'Tailles préférées'), mots('tailles', 'Ex. : scale-up')),
  ];
}

function editerEntreprises() {
  const zone = h('ul', { class: 'entreprises-edit' });
  const ajout = h('input', { class: 'champ', type: 'text', placeholder: 'Ajouter une entreprise, puis Entrée', 'aria-label': 'Ajouter une entreprise', maxlength: '80' });
  const maj = (i, modif) => changer('entreprises', etat.brouillon.entreprises.map((e, j) => (j === i ? { ...e, ...modif } : e)));
  const dessiner = () => zone.replaceChildren(...etat.brouillon.entreprises.map((e, i) => h('li', {},
    h('div', { class: 'ligne-entreprise' },
      h('span', { class: 'initiale', 'aria-hidden': 'true' }, e.nom.slice(0, 1).toUpperCase()),
      h('span', { class: 'nom', translate: 'no' }, e.nom),
      h('select', { class: 'champ groupe', 'aria-label': `Groupe de ${e.nom}`, onchange: (ev) => maj(i, { groupe: ev.target.value }) },
        Object.entries(etat.d.groupes).map(([g, l]) => h('option', { value: g, selected: g === e.groupe }, l))),
      h('span', { class: 'outils-ligne' },
        h('button', { type: 'button', class: 'retirer', 'aria-label': `Ne plus suivre ${e.nom}`, onclick: () => { changer('entreprises', etat.brouillon.entreprises.filter((_, j) => j !== i)); dessiner(); } }, icone(CROIX)))),
    h('details', { class: 'avance' },
      h('summary', {}, e.outil ? `Collecte directe : ${OUTILS[e.outil]}` : 'Collecte directe, autres noms'),
      h('div', { class: 'grille-3' },
        champ('Autres noms', h('input', { class: 'champ', value: e.alias, placeholder: 'séparés par des virgules', translate: 'no', oninput: (ev) => maj(i, { alias: ev.target.value }) })),
        champ('Outil de recrutement', h('select', { class: 'champ', onchange: (ev) => maj(i, { outil: ev.target.value }) },
          Object.entries(OUTILS).map(([v, l]) => h('option', { value: v, selected: v === e.outil }, l)))),
        champ('Identifiant ou adresse', h('input', { class: 'champ', value: e.adresse_ou_id, translate: 'no', oninput: (ev) => maj(i, { adresse_ou_id: ev.target.value.trim() }) })))))));
  ajout.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const nom = ajout.value.trim();
    if (nom && !etat.brouillon.entreprises.some(x => x.nom.toLowerCase() === nom.toLowerCase())) {
      changer('entreprises', [...etat.brouillon.entreprises, { nom, groupe: 'scale_up', alias: '', outil: '', adresse_ou_id: '' }]);
      dessiner();
    }
    ajout.value = '';
  });
  dessiner();
  return [ajout, zone, h('p', { class: 'aide' }, 'Leurs offres ont un bonus dans la note, et une offre de 6 mois chez elles va dans « À négocier ». '
    + 'Collecte directe : si leur page carrières utilise Ashby ou Workday, leurs offres sont lues directement.')];
}

function editerRecherches() {
  return [mots('requetes', 'Ajouter une recherche, ex. : stage computer vision'),
    h('p', { class: 'aide' }, 'Envoyées telles quelles aux sites. Pense au français et à l\'anglais.')];
}

function editerFins() {
  return [
    h('div', { class: 'champ-ligne' }, h('span', { class: 'libelle' }, 'Postes exclus'), mots('postes_exclus', 'Ajouter un poste')),
    h('div', { class: 'champ-ligne' }, h('span', { class: 'libelle' }, 'Contrats exclus'), mots('contrats_exclus', 'Ajouter un type de contrat')),
    h('div', { class: 'champ-ligne' }, h('span', { class: 'libelle' }, 'Niveaux trop élevés'), mots('niveaux_exclus', 'Ajouter un niveau')),
    champ('Ancienneté maximale d\'une offre (jours)', nombre('anciennete_max_jours', { min: 1, max: 365, pas: 1 }),
      'Cherchés dans le titre et le type de contrat de chaque offre, avant toute note de l\'IA.'),
  ];
}

// ======================================================================= conversation

function texteRiche(t) {
  return (t || '').split(/(\*\*[^*]+\*\*)/g).map(m => (m.startsWith('**') && m.endsWith('**') ? h('b', {}, m.slice(2, -2)) : m));
}

function difference(c) {
  const type = etat.d.champs[c.champ].type;
  if (type === 'liste' || type === 'entreprises') {
    const nomDe = (x) => (type === 'entreprises' ? x.nom : x);
    const avant = c.avant.map(nomDe);
    const apres = c.apres.map(nomDe);
    const morceaux = [
      ...apres.filter(x => !avant.includes(x)).map(x => h('span', { class: 'plus', translate: 'no' }, `+ ${x}`)),
      ...avant.filter(x => !apres.includes(x)).map(x => h('span', { class: 'moins', translate: 'no' }, `− ${x}`)),
    ];
    if (type === 'entreprises') {
      for (const e of c.apres) {
        const ancienne = c.avant.find(x => x.nom === e.nom);
        if (ancienne && ancienne.groupe !== e.groupe) morceaux.push(h('span', { translate: 'no' }, `${e.nom} → `), h('span', {}, etat.d.groupes[e.groupe]));
        if (ancienne && (ancienne.alias !== e.alias || ancienne.outil !== e.outil || ancienne.adresse_ou_id !== e.adresse_ou_id)) {
          morceaux.push(h('span', { translate: 'no' }, `${e.nom} : `),
            h('span', {}, e.outil ? `collecte directe ${OUTILS[e.outil]}` : 'détail modifié'));
        }
      }
      if (!morceaux.length) return [h('span', {}, 'nouvel ordre')];
    }
    if (!morceaux.length) {   // même éléments, autre ordre : on montre celui qui a le plus bougé
      const deplace = apres.map((x, j) => ({ x, de: avant.indexOf(x), a: j }))
        .sort((u, v) => Math.abs(v.a - v.de) - Math.abs(u.a - u.de) || (u.a - u.de) - (v.a - v.de))[0];
      return [h('span', { translate: 'no' }, `${deplace.x} : `), h('span', { class: 'avant' }, rang(deplace.de + 1)), ' → ', h('span', {}, rang(deplace.a + 1))];
    }
    return morceaux.flatMap((m, i) => (i ? [' ', m] : [m]));
  }
  return [h('span', { class: 'avant', translate: 'no' }, valeurTexte(c.champ, c.avant)), ' → ',
    h('span', { translate: 'no' }, valeurTexte(c.champ, c.apres))];
}

function dessinerFil({ defiler = true } = {}) {
  const fil = $('#fil');
  $('#effacer').hidden = !etat.messages.length;
  const puces = (l) => h('div', { class: 'suggestions' },
    l.map(x => h('button', { class: 'pastille', type: 'button', translate: 'no', onclick: () => envoyer(x) }, x)));
  if (!etat.messages.length) {
    fil.replaceChildren(h('div', { class: 'accueil-profil' },
      h('p', {}, 'Dis-moi ce qui change, avec tes mots : je modifie ton profil.'), puces(raccourcis(etat.p))));
    return;
  }
  const derniere = etat.messages.at(-1);
  const proposees = derniere.role !== 'user' && derniere.suggestions?.length ? derniere.suggestions : raccourcis(etat.p);
  // Seul le dernier échange est montré : les anciens messages sont repliés derrière un lien.
  let debut = etat.toutFil ? 0 : Math.max(0, etat.messages.length - 2);
  if (debut && etat.messages[debut].role !== 'user') debut -= 1;
  fil.replaceChildren(
    debut ? h('button', { class: 'plus-anciens', type: 'button', onclick: () => { etat.toutFil = true; dessinerFil({ defiler: false }); } },
      P.anciens(debut)) : '',
    ...etat.messages.slice(debut).map((m, j) => message(m, debut + j)),
    puces(proposees));
  if (defiler) fil.scrollTop = fil.scrollHeight;
}

function message(m, i) {
  if (m.role === 'user') return h('div', { class: 'bulle moi' }, h('p', { translate: 'no' }, m.texte));
  return h('div', { class: `bulle ia${m.erreur ? ' erreur-ia' : ''}`, role: m.erreur ? 'alert' : null },
    h('p', { translate: 'no' }, texteRiche(m.texte)),
    m.changements.length ? h('div', { class: 'modifs' },
      m.changements.map(c => h('div', { class: 'modif' }, h('span', { class: 'puce-modif' }),
        h('span', {}, h('b', {}, etat.d.champs[c.champ]?.libelle || c.libelle), LANGUE === 'en' ? ': ' : ' : ', difference(c)))),
      etat.annules.has(i) ? h('span', { class: 'annule' }, 'Annulé')
        : h('button', { class: 'annuler-modifs', type: 'button', onclick: () => annuler(m.changements, { depuisChat: i }) },
          m.changements.length > 1 ? 'Annuler ces changements' : 'Annuler ce changement')) : null,
    m.refus?.length && !m.erreur ? h('p', { class: 'refus' }, h('b', {}, 'Refusé : '), m.refus.join(' · ')) : null);
}

async function envoyer(t) {
  const zone = $('#message');
  const contenu = (t ?? zone.value).trim();
  if (!contenu || etat.enCours) return;
  etat.enCours = true;
  zone.value = '';
  $('#envoyer').disabled = true;
  const fil = $('#fil');
  fil.querySelector('.accueil-profil')?.remove();
  fil.querySelector('.suggestions')?.remove();
  fil.querySelector('.erreur')?.remove();
  fil.append(h('div', { class: 'bulle moi' }, h('p', { translate: 'no' }, contenu)),
    h('div', { class: 'bulle ia ecrit', 'aria-label': 'Gemini réfléchit' }, h('i'), h('i'), h('i')));
  fil.scrollTo({ top: fil.scrollHeight, behavior: reduit() ? 'auto' : 'smooth' });
  try {
    const d = await api('/api/profil/message', { texte: contenu });
    etat.messages = d.messages;
    etat.toutFil = false;
    appliquer(d, { flash: true });
    dessinerFil();
  } catch (e) {
    fil.querySelector('.ecrit')?.remove();
    fil.lastElementChild?.remove();
    fil.append(h('p', { class: 'erreur' }, e.message));
    zone.value = contenu;
  }
  etat.enCours = false;
  $('#envoyer').disabled = false;
  zone.focus();
}

// ======================================================================= branchements

$('#saisie').addEventListener('submit', (e) => { e.preventDefault(); envoyer(); });
$('#message').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); envoyer(); }
});
$('#effacer').addEventListener('click', async () => {
  const d = await api('/api/profil/effacer', {});
  etat.messages = d.messages;
  etat.annules.clear();
  etat.toutFil = false;
  dessinerFil();
});

// Téléphone : la conversation monte du bas.
const chat = $('#chat');
function basculerChat(ouvrirChat) {
  chat.classList.toggle('ouvert', ouvrirChat);
  $('#ouvrir-chat').setAttribute('aria-expanded', String(ouvrirChat));
  if (ouvrirChat) setTimeout(() => $('#message').focus(), 300);
  else $('#ouvrir-chat').focus();
}
$('#ouvrir-chat').addEventListener('click', () => basculerChat(!chat.classList.contains('ouvert')));
$('#fermer-chat').addEventListener('click', () => basculerChat(false));
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (chat.classList.contains('ouvert')) { e.preventDefault(); basculerChat(false); }
  else if (etat.ouverte) { e.preventDefault(); fermer({ rendreFocus: true }); }
});
window.addEventListener('beforeunload', (e) => { if (etat.ouverte && modifies().length) e.preventDefault(); });

brancherScrap(async (s) => { toast(s.erreur ? `Le scrap a planté : ${s.erreur}` : 'Scrap terminé.'); api('/api/profil').then(d => majMenu(d.menu)); });
charger().catch((e) => { console.error(e); toast('Impossible de charger ton profil : le serveur tourne-t-il ?'); });
