// Page À trier : le paquet de cartes, les filtres, les décisions (geste, boutons, clavier), l'annulation,
// la fiche détaillée et le scrap manuel.
import { Glisseur } from './swipe.js';
import { $, h, api, toast, cacherToast, afficherScrap, brancherScrap } from './commun.js';

const SECTIONS = [
  { cle: 'toutes', nom: 'Toutes' },
  { cle: 'Santé', nom: 'Santé' },
  { cle: 'Hors santé mais intéressant', nom: 'Hors santé' },
  { cle: 'À négocier', nom: 'À négocier' },
  { cle: 'plus_tard', nom: 'Plus tard' },
];
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

function dessinerBarre() {
  const zone = $('#sections');
  zone.replaceChildren(...SECTIONS.map(s => h('button', {
    class: 'pastille', type: 'button', 'aria-pressed': String(etat.section === s.cle),
    onclick: () => { etat.section = s.cle; rafraichir(); },
  }, s.nom, ' ', h('small', {}, String(compteSection(s.cle))))));
  $('#tri span').textContent = etat.tri === 'note' ? 'Meilleure note' : 'Plus récentes';
  const nbBof = etat.toutes.filter(o => o.bof && !o.plus_tard).length;
  $('#bof').textContent = `Bof ${nbBof}`;
  $('#bof').setAttribute('aria-pressed', String(etat.bof));
  $('#nb-a-trier').textContent = compteSection('toutes') || '';
}

// ======================================================================= cartes

function contenuCarte(o) {
  const note = o.score === null
    ? h('div', { class: 'note attente', title: "Pas encore notée par l'IA" }, h('small', {}, 'Note'), h('b', {}, '—'))
    : h('div', { class: 'note' }, h('small', {}, 'Note'), h('b', {}, String(o.score), h('span', {}, '/10')));
  const meta = [o.anciennete, o.site].filter(Boolean).join(' · ');
  return [
    h('span', { class: 'tampon oui', 'aria-hidden': 'true' }, 'Je candidate'),
    h('span', { class: 'tampon non', 'aria-hidden': 'true' }, 'Pas pour moi'),
    h('span', { class: 'tampon tard', 'aria-hidden': 'true' }, etat.section === 'plus_tard' ? 'À trier' : 'Plus tard'),
    h('div', { class: 'tete' },
      h('div', { class: 'initiale', 'aria-hidden': 'true' }, o.initiale),
      h('div', { class: 'qui' }, h('b', {}, o.entreprise, o.nouvelle ? h('span', { class: 'etiquette' }, 'Nouvelle') : null),
        h('small', {}, o.lieu)),
      note),
    h('h3', {}, o.titre),
    h('div', { class: 'puces' }, o.puces.map(p => h('span', { class: p.type }, p.texte))),
    o.resume ? h('p', { class: 'resume' }, o.resume) : null,
    o.pourquoi ? h('p', { class: 'pourquoi' }, `Pourquoi ${o.score}/10 : ${o.pourquoi}`) : null,
    h('div', { class: 'pied' },
      o.lien ? h('a', { href: o.lien, target: '_blank', rel: 'noopener' }, "Voir l'annonce ↗") : null,
      h('button', { type: 'button', onclick: () => ouvrirFiche(o.id) }, 'Détails'),
      h('span', { class: 'meta' }, meta)),
  ];
}

function nouvelleCarte(o, pos) {
  return h('article', { class: `carte pos${pos}`, 'data-id': o.id, 'aria-label': `${o.titre}, ${o.entreprise}` },
    contenuCarte(o));
}

// Reconstruit le paquet (après un filtre, un chargement, une annulation).
function rafraichir() {
  dessinerBarre();
  const liste = visibles();
  const pile = $('#pile');
  etat.glisseur?.detruire();
  etat.glisseur = null;
  pile.replaceChildren();
  liste.slice(0, 3).reverse().forEach((o, i, t) => pile.append(nouvelleCarte(o, t.length - 1 - i)));
  activerDessus();
  majCompte();
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

// Pendant le geste : tampon sur la carte, flèche du côté qui grossit, carte suivante qui se rapproche.
function suivreGeste(carte, suivante, dir, force, retour, depart) {
  carte.querySelector('.tampon.oui').style.opacity = dir === 'droite' ? force : 0;
  carte.querySelector('.tampon.non').style.opacity = dir === 'gauche' ? force : 0;
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

// ======================================================================= fiche détaillée

async function ouvrirFiche(id) {
  const fiche = $('#fiche');
  const corps = $('#fiche-corps');
  corps.replaceChildren(h('p', { class: 'texte' }, 'Chargement…'));
  fiche.classList.add('ouverte');
  fiche.setAttribute('aria-hidden', 'false');
  fiche.focus({ preventScroll: true });
  let o;
  try { o = await api(`/api/offres/${id}`); } catch (e) {
    corps.replaceChildren(h('p', { class: 'texte' }, "Impossible de charger l'offre."));
    return;
  }
  const estDessus = Number(carteDessus()?.dataset.id) === id;
  corps.replaceChildren(...[
    h('div', { class: 'tete' }, h('div', { class: 'initiale' }, o.initiale),
      h('div', { class: 'qui' }, h('b', {}, o.entreprise), h('small', {}, o.lieu)),
      o.score === null ? null : h('div', { class: 'note' }, h('small', {}, 'Note'), h('b', {}, String(o.score), h('span', {}, '/10')))),
    h('h2', { id: 'fiche-titre' }, o.titre),
    h('div', { class: 'puces' }, o.puces.map(p => h('span', { class: p.type }, p.texte))),
    estDessus ? h('div', { class: 'fiche-decisions' },
      h('button', { class: 'bouton principal', type: 'button', onclick: () => { fermerFiche(); decider('droite'); } }, 'Je candidate'),
      h('button', { class: 'bouton discret non', type: 'button', onclick: () => { fermerFiche(); decider('gauche'); } }, 'Pas pour moi'),
      h('button', { class: 'bouton discret', type: 'button', onclick: () => { fermerFiche(); decider('haut'); } },
        etat.section === 'plus_tard' ? 'Remettre à trier' : 'Plus tard')) : null,
    o.resume ? [h('h4', {}, 'En bref'), h('p', { class: 'texte' }, o.resume)] : null,
    o.pourquoi ? [h('h4', {}, `Pourquoi ${o.score}/10`), h('p', { class: 'texte' }, o.pourquoi)] : null,
    o.contact ? [h('h4', {}, 'Contact'), h('p', { class: 'texte' }, o.contact)] : null,
    h('h4', {}, o.extrait_seulement ? "Extrait de l'annonce (le site n'en donne pas plus)" : "L'annonce"),
    h('p', { class: 'texte' }, o.description || "Pas de description : ouvre l'annonce sur le site."),
    o.liens.length ? [h('h4', {}, 'Voir sur'), h('div', { class: 'liens' },
      o.liens.map(l => h('a', { class: 'pastille', href: l.lien, target: '_blank', rel: 'noopener' }, `${l.site} ↗`)))] : null,
  ].flat().filter(Boolean));
}

function fermerFiche() {
  const fiche = $('#fiche');
  if (!fiche.classList.contains('ouverte')) return false;
  fiche.classList.remove('ouverte');
  fiche.setAttribute('aria-hidden', 'true');
  return true;
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
  $('#fiche-fermer').addEventListener('click', fermerFiche);
  brancherScrap(apresScrap);
  $('#tri').addEventListener('click', () => { etat.tri = etat.tri === 'note' ? 'recentes' : 'note'; rafraichir(); });
  $('#bof').addEventListener('click', () => { etat.bof = !etat.bof; rafraichir(); });
  let attente = 0;
  $('#recherche').addEventListener('input', (e) => {
    clearTimeout(attente);
    attente = setTimeout(() => { etat.recherche = e.target.value; rafraichir(); }, 160);
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && fermerFiche()) { e.preventDefault(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); annulerDerniere(); return; }
    if (e.target.closest('input, textarea') || e.altKey || e.ctrlKey || e.metaKey) return;
    if ($('#fiche').classList.contains('ouverte')) return;
    const dir = { ArrowRight: 'droite', ArrowLeft: 'gauche', ArrowUp: 'haut' }[e.key];
    if (dir) { e.preventDefault(); decider(dir); }
    else if (e.key === 'Enter' && carteDessus() && !e.target.closest('button, a')) {
      e.preventDefault(); ouvrirFiche(Number(carteDessus().dataset.id));
    }
  });
}

brancher();
charger().catch((e) => { console.error(e); toast('Impossible de charger les offres : le serveur tourne-t-il ?'); });
