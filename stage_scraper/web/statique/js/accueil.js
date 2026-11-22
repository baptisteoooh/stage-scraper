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

// ======================================================================= connexion
// Version locale : le formulaire mène directement à l'appli. Site partagé (--comptes) : vrai nom + mot de passe,
// création du premier compte (celui de BAP), ou d'un compte d'ami avec un lien d'invitation (?invitation=…).
const formulaire = document.querySelector('#connexion');
let compte = { mode: false };

function champ(id, type, texte, autocomplete) {
  const label = el('label', 'sr-only', texte);
  label.htmlFor = id;
  const input = el('input', 'champ');
  Object.assign(input, { id, type, placeholder: texte, autocomplete, required: true });
  return [label, input];
}

function formulaireComptes() {
  const invitation = new URLSearchParams(location.search).get('invitation');
  const creer = compte.premier || compte.invitation === true;
  const bouton = el('button', 'bouton principal', creer ? 'Créer mon compte' : 'Se connecter');
  bouton.type = 'submit';
  const bas = document.querySelector('#bas-connexion');
  bas.textContent = compte.premier
    ? 'Premier passage : ce compte est le tien. Lui seul collecte les offres, et tu pourras inviter des amis.'
    : compte.invitation === true ? 'Tu es invité : choisis un nom et un mot de passe (8 caractères ou plus).'
      : compte.invitation === false ? "Ce lien d'invitation n'est plus valable : demande-en un nouveau. Tu as déjà un compte ? Connecte-toi."
        : 'Pas de compte ? Demande un lien d\'invitation à la personne qui a installé le site.';
  formulaire.replaceChildren(
    ...champ('nom', 'text', 'Nom', 'username'),
    ...champ('mot-de-passe', 'password', 'Mot de passe', creer ? 'new-password' : 'current-password'),
    bouton, document.querySelector('#erreur-connexion'), bas);
  formulaire.onsubmit = async (e) => {
    e.preventDefault();
    const erreur = document.querySelector('#erreur-connexion');
    erreur.textContent = '';
    bouton.disabled = true;
    const corps = { nom: formulaire.querySelector('#nom').value, mot_de_passe: formulaire.querySelector('#mot-de-passe').value, code: invitation };
    try {
      const r = await fetch(creer ? '/api/compte/inscription' : '/api/compte/connexion', {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(corps) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Erreur ${r.status}`);
      location.href = '/a-trier';
    } catch (err) {
      erreur.textContent = err.message;
      bouton.disabled = false;
    }
  };
}

formulaire.addEventListener('submit', (e) => {
  if (compte.mode) return;   // géré par formulaireComptes
  e.preventDefault();
  location.href = '/a-trier';
});

(async () => {
  try {
    const invitation = new URLSearchParams(location.search).get('invitation');
    compte = await (await fetch(`/api/compte${invitation ? `?invitation=${encodeURIComponent(invitation)}` : ''}`)).json();
  } catch { return; }
  if (!compte.mode) return;
  if (compte.connecte) { location.replace('/a-trier'); return; }
  formulaireComptes();
})();
