// Accueil : une carte d'exemple qu'on peut vraiment glisser (offres inventées), pour comprendre le geste.
import { Glisseur } from './swipe.js';
import './commun.js';   // sélecteur FR · EN

const EXEMPLES = [
  { entreprise: 'Aurore Santé', lieu: 'Paris 11e · Hybride', note: 9, titre: "Stage Data Scientist, détection d'anomalies sur ECG",
    puces: ['IA / data', '5 mois', 'Avril 2027'], texte: 'Tu entraînes des modèles qui repèrent les troubles du rythme cardiaque sur des électrocardiogrammes.' },
  { entreprise: 'Nervia Labs', lieu: 'Paris 13e · Hybride', note: 8, titre: 'Stage Machine Learning, imagerie IRM',
    puces: ['IA / data', '4 à 6 mois', 'Avril 2027'], texte: 'Tu améliores la segmentation automatique de lésions sur des IRM cérébrales.' },
  { entreprise: 'Cardiolink', lieu: 'Boulogne-Billancourt', note: 7, titre: 'Stage Data Analyst, essais cliniques',
    puces: ['Data', '5 mois', 'Mai 2027'], texte: 'Tu construis les tableaux de suivi des patients inclus dans les essais.' },
];

const pile = document.querySelector('#demo');
let rang = 0;
let glisseur = null;
let premiere = true;   // seule la toute première carte penche au repos

function el(tag, classe, texte) {
  const e = document.createElement(tag);
  if (classe) e.className = classe;
  if (texte !== undefined) e.textContent = texte;
  return e;
}

function carte(o, pos) {
  const c = el('article', `carte pos${pos}`);
  c.setAttribute('aria-label', `Exemple : ${o.titre}`);
  const oui = el('span', 'tampon oui', 'Intéressé');
  const non = el('span', 'tampon non', 'Pas intéressé');
  const tard = el('span', 'tampon tard', 'Plus tard');
  const tete = el('div', 'tete');
  const qui = el('div', 'qui');
  qui.append(el('b', '', o.entreprise), el('small', '', o.lieu));
  const note = el('div', 'note');
  const b = el('b', '', String(o.note));
  b.append(el('span', '', '/10'));
  note.append(el('small', '', 'Note'), b);
  tete.append(el('div', 'initiale', o.entreprise[0]), qui, note);
  const puces = el('div', 'puces');
  o.puces.forEach((p, i) => puces.append(el('span', i === 0 ? 'ia' : '', p)));
  c.append(oui, non, tard, tete, el('h3', '', o.titre), puces, el('p', 'resume', o.texte), el('span', 'exemple', "Offre d'exemple"));
  return c;
}

function remplir() {
  pile.replaceChildren();
  for (let i = 2; i >= 0; i--) pile.append(carte(EXEMPLES[(rang + i) % EXEMPLES.length], i));
  const dessus = pile.querySelector('.pos0');
  if (premiere) dessus.classList.add('repos');
  premiere = false;
  const suivante = pile.querySelector('.pos1');
  glisseur = new Glisseur(dessus, {
    haut: true,
    auBouger: ({ dir, force, retour, depart }) => {
      dessus.classList.remove('repos');
      dessus.querySelector('.oui').style.opacity = dir === 'droite' ? force : 0;
      dessus.querySelector('.non').style.opacity = dir === 'gauche' ? force : 0;
      dessus.querySelector('.tard').style.opacity = dir === 'haut' ? force : 0;
      if (retour) { suivante.style.transition = ''; suivante.style.transform = ''; return; }
      if (depart) { suivante.style.transition = ''; suivante.style.transform = 'none'; suivante.style.setProperty('--revele', 1); return; }
      suivante.style.transition = 'none';
      suivante.style.transform = `translateY(${14 * (1 - force)}px) scale(${.955 + .045 * force})`;
      suivante.style.setProperty('--revele', force);
    },
    auLacher: async (dir, fin) => {
      await fin;
      glisseur.detruire();
      rang = (rang + 1) % EXEMPLES.length;
      remplir();
    },
  });
}

remplir();

// Le formulaire mène à l'appli (pas encore de vrais comptes : version locale).
document.querySelector('#connexion').addEventListener('submit', (e) => {
  e.preventDefault();
  location.href = '/a-trier';
});
