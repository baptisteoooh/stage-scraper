// Outils communs aux pages de l'appli : construction d'éléments, appels à l'API, messages (toast),
// et le bouton « Lancer le scrap » du menu.

export const $ = (sel) => document.querySelector(sel);

// Petit constructeur d'éléments : le texte des offres passe toujours par textContent (jamais de HTML).
export function h(tag, attrs = {}, ...enfants) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const e of enfants.flat(Infinity)) if (e !== null && e !== undefined && e !== false) el.append(e);
  return el;
}

export async function api(chemin, corps) {
  const r = await fetch(chemin, corps === undefined ? {} : {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(corps),
  });
  if (!r.ok) {
    let detail = '';
    try { detail = (await r.json()).detail || ''; } catch { /* réponse sans JSON */ }
    const err = new Error(detail || `Erreur ${r.status}`);
    err.status = r.status;
    throw err;
  }
  return r.json();
}

// ======================================================================= compteurs du menu

// Les compteurs existent deux fois (menu de gauche, barre d'onglets du téléphone) : on les met à jour ensemble.
export function setNb(cle, valeur) {
  for (const el of document.querySelectorAll(`[data-nb="${cle}"]`)) el.textContent = valeur ? String(valeur) : '';
}
export function getNb(cle) { return Number(document.querySelector(`[data-nb="${cle}"]`)?.textContent) || 0; }

// Menu « Plus » de la barre du bas : marqué quand on est sur une de ses pages, refermé par un clic ailleurs.
const plus = document.querySelector('.onglets .plus');
if (plus) {
  if (plus.querySelector('a.on')) plus.querySelector('summary').classList.add('on');
  document.addEventListener('click', (e) => { if (plus.open && !plus.contains(e.target)) plus.open = false; });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && plus.open) { plus.open = false; plus.querySelector('summary').focus(); } });
}

// ======================================================================= langue (FR · EN)
export const LANGUE = document.documentElement.lang === 'en' ? 'en' : 'fr';
export const LOCALE = LANGUE === 'en' ? 'en-US' : 'fr-FR';
document.querySelectorAll('[data-langue]').forEach((b) => {
  b.setAttribute('aria-pressed', String(b.dataset.langue === LANGUE));
  b.addEventListener('click', () => {
    if (b.dataset.langue === LANGUE) return;
    document.cookie = `langue=${b.dataset.langue}; path=/; max-age=31536000; samesite=lax`;
    location.reload();
  });
});

// ======================================================================= toast

let minuteur = 0;
export function toast(texte, boutons = [], { raisons = null, duree = 5000 } = {}) {
  const t = $('#toast');
  clearTimeout(minuteur);
  t.classList.toggle('avec-raisons', !!raisons);
  const ligne = h('div', { class: 'ligne-toast' }, h('span', { class: 'texte' }, texte), boutons);
  t.replaceChildren(ligne, raisons || '');
  t.classList.add('visible');
  const programmer = () => { minuteur = setTimeout(cacherToast, duree); };
  t.onmouseenter = () => clearTimeout(minuteur);
  t.onmouseleave = programmer;
  programmer();
}
export function cacherToast() { $('#toast').classList.remove('visible'); }

// ======================================================================= scrap (menu de gauche)

export function afficherScrap(s, ligne) {
  const zone = $('#dernier');
  if (ligne !== undefined) {
    zone.replaceChildren(h('b', {}, 'Scrap en cours…'), 'Quelques minutes : tu peux continuer.',
      ligne ? h('span', { class: 'ligne' }, ligne) : '');
    return;
  }
  zone.replaceChildren(...(s ? [h('b', {}, s.titre), ...s.texte.split(/(?<=\.) (?=\p{Lu})/u).flatMap((p, i) => (i ? [' ', p] : [p]))] : [h('b', {}, 'Aucun scrap pour l\'instant'),
    'Clique sur « Lancer le scrap ».']));
}

// `fini(etat)` est appelé quand le scrap est terminé (etat.erreur s'il a planté).
export function brancherScrap(fini) {
  const bouton = $('#scrap');
  const libelle = bouton.querySelector('span');
  const suivre = async () => {
    let s;
    try { s = await api('/api/scrap'); } catch { setTimeout(suivre, 3000); return; }
    if (s.en_cours) { afficherScrap(null, s.derniere_ligne || ''); setTimeout(suivre, 2000); return; }
    bouton.removeAttribute('aria-busy');
    libelle.textContent = 'Lancer le scrap';
    await fini(s);
  };
  bouton.addEventListener('click', async () => {
    if (bouton.getAttribute('aria-busy') === 'true') return;
    bouton.setAttribute('aria-busy', 'true');
    libelle.textContent = 'Scrap en cours…';
    try { await api('/api/scrap', {}); } catch {
      bouton.removeAttribute('aria-busy'); libelle.textContent = 'Lancer le scrap';
      toast("Le scrap n'a pas pu démarrer."); return;
    }
    afficherScrap(null, '');
    setTimeout(suivre, 1500);
  });
  // Un scrap lancé depuis une autre page continue : on le suit aussi ici.
  api('/api/scrap').then((s) => {
    if (!s.en_cours) return;
    bouton.setAttribute('aria-busy', 'true');
    libelle.textContent = 'Scrap en cours…';
    afficherScrap(null, s.derniere_ligne || '');
    setTimeout(suivre, 2000);
  }).catch(() => {});
}

// ======================================================================= détail d'une offre (fiche de droite)

// Contenu de la fiche d'une offre (réponse de /api/offres/{id}) ; `actions` s'insère sous les puces.
export function detailOffre(o, actions = null) {
  return [
    h('div', { class: 'tete' }, h('div', { class: 'initiale' }, o.initiale),
      h('div', { class: 'qui' }, h('b', {}, o.entreprise), h('small', {}, o.lieu)),
      o.score === null ? null : h('div', { class: 'note' }, h('small', {}, 'Note'), h('b', {}, String(o.score), h('span', {}, '/10')))),
    h('h2', { id: 'fiche-titre' }, o.titre),
    h('div', { class: 'puces' }, o.puces.map(p => h('span', { class: p.type }, p.texte))),
    actions,
    o.exclusion ? [h('h4', {}, "Écartée par l'IA"), h('p', { class: 'texte' }, o.exclusion)] : null,
    o.resume ? [h('h4', {}, 'En bref'), h('p', { class: 'texte', translate: 'no' }, o.resume)] : null,
    o.pourquoi ? [h('h4', {}, `Pourquoi ${o.score}/10`), h('p', { class: 'texte', translate: 'no' }, o.pourquoi)] : null,
    o.contact ? [h('h4', {}, 'Contact'), h('p', { class: 'texte', translate: 'no' }, o.contact)] : null,
    h('h4', {}, o.extrait_seulement ? "Extrait de l'annonce (le site n'en donne pas plus)" : "L'annonce"),
    h('p', { class: 'texte', translate: o.description ? 'no' : null }, o.description || "Pas de description : ouvre l'annonce sur le site."),
    o.liens.length ? [h('h4', {}, 'Voir sur'), h('div', { class: 'liens' },
      o.liens.map(l => h('a', { class: 'pastille', href: l.lien, target: '_blank', rel: 'noopener' }, `${l.site} ↗`)))] : null,
  ].flat().filter(Boolean);
}

// Panneau de droite (#fiche) : ouvrir, fermer (Échap), et rendre le focus à l'élément d'origine.
let origine = null;
export function ouvrirPanneau() {
  const fiche = $('#fiche');
  if (fiche.classList.contains('ouverte')) return;
  origine = document.activeElement;
  fiche.classList.add('ouverte');
  fiche.setAttribute('aria-hidden', 'false');
  fiche.focus({ preventScroll: true });
}
export function fermerPanneau() {
  const fiche = $('#fiche');
  if (!fiche.classList.contains('ouverte')) return false;
  fiche.classList.remove('ouverte');
  fiche.setAttribute('aria-hidden', 'true');
  if (origine?.isConnected) origine.focus({ preventScroll: true });
  origine = null;
  return true;
}

// Compteurs du menu de gauche et dernier scrap (réponse des API de page : a_trier, selection, scrap).
export function majMenu(d) {
  if ('a_trier' in d) setNb('a-trier', d.a_trier);
  if ('selection' in d) setNb('selection', d.selection);
  if ('scrap' in d) afficherScrap(d.scrap);
}

export function montant(dollars, chiffres = 2) {
  const n = dollars.toLocaleString(LOCALE, { minimumFractionDigits: chiffres, maximumFractionDigits: chiffres });
  return LANGUE === 'en' ? `$${n}` : `${n} $`;
}
