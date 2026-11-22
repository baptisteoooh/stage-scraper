// Entretien d'accueil (/bienvenue) : 6 questions courtes, une à la fois, puis une phrase qui résume tout et « C'est bon ».
// Une réponse = un clic sur une puce (ou plusieurs, puis « Suivant »), ou quelques mots tapés, ou « Passer ».
// Rien n'est écrit avant « C'est bon » : le brouillon vit ici (et dans sessionStorage, pour survivre à un rechargement).
// Tout ce que la page affiche vient du serveur : ce qui a été noté, la phrase finale, et « C'est enregistré »
// seulement après que le serveur a écrit ET relu le profil.
import { $, h, api, toast, messageSuivant } from './commun.js';

const DEPUIS_PROFIL = new URLSearchParams(location.search).get('depuis') === 'profil';
const CLE = 'entretien-accueil';
const etat = {
  questions: [], index: 0, q: null, choix: {}, valeurs: {}, retenus: {}, passees: [],
  versRecap: false, occupe: false, note: null,
};
const reduit = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

// ======================================================================= brouillon gardé le temps de la visite

function garder() {
  try {
    sessionStorage.setItem(CLE, JSON.stringify({ valeurs: etat.valeurs, retenus: etat.retenus, passees: etat.passees, index: etat.index }));
  } catch { /* stockage indisponible : tant pis, on garde en mémoire */ }
}
function reprendre() {
  try {
    const d = JSON.parse(sessionStorage.getItem(CLE) || 'null');
    if (d && typeof d === 'object') Object.assign(etat, { valeurs: d.valeurs || {}, retenus: d.retenus || {}, passees: d.passees || [], index: d.index || 0 });
  } catch { /* rien à reprendre */ }
}
function oublier() {
  try { sessionStorage.removeItem(CLE); } catch { /* rien */ }
}

// ======================================================================= dessin commun

function progression(fini = false) {
  $('#progression').replaceChildren(...etat.questions.map((q, i) => {
    const faite = fini || q.id in etat.retenus || etat.passees.includes(q.id);
    const classe = !fini && i === etat.index ? 'en-cours' : faite ? 'faite' : '';
    return h('li', { class: classe, 'aria-current': !fini && i === etat.index ? 'step' : null },
      h('span', { class: 'sr-only' }, `${i + 1}/${etat.questions.length}`));
  }));
}

function afficher(...enfants) {
  const etape = $('#etape');
  etape.replaceChildren(...enfants.flat(Infinity).filter(Boolean));
  const titre = etape.querySelector('h1');
  if (titre) titre.focus({ preventScroll: true });
}

const icone = (d) => {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', 'ic'); s.setAttribute('aria-hidden', 'true');
  s.innerHTML = `<path d="${d}"/>`;   // tracé fixe, écrit ici (jamais de donnée)
  return s;
};
const FLECHE = 'M12 19V5M6 11l6-6 6 6';
const COCHE = 'M5 12.5l4.5 4.5L19 7.5';

// ======================================================================= une question

async function montrerQuestion(i) {
  etat.index = i;
  garder();
  progression();
  const id = etat.questions[i].id;
  try {
    etat.q = await api('/api/entretien/question', { id, valeurs: etat.valeurs });
  } catch (e) { erreurBloquante(e); return; }
  etat.choix = Object.fromEntries(etat.q.rangees.map(r => [r.id, [...r.choisis]]));
  etat.touchees = new Set();
  dessinerQuestion();
}

// Une seule rangée à choix unique : le clic suffit, pas besoin de « Suivant ».
const auClic = () => etat.q.rangees.length === 1 && !etat.q.rangees[0].multiple;
// Plusieurs rangées à choix unique (début + durée, zone + télétravail) : dès qu'on a choisi dans chacune, on passe à la suite.
const complete = () => etat.q.rangees.every(r => !r.multiple && etat.touchees.has(r.id) && etat.choix[r.id].length);

function dessinerQuestion() {
  const q = etat.q;
  const premiere = etat.index === 0 && !Object.keys(etat.retenus).length && !etat.passees.length;
  const note = etat.note;
  etat.note = null;
  afficher(
    note ? h('p', { class: 'retenu' }, icone(COCHE), h('span', {}, 'Noté'), h('span', { class: 'valeur', translate: 'no' }, note)) : null,
    premiere && !DEPUIS_PROFIL ? h('p', { class: 'bonjour' }, 'Bienvenue ! 6 questions rapides, et je règle ta recherche tout seul.') : null,
    h('h1', { id: 'titre-etape', tabindex: '-1' }, q.titre),
    h('p', { class: 'aide' }, q.aide),
    q.rangees.map(rangee),
    h('form', { class: 'libre', onsubmit: (e) => { e.preventDefault(); envoyerTexte(); } },
      h('label', { class: 'sr-only', for: 'texte-libre' }, 'Ta réponse avec tes mots'),
      h('input', { class: 'champ', id: 'texte-libre', type: 'text', maxlength: '300', autocomplete: 'off', placeholder: q.exemple }),
      h('button', { class: 'bouton principal', type: 'submit', 'aria-label': 'Envoyer' }, icone(FLECHE))),
    h('p', { class: 'erreur', id: 'erreur', role: 'alert' }),
    h('div', { class: 'actions' },
      h('div', { class: 'liens' },
        etat.index > 0 && !etat.versRecap ? h('button', { class: 'lien', type: 'button', onclick: () => montrerQuestion(etat.index - 1) }, 'Retour') : null,
        h('button', { class: 'lien', type: 'button', onclick: passer }, etat.versRecap ? 'Garder comme avant' : 'Passer')),
      auClic() && !aDesChoix() ? null : h('button', { class: 'bouton principal', id: 'suivant', type: 'button', onclick: envoyerChoix, disabled: !aDesChoix() }, 'Suivant')),
  );
}

const aDesChoix = () => Object.values(etat.choix).some(l => l.length);

function rangee(r) {
  const zone = h('div', { class: 'puces-choix', role: r.multiple ? 'group' : 'radiogroup', 'aria-label': r.libelle || etat.q.titre });
  const dessiner = () => zone.replaceChildren(...r.choix.map((c) => {
    const rang = etat.choix[r.id].indexOf(c.id);
    const pris = rang >= 0;
    return h('button', {
      type: 'button', class: 'pastille', 'aria-pressed': String(pris), role: r.multiple ? null : 'radio',
      'aria-checked': r.multiple ? null : String(pris), 'data-id': c.id,
      translate: r.id === 'entreprises' || c.id.startsWith('x:') ? 'no' : null,   // noms propres et mots tapés : jamais traduits
      onclick: () => {
        const l = etat.choix[r.id];
        etat.choix[r.id] = r.multiple ? (pris ? l.filter(x => x !== c.id) : [...l, c.id]) : [c.id];
        dessiner();
        zone.querySelector(`[data-id="${CSS.escape(c.id)}"]`)?.focus();
        $('#erreur')?.replaceChildren();
        etat.touchees.add(r.id);
        if (auClic() || complete()) { envoyerChoix(); return; }
        const suivant = $('#suivant');
        if (suivant) suivant.disabled = !aDesChoix();
      },
    }, r.ordonne && pris && etat.choix[r.id].length > 1 ? h('span', { class: 'rang-puce', 'aria-hidden': 'true' }, String(rang + 1)) : null, c.libelle);
  }));
  dessiner();
  return [r.libelle ? h('p', { class: 'rangee-titre' }, r.libelle) : null, zone];
}

// ======================================================================= réponses

async function repondre(corps, bouton) {
  if (etat.occupe) return;
  etat.occupe = true;
  const carte = $('#carte');
  carte.setAttribute('aria-busy', 'true');
  if (bouton) bouton.disabled = true;
  const attente = corps.texte ? h('div', { class: 'bulle ia ecrit', 'aria-label': 'Je lis ta réponse' }, h('i'), h('i'), h('i')) : null;
  if (attente) $('.libre').after(attente);
  try {
    const r = await api('/api/entretien/repondre', { question: etat.q.id, valeurs: etat.valeurs, ...corps });
    if (!r.compris) {
      attente?.remove();
      $('#erreur').replaceChildren("Je n'ai pas compris. Choisis une réponse ci-dessus, ou dis-le autrement.");
      $('#texte-libre')?.focus();
      return;
    }
    etat.valeurs = r.valeurs;
    etat.retenus[etat.q.id] = r.retenu;
    etat.passees = etat.passees.filter(x => x !== etat.q.id);
    etat.note = r.retenu;
    await suite();
  } catch (e) {
    attente?.remove();
    $('#erreur')?.replaceChildren(e.message);
  } finally {
    etat.occupe = false;
    carte.removeAttribute('aria-busy');
    if (bouton?.isConnected) bouton.disabled = false;
  }
}

function envoyerChoix() {
  if (!aDesChoix()) return;
  repondre({ choix: etat.choix }, $('#suivant'));
}

function envoyerTexte() {
  const champ = $('#texte-libre');
  const texte = champ.value.trim();
  if (!texte) { champ.focus(); return; }
  repondre(aDesChoix() ? { texte, choix: etat.choix } : { texte }, champ.form.querySelector('button'));   // le texte complète les puces cochées
}

async function passer() {
  if (etat.occupe) return;
  if (!(etat.q.id in etat.retenus) && !etat.passees.includes(etat.q.id)) etat.passees.push(etat.q.id);
  await suite();
}

async function suite() {
  const prochaine = etat.index + 1;
  if (etat.versRecap || prochaine >= etat.questions.length) { await recapitulatif(); return; }
  await montrerQuestion(prochaine);
}

// ======================================================================= récapitulatif en une phrase

async function recapitulatif() {
  etat.versRecap = true;
  etat.index = etat.questions.length;
  garder();
  progression(true);
  let r;
  try { r = await api('/api/entretien/apercu', { valeurs: etat.valeurs }); } catch (e) { erreurBloquante(e); return; }
  // Un <button> ne se coupe pas d'une ligne à l'autre : chaque morceau est un texte en ligne qui se comporte en bouton.
  const phrase = h('p', { class: 'phrase-recap', translate: 'no' }, r.segments.map(s => (s.question
    ? h('span', {
      class: 'morceau', role: 'button', tabindex: '0', title: 'Changer', onclick: () => corriger(s.question),
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); corriger(s.question); } },
    }, s.texte)
    : s.texte)));
  afficher(
    h('p', { class: 'surtitre' }, "Voilà ce que j'ai compris"),
    h('h1', { id: 'titre-etape', tabindex: '-1', class: 'sr-only' }, "Voilà ce que j'ai compris"),
    phrase,
    h('p', { class: 'aide' }, 'Touche un morceau de la phrase pour le changer.'),
    r.alertes?.length ? h('p', { class: 'alerte', translate: 'no' }, r.alertes[0]) : null,
    h('p', { class: 'erreur', id: 'erreur', role: 'alert' }, r.erreur || ''),
    h('div', { class: 'actions' }, h('button', { class: 'bouton principal', id: 'valider', type: 'button', disabled: !!r.erreur, onclick: terminer }, "C'est bon")),
  );
}

function corriger(qid) {
  montrerQuestion(etat.questions.findIndex(q => q.id === qid));
}

async function terminer(e) {
  const bouton = e.currentTarget;
  bouton.disabled = true;
  bouton.textContent = 'Enregistrement…';
  let r;
  try {
    r = await api('/api/entretien/terminer', { valeurs: etat.valeurs });
  } catch (err) {
    bouton.disabled = false;
    bouton.textContent = "C'est bon";
    $('#erreur').replaceChildren(`Rien n'est enregistré : ${err.message}`);
    return;
  }
  oublier();
  // Pas d'écran de confirmation : on va droit aux offres (ou au profil), avec un message en passant.
  // Le serveur n'a répondu qu'après avoir relu le fichier écrit : le message dit vrai.
  messageSuivant(r.retriees ? 'C\'est enregistré : tes offres sont retriées selon tes réponses.' : 'C\'est enregistré.');
  location.href = DEPUIS_PROFIL ? '/profil' : '/a-trier';
}

function erreurBloquante(e) {
  afficher(h('h1', { id: 'titre-etape', tabindex: '-1' }, 'Oups.'), h('p', { class: 'erreur' }, e.message || 'Le serveur ne répond pas.'),
    h('div', { class: 'actions' }, h('button', { class: 'bouton principal', type: 'button', onclick: () => location.reload() }, 'Réessayer')));
}

// ======================================================================= démarrage

const plusTard = $('#plus-tard');
if (DEPUIS_PROFIL) {
  plusTard.textContent = 'Revenir à mon profil';
  plusTard.href = '/profil';
}
plusTard.addEventListener('click', () => {
  // « Plus tard » : on ne redemande plus pendant cette visite (cookie de session), le brouillon reste.
  if (!DEPUIS_PROFIL) document.cookie = 'entretien=plus_tard; path=/; samesite=lax';
});

(async () => {
  let d;
  try { d = await api('/api/entretien'); } catch (e) { erreurBloquante(e); return; }
  etat.questions = d.questions;
  if (DEPUIS_PROFIL) oublier();   // relancé depuis Mon profil : on repart de zéro (réponses préremplies par le serveur)
  else reprendre();
  if (etat.index >= etat.questions.length) await recapitulatif();
  else await montrerQuestion(Math.max(0, etat.index));
  if (!reduit()) $('#carte').classList.add('arrivee');
})().catch((e) => { console.error(e); toast('Impossible de charger les questions : le serveur tourne-t-il ?'); });
