// Mon profil : ta recherche écrite en phrases. Chaque valeur soulignée se modifie d'un clic (enregistré tout de
// suite, annulable) ; à droite, une conversation avec Gemini modifie le profil à ta place.
import { $, h, api, toast, brancherScrap, majMenu, LOCALE, LANGUE } from './commun.js';

const etat = { d: null, p: null, alertes: [], messages: [], enCours: false, triEnAttente: false, annules: new Set() };

const EXEMPLES = [
  'Accepte aussi les stages de 6 mois',
  'Je veux commencer plutôt début mai',
  'Ajoute la robotique à mes domaines',
  'Suis aussi Alan et Qonto',
];
const GROUPES_TITRES = [
  ['priorite_absolue', 'Priorité absolue'], ['scale_up', 'Scale-ups'], ['grand_groupe', 'Grands groupes'], ['ecosysteme', 'Écosystèmes'],
];
const OUTILS = { '': 'Aucun', ashby: 'Ashby', workday: 'Workday' };

const SECTIONS = [
  { id: 'qui', champs: ['recherche', 'ecole', 'annee', 'majeure', 'competences'], dessin: tete },
  { id: 'quand', titre: 'Quand', champs: ['contrats', 'debut_au_plus_tot', 'debut_ideal', 'debut_au_plus_tard', 'fin_au_plus_tard', 'duree_min', 'duree_max', 'six_mois'], dessin: quand },
  { id: 'ou', titre: 'Où', champs: ['departements', 'hybride', 'full_remote'], dessin: ou },
  { id: 'domaines', titre: 'Domaines, par ordre de préférence', champs: ['domaines', 'domaines_phares'], dessin: domaines },
  { id: 'secteurs', titre: 'Secteurs', champs: ['secteurs_cible', 'secteurs_ok', 'secteurs_moins', 'autres_secteurs_domaines', 'tailles'], aussi: ['domaines'], dessin: secteurs },
  { id: 'entreprises', titre: 'Entreprises suivies', champs: ['entreprises'], dessin: entreprises },
  { id: 'recherches', titre: 'Recherches envoyées aux sites', champs: ['requetes'], dessin: recherches },
  { id: 'fins', champs: ['postes_exclus', 'contrats_exclus', 'niveaux_exclus', 'anciennete_max_jours'], dessin: fins },
];

// ======================================================================= mise en forme des valeurs

const dateLongue = (iso) => {
  const texte = new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(`${iso}T12:00:00`));
  return LANGUE === 'fr' ? texte.replace(/^1 /, '1er ') : texte;
};
const virgule = (n) => (LANGUE === 'en' ? String(n) : String(n).replace('.', ','));
const mois = (n) => (LANGUE === 'en' ? `${n} month${n > 1 ? 's' : ''}` : `${virgule(n)} mois`);

function valeurTexte(champ, v) {
  const type = etat.d.champs[champ].type;
  if (type === 'date') return dateLongue(v);
  if (type === 'nombre') return champ === 'anciennete_max_jours' ? P.jours(v) : mois(v);
  if (type === 'booleen') return v ? P.oui : P.non;
  if (type === 'choix') return etat.d.six_mois[v];
  if (type === 'texte') return v ? `« ${v} »` : '(vide)';
  return String(v);
}

// Les phrases du profil, écrites entières dans chaque langue (les valeurs sont glissées entre les morceaux).
const P = LANGUE === 'en' ? {
  un: (t) => (/^[aeiou]/i.test(t) ? 'An ' : 'A '), debut: ' starting between ', et: ' and ', ideal: ', ideally on ', fin: '. It ends by ', dure: ' and lasts ',
  a: ' to ', point: '.', six: 'Fixed 6-month offers are ', dans: 'In ', avec: ', with ', toute: 'all of Île-de-France',
  deps: (n) => `${n} department${n > 1 ? 's' : ''}`, hybride: ['hybrid accepted', 'hybrid refused'],
  remote: ['full remote accepted', 'full remote refused'], anciennete: 'Ignore offers published more than ', jours: (n) => `${n} days ago`,
  contrats: { 'stage,cdd': 'internship or fixed-term contract', stage: 'internship', cdd: 'fixed-term contract' },
  sixValeurs: { a_negocier: 'negotiable at your followed companies', exclure: 'always excluded' }, oui: 'yes', non: 'no',
} : {
  un: () => 'Un ', debut: ' qui commence entre le ', et: ' et le ', ideal: ', idéalement le ', fin: '. Il finit au plus tard le ', dure: ' et dure de ',
  a: ' à ', point: '.', six: 'Les offres de 6 mois fixes sont ', dans: 'Dans ', avec: ', avec ', toute: 'toute l\'Île-de-France',
  deps: (n) => `${n} département${n > 1 ? 's' : ''}`, hybride: ['hybride accepté', 'hybride refusé'],
  remote: ['télétravail complet accepté', 'télétravail complet refusé'], anciennete: 'Ignorer les offres publiées il y a plus de ', jours: (n) => `${n} jours`,
  contrats: { 'stage,cdd': 'stage ou CDD', stage: 'stage', cdd: 'CDD' },
  sixValeurs: { a_negocier: 'à négocier chez tes entreprises suivies', exclure: 'toujours exclues' }, oui: 'oui', non: 'non',
};
const contratsTexte = (c) => P.contrats[c.join(',')] || c.join(', ');

// ======================================================================= chargement et dessin

async function charger() {
  const d = await api('/api/profil');
  majMenu(d.menu);
  etat.d = d;
  etat.p = d.profil;
  etat.alertes = d.alertes;
  etat.messages = d.messages;
  dessinerTout();
  dessinerFil();
}

function dessinerTout() {
  $('#feuille').replaceChildren(h('div', { id: 'bandeaux' }),
    ...SECTIONS.map((s, i) => h('section', {
      class: `rubrique-profil apparait${s.id === 'qui' ? ' tete-profil' : ''}`, id: `sec-${s.id}`, style: `--i:${i}`,
    }, contenu(s))));
  dessinerBandeaux();
}

function contenu(s) {
  return [s.titre ? h('h2', {}, s.titre) : null, s.dessin()].flat(Infinity).filter(Boolean);
}

// Redessine les rubriques touchées par ces champs ; garde le focus là où il était (champ d'ajout d'une liste...).
function redessiner(champs, { flash = false } = {}) {
  const cle = document.activeElement?.dataset?.focus;
  const touchees = SECTIONS.filter(s => champs.some(c => s.champs.includes(c) || s.aussi?.includes(c)));
  for (const s of touchees) {
    const el = $(`#sec-${s.id}`);
    el.classList.remove('apparait');
    el.replaceChildren(...contenu(s));
  }
  if (cle) document.querySelector(`[data-focus="${CSS.escape(cle)}"]`)?.focus();
  if (flash) {
    const vraies = SECTIONS.filter(s => champs.some(c => s.champs.includes(c)));
    vraies.forEach((s) => {
      const el = $(`#sec-${s.id}`);
      if (s.id === 'fins') el.querySelector('details')?.setAttribute('open', '');
      el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
    });
    vraies[0] && $(`#sec-${vraies[0].id}`).scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }
  dessinerBandeaux();
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

// ======================================================================= enregistrer et annuler

const marque = $('#enregistre');
let minuteurMarque = 0;
function marquer(quoi) {
  clearTimeout(minuteurMarque);
  marque.className = `enregistre ${quoi || ''}`;
  marque.textContent = quoi === 'en-cours' ? 'Enregistrement…' : quoi === 'ok' ? 'Enregistré' : 'Enregistré automatiquement';
  if (quoi === 'ok') minuteurMarque = setTimeout(() => marquer(), 2200);
}

function appliquer(r, { flash = false } = {}) {
  etat.p = r.profil;
  etat.alertes = r.alertes;
  const champs = r.changements.map(c => c.champ);
  if (champs.some(c => etat.d.champs_tri.includes(c))) etat.triEnAttente = true;
  if (champs.length) redessiner(champs, { flash });
  else dessinerBandeaux();
}

// valeurs : {champ: nouvelle valeur}. toastTexte : un message avec « Annuler » (sinon l'indicateur suffit).
async function enregistrer(valeurs, { toastTexte = null } = {}) {
  marquer('en-cours');
  let r;
  try { r = await api('/api/profil', { valeurs }); } catch (e) {
    marquer();
    toast(`Pas enregistré : ${e.message}`);
    redessiner(Object.keys(valeurs));   // remet la valeur affichée comme avant
    return null;
  }
  appliquer(r);
  marquer('ok');
  if (toastTexte && r.changements.length) {
    toast(toastTexte, [h('button', { type: 'button', onclick: () => annuler(r.changements) }, 'Annuler')]);
  }
  return r;
}

async function annuler(changements, { depuisChat = null } = {}) {
  try {
    const r = await api('/api/profil', { valeurs: Object.fromEntries(changements.map(c => [c.champ, c.avant])) });
    appliquer(r, { flash: true });
    if (depuisChat !== null) { etat.annules.add(depuisChat); dessinerFil({ defiler: false }); }
    toast(changements.length > 1 ? 'Changements annulés.' : 'Changement annulé.');
  } catch (e) { toast(`Impossible d'annuler : ${e.message}`); }
}

// ======================================================================= bulle d'édition

let bulle = null;

function ouvrirBulle(ancre, ...contenuBulle) {
  fermerBulle({ rendreFocus: false });
  const b = h('div', { class: 'bulle-edition', role: 'dialog' }, contenuBulle);
  document.body.append(b);
  ancre.setAttribute('aria-expanded', 'true');
  bulle = { b, ancre };
  placerBulle();
  (b.querySelector('[data-premier]') || b.querySelector('input, select, button'))?.focus({ preventScroll: true });
}

// La bulle suit sa valeur quand la page défile ; elle se ferme si la valeur sort de l'écran.
function placerBulle() {
  if (!bulle) return;
  const { b, ancre } = bulle;
  const r = ancre.getBoundingClientRect();
  const zone = $('#feuille').getBoundingClientRect();
  if (r.bottom < zone.top || r.top > zone.bottom) { fermerBulle({ rendreFocus: false }); return; }
  const left = Math.min(Math.max(12, r.left - 8), innerWidth - b.offsetWidth - 12);
  let top = r.bottom + 8;
  if (top + b.offsetHeight > innerHeight - 12) top = Math.max(12, r.top - b.offsetHeight - 8);
  b.style.left = `${left}px`;
  b.style.top = `${top}px`;
}

function fermerBulle({ rendreFocus = true } = {}) {
  if (!bulle) return false;
  const { b, ancre } = bulle;
  bulle = null;
  b.remove();
  ancre.setAttribute('aria-expanded', 'false');
  if (rendreFocus && ancre.isConnected) ancre.focus();
  return true;
}

document.addEventListener('pointerdown', (e) => {
  if (bulle && !bulle.b.contains(e.target) && !bulle.ancre.contains(e.target)) fermerBulle({ rendreFocus: false });
});

const boutons = () => h('div', { class: 'boutons' },
  h('button', { class: 'pastille', type: 'button', onclick: () => fermerBulle() }, 'Annuler'),
  h('button', { class: 'bouton principal', type: 'submit' }, 'OK'));

// Une petite fiche : Entrée valide, Échap ferme. lire() renvoie la valeur à enregistrer.
function formulaire(champ, contenuForm, lire) {
  return h('form', {
    onsubmit: async (e) => {
      e.preventDefault();
      const r = await enregistrer({ [champ]: lire() }, { toastTexte: `Modifié : ${etat.d.champs[champ].libelle}.` });
      if (r) fermerBulle();
    },
  }, contenuForm, boutons());
}

function jeton(champ, texte, ouvrir, { non = false, traduire = true } = {}) {
  return h('button', {
    type: 'button', class: `jeton${non ? ' non' : ''}`, 'data-focus': `jeton-${champ}`, 'aria-haspopup': 'dialog',
    'aria-expanded': 'false', translate: traduire ? null : 'no', title: LANGUE === 'fr' ? etat.d.champs[champ]?.libelle : null,
    onclick: (e) => (bulle?.ancre === e.currentTarget ? fermerBulle() : ouvrir(e.currentTarget)),
  }, texte);
}

function editerDate(champ) {
  return (ancre) => {
    const entree = h('input', { class: 'champ', type: 'date', value: etat.p[champ], 'data-premier': '', required: true });
    ouvrirBulle(ancre, h('label', {}, etat.d.champs[champ].libelle), formulaire(champ, entree, () => entree.value));
  };
}

function editerNombre(champ, { pas = 0.5, min = 1, max = 12, unite = mois } = {}) {
  return (ancre) => {
    let v = etat.p[champ];
    const sortie = h('output', {}, unite(v));
    const changer = (d) => { v = Math.min(max, Math.max(min, Math.round((v + d) / pas) * pas)); sortie.textContent = unite(v); };
    ouvrirBulle(ancre, h('label', {}, etat.d.champs[champ].libelle), formulaire(champ, h('div', { class: 'pas' },
      h('button', { type: 'button', 'aria-label': 'Moins', onclick: () => changer(-pas), 'data-premier': '' }, '−'), sortie,
      h('button', { type: 'button', 'aria-label': 'Plus', onclick: () => changer(pas) }, '+')), () => v));
  };
}

function editerTexte(champ) {
  return (ancre) => {
    const entree = h('input', { class: 'champ', value: etat.p[champ], 'data-premier': '', maxlength: '400', translate: 'no' });
    ouvrirBulle(ancre, h('label', {}, etat.d.champs[champ].libelle), formulaire(champ, entree, () => entree.value));
  };
}

// Choix dans une liste : un clic enregistre et referme.
function editerOptions(champ, options) {
  return (ancre) => {
    ouvrirBulle(ancre, h('label', {}, etat.d.champs[champ].libelle), h('div', { class: 'options', role: 'radiogroup' },
      Object.entries(options).map(([cle, libelle], i) => h('button', {
        type: 'button', role: 'radio', 'aria-checked': String(JSON.stringify(etat.p[champ]) === cle),
        'data-premier': i === 0 ? '' : null,
        onclick: async () => {
          const valeur = JSON.parse(cle);
          if (JSON.stringify(valeur) === JSON.stringify(etat.p[champ])) { fermerBulle(); return; }
          if (await enregistrer({ [champ]: valeur }, { toastTexte: `Modifié : ${etat.d.champs[champ].libelle}.` })) fermerBulle();
        },
      }, libelle))));
  };
}

// ======================================================================= listes de mots

function mots(champ, placeholder) {
  const liste = etat.p[champ];
  const champAjout = h('input', { class: 'champ ajout', type: 'text', placeholder, 'aria-label': placeholder, 'data-focus': `mots-${champ}`, maxlength: '80' });
  champAjout.addEventListener('keydown', (e) => {
    if (e.key === 'Backspace' && !champAjout.value && liste.length) {
      enregistrer({ [champ]: liste.slice(0, -1) }, { toastTexte: `Retiré : ${liste.at(-1)}.` });
      return;
    }
    if (e.key !== 'Enter' && e.key !== ',') return;
    e.preventDefault();
    const v = champAjout.value.trim();
    if (!v) return;
    champAjout.value = '';
    if (!liste.some(x => x.toLowerCase() === v.toLowerCase())) enregistrer({ [champ]: [...liste, v] });
  });
  return h('div', { class: 'mots' },
    liste.map((m, i) => h('span', { class: 'mot', translate: 'no' }, m, h('button', {
      type: 'button', 'aria-label': `Retirer ${m}`,
      onclick: () => enregistrer({ [champ]: liste.filter((_, j) => j !== i) }, { toastTexte: `Retiré : ${m}.` }),
    }, '×'))), champAjout);
}

function rangee(libelle, champ, placeholder) {
  return h('div', { class: 'rangee' }, h('span', {}, libelle), mots(champ, placeholder));
}

// ======================================================================= rubriques

function tete() {
  const p = etat.p;
  const ouvrirRecherche = (b) => {
    const zone = h('textarea', { class: 'recherche-phrase', maxlength: '400', 'aria-label': 'Ce que tu cherches', translate: 'no' });
    zone.value = p.recherche;
    const finir = async (garder) => {
      zone.onblur = null;
      if (garder && zone.value.trim() !== p.recherche) await enregistrer({ recherche: zone.value }, { toastTexte: 'Modifié : Ce que tu cherches.' });
      else redessiner(['recherche']);
    };
    zone.onblur = () => finir(true);
    zone.onkeydown = (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); zone.blur(); }
      if (e.key === 'Escape') { e.preventDefault(); finir(false); }
    };
    b.replaceWith(zone);
    zone.focus();
    zone.setSelectionRange(zone.value.length, zone.value.length);
  };
  return [
    h('h2', {}, 'Ce que tu cherches'),
    h('button', {
      type: 'button', class: `recherche-phrase${p.recherche ? '' : ' vide'}`, 'data-focus': 'recherche',
      translate: p.recherche ? 'no' : null, onclick: e => ouvrirRecherche(e.currentTarget),
    }, p.recherche || 'Décris en une phrase le stage que tu cherches'),
    h('p', { class: 'qui' },
      jeton('ecole', p.ecole || 'École ?', editerTexte('ecole'), { traduire: !p.ecole }), h('span', { class: 'sep' }, '·'),
      jeton('annee', p.annee || 'Année ?', editerTexte('annee'), { traduire: !p.annee }), h('span', { class: 'sep' }, '·'),
      jeton('majeure', p.majeure || 'Majeure ?', editerTexte('majeure'), { traduire: !p.majeure })),
    h('p', { class: 'sous-titre' }, 'Compétences'),
    mots('competences', 'Ajouter une compétence'),
  ];
}

function quand() {
  const p = etat.p;
  const contrats = Object.fromEntries([[JSON.stringify(['stage', 'cdd']), 'Stage ou CDD'], [JSON.stringify(['stage']), 'Stage seulement'], [JSON.stringify(['cdd']), 'CDD seulement']]);
  const six = Object.fromEntries(Object.entries(etat.d.six_mois).map(([k, v]) => [JSON.stringify(k), v]));
  return [
    h('p', { class: 'phrase', translate: 'no' },
      P.un(contratsTexte(p.contrats)), jeton('contrats', contratsTexte(p.contrats), editerOptions('contrats', contrats)),
      P.debut, jeton('debut_au_plus_tot', dateLongue(p.debut_au_plus_tot), editerDate('debut_au_plus_tot')),
      P.et, jeton('debut_au_plus_tard', dateLongue(p.debut_au_plus_tard), editerDate('debut_au_plus_tard')),
      P.ideal, jeton('debut_ideal', dateLongue(p.debut_ideal), editerDate('debut_ideal')),
      P.fin, jeton('fin_au_plus_tard', dateLongue(p.fin_au_plus_tard), editerDate('fin_au_plus_tard')),
      P.dure, jeton('duree_min', mois(p.duree_min), editerNombre('duree_min')),
      P.a, jeton('duree_max', mois(p.duree_max), editerNombre('duree_max')), P.point),
    frise(p),
    h('p', { class: 'phrase', translate: 'no' }, P.six, jeton('six_mois', P.sixValeurs[p.six_mois], editerOptions('six_mois', six)), P.point),
    h('p', { class: 'aide' }, 'Les offres « 3 à 6 mois » ou « 4 à 6 mois » sont toujours gardées.'),
  ];
}

// Frise : la fenêtre de début (bande), le début idéal (point), le stage idéal (barre) et la fin au plus tard.
function frise(p) {
  const jour = (iso) => new Date(`${iso}T12:00:00`).getTime();
  const debutFrise = new Date(jour(p.debut_au_plus_tot)); debutFrise.setDate(1);
  const finFrise = new Date(jour(p.fin_au_plus_tard)); finFrise.setMonth(finFrise.getMonth() + 1, 1);
  const total = finFrise - debutFrise;
  const x = (t) => `${((t - debutFrise) / total) * 100}%`;
  const largeur = (a, b) => `${(Math.max(0, b - a) / total) * 100}%`;
  const moisNoms = [];
  for (const m = new Date(debutFrise); m < finFrise; m.setMonth(m.getMonth() + 1)) {
    moisNoms.push(h('span', { class: 'mois', style: `left:${x(m.getTime())}` }, new Intl.DateTimeFormat(LOCALE, { month: 'short' }).format(m)));
  }
  const ideal = jour(p.debut_ideal);
  const finStage = new Date(ideal); finStage.setMonth(finStage.getMonth() + Math.floor(p.duree_max));
  if (p.duree_max % 1) finStage.setDate(finStage.getDate() + 15);
  const finMin = new Date(ideal); finMin.setMonth(finMin.getMonth() + Math.floor(p.duree_min));
  const trop = finMin.getTime() > jour(p.fin_au_plus_tard);
  const finBarre = Math.min(finStage.getTime(), jour(p.fin_au_plus_tard));
  return h('div', { class: 'frise', 'aria-hidden': 'true', translate: 'no' }, moisNoms,
    h('span', { class: 'fenetre-debut', style: `left:${x(jour(p.debut_au_plus_tot))};width:${largeur(jour(p.debut_au_plus_tot), jour(p.debut_au_plus_tard))}` }),
    h('span', { class: `stage${trop ? ' trop-long' : ''}`, style: `left:${x(ideal)};width:${largeur(ideal, finBarre)}` }),
    h('span', { class: 'ideal', style: `left:${x(ideal)}` }),
    h('span', { class: 'fin', style: `left:${x(jour(p.fin_au_plus_tard))}` }),
    h('span', { class: 'legende', style: `left:${x((jour(p.debut_au_plus_tot) + jour(p.debut_au_plus_tard)) / 2)}` }, LANGUE === 'en' ? 'start' : 'début'),
    h('span', { class: 'legende fin-l', style: `left:${x(jour(p.fin_au_plus_tard))}` }, LANGUE === 'en' ? 'latest end' : 'fin au plus tard'));
}

function ou() {
  const p = etat.p;
  const tous = Object.keys(etat.d.departements).every(c => p.departements.includes(c));
  const basculer = (champ) => () => enregistrer({ [champ]: !p[champ] }, { toastTexte: `Modifié : ${etat.d.champs[champ].libelle}.` });
  const bascule = (champ, oui, non) => h('button', {
    type: 'button', class: `jeton${p[champ] ? '' : ' non'}`, 'aria-pressed': String(p[champ]), 'data-focus': `jeton-${champ}`, onclick: basculer(champ),
  }, p[champ] ? oui : non);
  return [
    h('p', { class: 'phrase', translate: 'no' }, P.dans, h('b', { class: 'zone' }, tous ? P.toute : P.deps(p.departements.length)),
      P.avec, bascule('hybride', ...P.hybride), P.et.replace(' le', ''), bascule('full_remote', ...P.remote), P.point),
    h('div', { class: 'choix', style: 'margin-top:14px', role: 'group', 'aria-label': 'Départements' },
      Object.entries(etat.d.departements).map(([code, nom]) => {
        const pris = p.departements.includes(code);
        return h('button', {
          type: 'button', class: 'pastille', 'aria-pressed': String(pris), 'data-focus': `dep-${code}`,
          onclick: () => enregistrer({ departements: pris ? p.departements.filter(c => c !== code) : [...p.departements, code] }),
        }, nom, ' ', h('small', {}, code));
      })),
    h('p', { class: 'aide' }, 'L\'outil ne couvre pour l\'instant que l\'Île-de-France.'),
  ];
}

function domaines() {
  const p = etat.p;
  const icone = (d, plein = false) => {
    const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', 'ic'); s.setAttribute('aria-hidden', 'true');
    if (plein) s.style.fill = 'currentColor';
    s.innerHTML = `<path d="${d}"/>`;   // tracé fixe, écrit ici (jamais de donnée)
    return s;
  };
  const ETOILE = 'M12 4l2.4 5 5.4.8-3.9 3.8.9 5.4-4.8-2.6-4.8 2.6.9-5.4L4.2 9.8 9.6 9z';
  const deplacer = (i, d) => {
    const l = [...p.domaines];
    [l[i], l[i + d]] = [l[i + d], l[i]];
    enregistrer({ domaines: l });
  };
  const ajout = h('input', { class: 'champ', type: 'text', placeholder: 'Ajouter un domaine (Entrée)', 'aria-label': 'Ajouter un domaine', maxlength: '80', 'data-focus': 'ajout-domaine' });
  ajout.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const v = ajout.value.trim();
    if (v && !p.domaines.some(x => x.toLowerCase() === v.toLowerCase())) enregistrer({ domaines: [...p.domaines, v] });
    ajout.value = '';
  });
  return [
    h('ol', { class: 'domaines' }, p.domaines.map((nom, i) => {
      const phare = p.domaines_phares.includes(nom);
      return h('li', { class: `domaine${phare ? ' phare' : ''}` },
        h('span', { class: 'rang' }, String(i + 1)),
        h('span', { class: 'nom' }, h('span', { translate: 'no' }, nom), phare ? h('small', {}, 'très intéressant') : null),
        h('span', { class: 'outils-ligne' },
          h('button', {
            type: 'button', class: 'etoile', 'aria-pressed': String(phare), 'data-focus': `etoile-${i}`,
            'aria-label': phare ? `${nom} : ne plus marquer comme très intéressant` : `${nom} : marquer comme très intéressant`,
            title: 'Très intéressant',
            onclick: () => enregistrer({ domaines_phares: phare ? p.domaines_phares.filter(x => x !== nom) : [...p.domaines_phares, nom] }),
          }, icone(ETOILE, phare)),
          h('button', { type: 'button', 'aria-label': `Monter ${nom}`, disabled: i === 0, 'data-focus': `monter-${nom}`, onclick: () => deplacer(i, -1) }, icone('M6 15l6-6 6 6')),
          h('button', { type: 'button', 'aria-label': `Descendre ${nom}`, disabled: i === p.domaines.length - 1, 'data-focus': `descendre-${nom}`, onclick: () => deplacer(i, 1) }, icone('M6 9l6 6 6-6')),
          h('button', {
            type: 'button', class: 'retirer', 'aria-label': `Retirer ${nom}`,
            onclick: () => enregistrer({ domaines: p.domaines.filter(x => x !== nom) }, { toastTexte: `Retiré : ${nom}.` }),
          }, icone('M6 6l12 12M18 6L6 18'))));
    })),
    h('div', { class: 'ajout-ligne' }, ajout),
    h('p', { class: 'aide' }, 'L\'ordre compte : le premier domaine pèse le plus dans la note. L\'étoile marque ceux qui rendent une offre très intéressante.'),
  ];
}

function secteurs() {
  const p = etat.p;
  return [
    rangee('Visés', 'secteurs_cible', 'Ajouter un secteur'),
    rangee('Vont aussi', 'secteurs_ok', 'Ajouter un secteur'),
    rangee('Moins intéressants', 'secteurs_moins', 'Ajouter un secteur'),
    h('p', { class: 'sous-titre' }, 'Hors de ces secteurs, garder seulement les postes en :'),
    h('div', { class: 'choix petits', role: 'group', 'aria-label': 'Domaines gardés hors de tes secteurs' }, p.domaines.map((nom, i) => {
      const pris = p.autres_secteurs_domaines.includes(nom);
      return h('button', {
        type: 'button', class: 'pastille', 'aria-pressed': String(pris), translate: 'no', 'data-focus': `autre-${i}`,
        onclick: () => enregistrer({ autres_secteurs_domaines: pris ? p.autres_secteurs_domaines.filter(x => x !== nom) : [...p.autres_secteurs_domaines, nom] }),
      }, nom);
    })),
    h('p', { class: 'aide' }, 'Ces offres-là vont dans « Autres secteurs » sur la page À trier.'),
    rangee('Tailles préférées', 'tailles', 'Ex. : scale-up'),
  ];
}

function entreprises() {
  const p = etat.p;
  const tuile = (e, i) => h('button', {
    type: 'button', class: 'tuile', 'aria-haspopup': 'dialog', 'aria-expanded': 'false', 'data-focus': `entreprise-${e.nom}`,
    onclick: (ev) => editerEntreprise(ev.currentTarget, i),
  }, h('span', { class: 'initiale', 'aria-hidden': 'true' }, e.nom.slice(0, 1).toUpperCase()),
  h('span', { style: 'min-width:0' }, h('b', { translate: 'no' }, e.nom),
    e.outil ? h('small', { class: 'directe' }, 'collecte directe') : e.alias ? h('small', { translate: 'no' }, e.alias) : null));
  const ajouter = h('button', {
    type: 'button', class: 'tuile ajouter-tuile', 'data-focus': 'ajouter-entreprise',
    onclick: () => {
      const entree = h('input', { class: 'champ', type: 'text', placeholder: 'Nom de l\'entreprise', 'aria-label': 'Nom de l\'entreprise', maxlength: '80' });
      const finir = async (garder) => {
        entree.onblur = null;
        const nom = entree.value.trim();
        if (garder && nom && !p.entreprises.some(x => x.nom.toLowerCase() === nom.toLowerCase())) {
          await enregistrer({ entreprises: [...p.entreprises, { nom, groupe: 'scale_up' }] }, { toastTexte: `Ajouté aux entreprises suivies : ${nom}.` });
        } else redessiner(['entreprises']);
      };
      entree.onblur = () => finir(true);
      entree.onkeydown = (e) => {
        if (e.key === 'Enter') { e.preventDefault(); finir(true); }
        if (e.key === 'Escape') { e.preventDefault(); finir(false); }
      };
      ajouter.replaceWith(h('div', { class: 'tuile-saisie' }, entree));
      entree.focus();
    },
  }, '+ Ajouter');
  const groupes = GROUPES_TITRES.map(([g, titre]) => {
    const liste = p.entreprises.map((e, i) => [e, i]).filter(([e]) => e.groupe === g);
    if (!liste.length) return null;
    return h('div', { class: 'groupe-entreprises' }, h('h3', {}, titre, h('small', {}, String(liste.length))),
      h('div', { class: 'tuiles' }, liste.map(([e, i]) => tuile(e, i))));
  });
  return [
    h('p', { class: 'aide', style: 'margin:-6px 0 16px' }, 'Leurs offres ont un bonus dans la note, et une offre de 6 mois chez elles va dans « À négocier ».'),
    groupes,
    h('div', { class: 'tuiles', style: 'margin-top:12px' }, ajouter),
  ];
}

function editerEntreprise(ancre, i) {
  const e = { ...etat.p.entreprises[i] };
  const nom = h('input', { class: 'champ', value: e.nom, 'aria-label': 'Nom', maxlength: '80', translate: 'no' });
  const groupes = h('div', { class: 'choix petits', role: 'radiogroup', 'aria-label': 'Groupe' });
  const dessinerGroupes = () => groupes.replaceChildren(...Object.entries(etat.d.groupes).map(([g, libelle]) => h('button', {
    type: 'button', class: 'pastille', role: 'radio', 'aria-checked': String(e.groupe === g), 'aria-pressed': String(e.groupe === g),
    onclick: () => { e.groupe = g; dessinerGroupes(); },
  }, libelle)));
  dessinerGroupes();
  const alias = h('input', { class: 'champ', value: e.alias, placeholder: 'Autres noms, séparés par des virgules', 'aria-label': 'Autres noms', translate: 'no' });
  const outil = h('select', { class: 'champ', 'aria-label': 'Outil de recrutement' },
    Object.entries(OUTILS).map(([v, l]) => h('option', { value: v, selected: v === e.outil }, l)));
  const adresse = h('input', { class: 'champ', value: e.adresse_ou_id, placeholder: 'Identifiant Ashby ou adresse Workday', 'aria-label': 'Identifiant ou adresse', translate: 'no' });
  const enregistrerEntreprise = async (ev) => {
    ev.preventDefault();
    const liste = etat.p.entreprises.map((x, j) => (j === i ? {
      ...e, nom: nom.value.trim() || e.nom, alias: alias.value, outil: outil.value, adresse_ou_id: adresse.value.trim(),
    } : x));
    if (await enregistrer({ entreprises: liste }, { toastTexte: `Modifié : ${nom.value.trim() || e.nom}.` })) fermerBulle({ rendreFocus: false });
  };
  ouvrirBulle(ancre, h('form', { class: 'edition-entreprise', onsubmit: enregistrerEntreprise },
    h('label', {}, 'Entreprise'), nom,
    h('label', { style: 'margin-top:14px' }, 'Groupe'), groupes,
    h('label', {}, 'Autres noms'), alias,
    h('details', { open: e.outil ? '' : null }, h('summary', {}, 'Collecte directe de ses offres'),
      h('p', { class: 'aide', style: 'margin-top:6px' }, 'Si sa page carrières utilise Ashby ou Workday, ses offres sont lues directement.'), outil, adresse),
    h('div', { class: 'boutons' },
      h('button', {
        type: 'button', class: 'retirer',
        onclick: async () => {
          if (await enregistrer({ entreprises: etat.p.entreprises.filter((_, j) => j !== i) }, { toastTexte: `Plus suivie : ${e.nom}.` })) fermerBulle({ rendreFocus: false });
        },
      }, 'Ne plus suivre'),
      h('button', { class: 'bouton principal', type: 'submit' }, 'OK'))));
}

function recherches() {
  return [
    mots('requetes', 'Ajouter une recherche, ex. : stage computer vision'),
    h('p', { class: 'aide' }, 'Envoyées telles quelles à Google Jobs (quelques-unes par jour, à tour de rôle) et à Careerjet (toutes, à chaque scrap). Pense au français et à l\'anglais.'),
  ];
}

function fins() {
  const p = etat.p;
  return h('details', { class: 'filtres-fins', open: etat.finsOuvert ? '' : null, ontoggle: (e) => { etat.finsOuvert = e.target.open; } },
    h('summary', {}, 'Filtres fins : postes, contrats et niveaux exclus, ancienneté'),
    h('p', { class: 'phrase', style: 'font-size:16px', translate: 'no' }, P.anciennete,
      jeton('anciennete_max_jours', P.jours(p.anciennete_max_jours), editerNombre('anciennete_max_jours', { pas: 5, min: 5, max: 365, unite: P.jours })), P.point),
    rangee('Postes exclus', 'postes_exclus', 'Ajouter un poste'),
    rangee('Contrats exclus', 'contrats_exclus', 'Ajouter un type de contrat'),
    rangee('Niveaux trop élevés', 'niveaux_exclus', 'Ajouter un niveau'),
    h('p', { class: 'aide' }, 'Cherchés dans le titre et le type de contrat de chaque offre, avant toute note de l\'IA.'));
}

// ======================================================================= conversation

function texteRiche(texte) {
  return (texte || '').split(/(\*\*[^*]+\*\*)/g).map(m => (m.startsWith('**') && m.endsWith('**') ? h('b', {}, m.slice(2, -2)) : m));
}

function difference(c) {
  const type = etat.d.champs[c.champ].type;
  if (type === 'liste' || type === 'entreprises') {
    const nomDe = (x) => (type === 'entreprises' ? x.nom : x);
    const avant = c.avant.map(nomDe);
    const apres = c.apres.map(nomDe);
    const plus = apres.filter(x => !avant.includes(x));
    const moins = avant.filter(x => !apres.includes(x));
    const morceaux = [...plus.map(x => h('span', { class: 'plus', translate: 'no' }, `+ ${x}`)), ...moins.map(x => h('span', { class: 'moins', translate: 'no' }, `− ${x}`))];
    if (type === 'entreprises') {
      for (const e of c.apres) {
        const ancienne = c.avant.find(x => x.nom === e.nom);
        if (ancienne && ancienne.groupe !== e.groupe) morceaux.push(h('span', { translate: 'no' }, `${e.nom} → `), h('span', {}, etat.d.groupes[e.groupe]));
      }
    }
    if (!morceaux.length) return [h('span', {}, 'nouvel ordre : '), h('span', { translate: 'no' }, apres.join(' › '))];
    return morceaux.flatMap((m, i) => (i ? [' ', m] : [m]));
  }
  return [h('span', { class: 'avant', translate: type === 'texte' ? 'no' : null }, valeurTexte(c.champ, c.avant)), ' → ',
    h('span', { translate: type === 'texte' ? 'no' : null }, valeurTexte(c.champ, c.apres))];
}

function dessinerFil({ defiler = true } = {}) {
  const fil = $('#fil');
  $('#effacer').hidden = !etat.messages.length;
  if (!etat.messages.length) {
    fil.replaceChildren(h('div', { class: 'accueil-profil' },
      h('p', {}, 'Dis-moi ce qui change dans ta recherche, avec tes mots. Je modifie ton profil et tu vois le résultat à gauche.'),
      h('div', { class: 'suggestions' }, EXEMPLES.map(x => h('button', { class: 'pastille', type: 'button', onclick: () => envoyer(x) }, x)))));
    return;
  }
  const derniere = etat.messages.at(-1);
  fil.replaceChildren(...etat.messages.map(message),
    derniere.role !== 'user' && derniere.suggestions?.length ? h('div', { class: 'suggestions' },
      derniere.suggestions.map(x => h('button', { class: 'pastille', type: 'button', translate: 'no', onclick: () => envoyer(x) }, x))) : '');
  if (defiler) fil.scrollTop = fil.scrollHeight;
}

function message(m, i) {
  if (m.role === 'user') return h('div', { class: 'bulle moi' }, h('p', { translate: 'no' }, m.texte));
  return h('div', { class: 'bulle ia' },
    h('p', { translate: 'no' }, texteRiche(m.texte)),
    m.changements.length ? h('div', { class: 'modifs' },
      m.changements.map(c => h('div', { class: 'modif' }, h('span', { class: 'puce-modif' }),
        h('span', {}, h('b', {}, c.libelle), LANGUE === 'en' ? ': ' : ' : ', difference(c)))),
      etat.annules.has(i) ? h('span', { class: 'annule' }, 'Annulé')
        : h('button', { class: 'annuler-modifs', type: 'button', onclick: () => annuler(m.changements, { depuisChat: i }) },
          m.changements.length > 1 ? 'Annuler ces changements' : 'Annuler ce changement')) : null,
    m.refus?.length && !m.changements.length ? h('p', { class: 'refus' }, m.refus.join(' · ')) : null);
}

async function envoyer(texte) {
  const zone = $('#message');
  const contenuMessage = (texte ?? zone.value).trim();
  if (!contenuMessage || etat.enCours) return;
  etat.enCours = true;
  zone.value = '';
  $('#envoyer').disabled = true;
  const fil = $('#fil');
  fil.querySelector('.accueil-profil')?.remove();
  fil.querySelector('.suggestions')?.remove();
  fil.querySelector('.erreur')?.remove();
  fil.append(h('div', { class: 'bulle moi' }, h('p', { translate: 'no' }, contenuMessage)),
    h('div', { class: 'bulle ia ecrit', 'aria-label': 'Gemini réfléchit' }, h('i'), h('i'), h('i')));
  fil.scrollTo({ top: fil.scrollHeight, behavior: 'smooth' });
  try {
    const d = await api('/api/profil/message', { texte: contenuMessage });
    etat.messages = d.messages;
    dessinerFil();
    appliquer(d, { flash: true });
  } catch (e) {
    fil.querySelector('.ecrit')?.remove();
    fil.lastElementChild?.remove();
    fil.append(h('p', { class: 'erreur' }, e.message));
    zone.value = contenuMessage;
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
  dessinerFil();
});

// Téléphone : la conversation monte du bas.
const chat = $('#chat');
function basculerChat(ouvrir) {
  chat.classList.toggle('ouvert', ouvrir);
  $('#ouvrir-chat').setAttribute('aria-expanded', String(ouvrir));
  if (ouvrir) setTimeout(() => $('#message').focus(), 300);
  else $('#ouvrir-chat').focus();
}
$('#ouvrir-chat').addEventListener('click', () => basculerChat(!chat.classList.contains('ouvert')));
$('#fermer-chat').addEventListener('click', () => basculerChat(false));

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (fermerBulle()) { e.preventDefault(); return; }
  if (chat.classList.contains('ouvert')) { e.preventDefault(); basculerChat(false); }
});
$('#feuille').addEventListener('scroll', placerBulle, { passive: true });
window.addEventListener('resize', placerBulle);

brancherScrap(async (s) => { toast(s.erreur ? `Le scrap a planté : ${s.erreur}` : 'Scrap terminé.'); api('/api/profil').then(d => majMenu(d.menu)); });
charger().catch((e) => { console.error(e); toast('Impossible de charger ton profil : le serveur tourne-t-il ?'); });
