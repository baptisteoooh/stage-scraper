// Page Ma sélection : les offres gardées depuis À trier, rangées par étape (En préparation → Envoyées →
// Entretien → Terminées), leur fiche de suivi (étape, dates, notes) et les offres trouvées ailleurs.
import { $, h, api, toast, afficherScrap, brancherScrap } from './commun.js';
import { ouvrirDossier, fermerDossier, dossierOuvert } from './dossier.js';

const etat = {
  fiches: [],
  etapes: [],
  etape: null,       // étape affichée
  ouverte: null,     // id de la fiche ouverte (candidature)
};

// ======================================================================= chargement

async function charger() {
  const d = await api('/api/selection');
  etat.fiches = d.fiches;
  etat.etapes = d.etapes;
  $('#nb-a-trier').textContent = d.a_trier || '';
  $('#nb-selection').textContent = d.fiches.length || '';
  afficherScrap(d.scrap);
  if (!etat.etape) {
    // On ouvre sur la première étape où il y a quelque chose à faire, sinon « En préparation ».
    const urgente = d.fiches.find(f => f.action);
    etat.etape = new URLSearchParams(location.search).get('etape') || urgente?.etape || 'preparation';
  }
  dessiner();
}

// Change l'affichage en douceur (transition de vue quand le navigateur sait la faire).
function transition(changer) {
  if (!document.startViewTransition || matchMedia('(prefers-reduced-motion: reduce)').matches) { changer(); return; }
  document.startViewTransition(changer);
}

// ======================================================================= barre des étapes

function dessinerEtapes() {
  $('#etapes').replaceChildren(...etat.etapes.map(({ cle, nom }) => {
    const liste = etat.fiches.filter(f => f.etape === cle);
    const aFaire = liste.filter(f => f.action).length;
    return h('button', {
      class: 'pastille', type: 'button', 'aria-pressed': String(cle === etat.etape),
      title: aFaire ? `${aFaire} à faire` : null,
      onclick: () => { if (cle !== etat.etape) { etat.etape = cle; memoriser(); transition(dessiner); } },
    }, nom, h('small', {}, String(liste.length)), aFaire ? h('span', { class: 'point', 'aria-label': `${aFaire} à faire` }) : null);
  }));
}

// ======================================================================= grille

function carte(f, i) {
  const urgent = f.action === 'relancer';
  const agir = f.bouton ? h('button', {
    class: 'agir', type: 'button',
    onclick: (e) => { e.stopPropagation(); agirSur(f); },
  }, f.bouton) : h('span', { class: 'ouvrir' }, 'Ouvrir →');
  return h('article', {
    class: 'dossier', tabindex: '0', role: 'button', 'data-id': f.id, style: `--i:${i};view-transition-name:d${f.id}`,
    'aria-label': `${f.entreprise} : ${f.titre}`,
    onclick: () => ouvrirFiche(f.id),
    onkeydown: (e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) { e.preventDefault(); ouvrirFiche(f.id); } },
  },
  h('div', { class: 'tete' }, h('div', { class: 'initiale' }, f.initiale),
    h('div', { class: 'qui' }, h('b', {}, f.entreprise), h('small', {}, f.lieu || (f.trouvee_ailleurs ? 'Trouvée ailleurs' : ''))),
    f.score === null ? null : h('div', { class: 'note' }, h('b', {}, String(f.score), h('span', {}, '/10')))),
  h('h3', {}, f.titre),
  h('p', { class: 'situation' }, f.situation),
  h('div', { class: 'bas' },
    // Le badge ne sert que pour ce qui presse (relance, entretien) : « préparer » est le cas normal de l'étape.
    urgent || f.action === 'entretien' ? h('span', { class: `a-faire${urgent ? ' urgent' : ''}` }, urgent ? 'Relance à faire' : 'Entretien à préparer')
      : f.trouvee_ailleurs ? h('span', { class: 'ailleurs' }, 'Trouvée ailleurs') : null,
    agir));
}

function messageRien() {
  const total = etat.fiches.length;
  if (!total) {
    return h('div', { class: 'rien' }, h('h3', {}, 'Rien dans ta sélection'),
      h('p', {}, 'Dans À trier, glisse une offre à droite : elle arrive ici, à l\'étape « En préparation ».'),
      h('a', { class: 'bouton principal', href: '/a-trier' }, 'Aller trier'));
  }
  const textes = {
    preparation: 'Aucune candidature en préparation. Les offres gardées dans À trier arrivent ici.',
    envoyee: 'Aucune candidature envoyée pour l\'instant. Quand une lettre part, dis-le dans sa fiche : « C\'est envoyé ».',
    entretien: 'Pas d\'entretien prévu. Quand on te propose un entretien, note la date dans la fiche.',
    terminee: 'Rien de terminé : pas encore de réponse définitive.',
  };
  return h('div', { class: 'rien' }, h('p', {}, textes[etat.etape] || 'Rien à cette étape.'));
}

function dessiner() {
  dessinerEtapes();
  const liste = etat.fiches.filter(f => f.etape === etat.etape);
  const aFaire = liste.filter(f => f.action).length;
  $('#compte').textContent = liste.length
    ? `${liste.length} offre${liste.length > 1 ? 's' : ''}${aFaire ? ` · ${aFaire} à faire` : ''}` : '';
  $('#dossiers').replaceChildren(...(liste.length ? liste.map(carte) : [messageRien()]));
}

function memoriser() {
  const p = new URLSearchParams();
  if (etat.etape && etat.etape !== 'preparation') p.set('etape', etat.etape);
  if (etat.ouverte) p.set('fiche', etat.ouverte);
  if (etat.ouverte && etat.dossier) p.set('dossier', '1');
  history.replaceState(null, '', `${location.pathname}${p.size ? `?${p}` : ''}`);
}

// ======================================================================= actions (avec annulation)

function proposerAnnulation(texte, jeton) {
  const boutons = jeton ? [h('button', {
    type: 'button',
    onclick: async () => {
      try { await api('/api/selection/annuler', { jeton }); } catch (e) { toast(e.message); return; }
      await recharger();
      toast('Annulé.');
    },
  }, 'Annuler')] : [];
  toast(texte, boutons, { duree: 6000 });
}

// Recharge la liste ; la fiche ouverte est redessinée si elle existe encore.
async function recharger({ suivre = false } = {}) {
  const avant = new Map(etat.fiches.map(f => [f.id, f.etape]));
  const d = await api('/api/selection');
  // Une fiche qui quitte l'étape affichée s'efface avant que la grille se resserre.
  const partantes = d.fiches.filter(f => avant.get(f.id) === etat.etape && f.etape !== etat.etape)
    .concat([...avant.keys()].filter(id => !d.fiches.some(f => f.id === id)).map(id => ({ id })));
  for (const f of partantes) document.querySelector(`.dossier[data-id="${f.id}"]`)?.classList.add('part');
  if (partantes.length) await new Promise(r => setTimeout(r, 260));
  etat.fiches = d.fiches;
  $('#nb-a-trier').textContent = d.a_trier || '';
  $('#nb-selection').textContent = d.fiches.length || '';
  const ouverte = etat.fiches.find(f => f.id === etat.ouverte);
  if (suivre && ouverte) etat.etape = ouverte.etape;
  transition(dessiner);
  if (etat.ouverte) {
    if (ouverte) ouvrirFiche(etat.ouverte, { garderDefilement: true }); else fermerFiche();
  }
  memoriser();
}

async function changerEtape(f, etape, resultat) {
  let r;
  try { r = await api(`/api/selection/${f.id}/etape`, resultat ? { etape, resultat } : { etape }); }
  catch (e) { toast(e.message); return; }
  const nom = etat.etapes.find(x => x.cle === etape)?.nom || etape;
  await recharger();
  proposerAnnulation(etape === 'terminee' ? `${f.entreprise} : ${resultat === 'accepté' ? 'accepté !' : 'refus noté.'}`
    : `${f.entreprise} : rangée dans « ${nom} ».`, r.jeton);
}

async function noterRelance(f) {
  let r;
  try { r = await api(`/api/selection/${f.id}/relance`, {}); } catch (e) { toast(e.message); return; }
  await recharger();
  proposerAnnulation(`${f.entreprise} : relance notée, prochain rappel dans quelques jours.`, r.jeton);
}

function agirSur(f) {
  if (f.action === 'relancer') noterRelance(f);
  else ouvrirFiche(f.id, { dossier: true });   // préparer, finir la lettre, préparer l'entretien
}

// Le dossier de candidature (lettre, conseils, analyse, conversation), dans le panneau élargi.
function versDossier(f) {
  etat.dossier = true;
  memoriser();
  ouvrirDossier(f, {
    retour: () => { etat.dossier = false; ouvrirFiche(f.id); },
    envoyee: () => { etat.dossier = false; changerEtape(f, 'envoyee'); },
  });
}

// ======================================================================= fiche de suivi

function ouvrirPanneau() {
  const fiche = $('#fiche');
  if (!fiche.classList.contains('ouverte')) {
    fiche.classList.add('ouverte');
    fiche.setAttribute('aria-hidden', 'false');
    fiche.focus({ preventScroll: true });
  }
}

function fermerFiche() {
  const fiche = $('#fiche');
  if (!fiche.classList.contains('ouverte')) return false;
  fiche.classList.remove('ouverte');
  fiche.setAttribute('aria-hidden', 'true');
  fermerDossier();
  const id = etat.ouverte;
  etat.ouverte = null;
  etat.dossier = false;
  memoriser();
  document.querySelector(`.dossier[data-id="${id}"]`)?.focus({ preventScroll: true });
  return true;
}

// Champ gardé tout seul : à la sortie du champ (et après une pause de frappe pour les textes longs).
function champGarde(f, cle, el, temoin) {
  let valeur = el.value, attente = 0;
  const garder = async () => {
    clearTimeout(attente);
    if (el.value === valeur) return;
    valeur = el.value;
    try {
      await api(`/api/selection/${f.id}/dates`, { [cle]: el.value || null });
      temoin.classList.add('visible');
      setTimeout(() => temoin.classList.remove('visible'), 1600);
      if (cle !== 'notes' && cle !== 'annonce') recharger();
    } catch (e) { toast(`Pas gardé : ${e.message}`); }
  };
  el.addEventListener('change', garder);
  el.addEventListener('blur', garder);
  if (el.tagName === 'TEXTAREA') el.addEventListener('input', () => { clearTimeout(attente); attente = setTimeout(garder, 900); });
}

async function ouvrirFiche(id, { garderDefilement = false, dossier = false } = {}) {
  if (dossierOuvert()) {
    if (garderDefilement && etat.ouverte === id) return;   // rechargement de la liste : le dossier reste affiché
    fermerDossier();
  }
  const corps = $('#fiche-corps');
  const defilement = corps.scrollTop;
  if (!garderDefilement) corps.replaceChildren(h('p', { class: 'texte' }, 'Chargement…'));
  etat.ouverte = id;
  memoriser();
  ouvrirPanneau();
  let f;
  try { f = await api(`/api/selection/${id}`); } catch (e) {
    corps.replaceChildren(h('p', { class: 'texte' }, e.message));
    return;
  }
  if (etat.ouverte !== id) return;   // une autre fiche a été ouverte entre-temps

  const temoin = () => h('span', { class: 'garde', 'aria-live': 'polite' }, 'Gardé');
  const etapes = h('div', { class: 'etapes-fiche', role: 'group', 'aria-label': 'Étape' },
    Object.entries({ preparation: 'En préparation', envoyee: 'Envoyée', entretien: 'Entretien', terminee: 'Terminée' })
      .map(([cle, nom]) => h('button', {
        class: 'pastille', type: 'button', 'aria-pressed': String(cle === f.etape),
        onclick: () => { if (cle !== f.etape) changerEtape(f, cle); },
      }, nom)));
  const resultat = f.etape === 'terminee' ? [h('h4', {}, 'Résultat'), h('div', { class: 'etapes-fiche' },
    [['refus', 'Refus'], ['accepté', 'Accepté']].map(([cle, nom]) => h('button', {
      class: 'pastille', type: 'button', 'aria-pressed': String(f.statut === cle),
      onclick: () => { if (f.statut !== cle) changerEtape(f, 'terminee', cle); },
    }, nom)))] : null;

  const boutons = h('div', { class: 'boutons-fiche' },
    f.etape === 'preparation' ? h('button', {
      class: 'bouton principal', type: 'button', title: `Range l'offre dans « Envoyées » et prévoit une relance dans ${f.relance_jours} jours`,
      onclick: () => changerEtape(f, 'envoyee'),
    }, "C'est envoyé") : null,
    f.relance_due ? h('button', { class: 'bouton principal', type: 'button', onclick: () => noterRelance(f) }, "J'ai relancé") : null,
    f.lien ? h('a', { class: 'bouton discret', href: f.lien, target: '_blank', rel: 'noopener' }, "Voir l'annonce ↗") : null);

  // Dates (et entretien), gardées toutes seules
  const tEnvoi = temoin(), tRelance = temoin(), tEntretien = temoin(), tNotes = temoin(), tAnnonce = temoin();
  const envoi = h('input', { class: 'champ', type: 'date', value: f.date_candidature });
  const relance = h('input', { class: 'champ', type: 'date', value: f.date_relance });
  const entretien = h('input', { class: 'champ', type: 'datetime-local', value: (f.date_entretien || '').replace(' ', 'T').slice(0, 16) });
  const notes = h('textarea', { class: 'champ', placeholder: 'Contact, référence, impressions…', rows: '5' });
  notes.value = f.notes;
  champGarde(f, 'date_candidature', envoi, tEnvoi);
  champGarde(f, 'date_relance', relance, tRelance);
  champGarde(f, 'notes', notes, tNotes);
  // L'entretien s'écrit « AAAA-MM-JJ HH:MM » en base
  entretien.addEventListener('change', async () => {
    const v = entretien.value ? entretien.value.replace('T', ' ') : null;
    try {
      await api(`/api/selection/${f.id}/dates`, { date_entretien: v });
      tEntretien.classList.add('visible');
      await recharger({ suivre: true });
    } catch (e) { toast(`Pas gardé : ${e.message}`); }
  });

  let annonce = null;
  if (f.trouvee_ailleurs) {
    const zone = h('textarea', { class: 'champ', placeholder: "Colle ici le texte de l'annonce : l'IA en a besoin pour l'analyse et la lettre.", rows: '8' });
    zone.value = f.description || '';
    champGarde(f, 'annonce', zone, tAnnonce);
    annonce = [h('h4', {}, "Texte de l'annonce", tAnnonce), zone];
  }

  $('#fiche-corps').replaceChildren(...[
    h('div', { class: 'tete' }, h('div', { class: 'initiale' }, f.initiale),
      h('div', { class: 'qui' }, h('b', {}, f.entreprise), h('small', {}, f.lieu || '')),
      f.score === null ? null : h('div', { class: 'note' }, h('small', {}, 'Note'), h('b', {}, String(f.score), h('span', {}, '/10')))),
    h('h2', { id: 'fiche-titre' }, f.titre),
    f.puces.length ? h('div', { class: 'puces' }, f.puces.map(p => h('span', { class: p.type }, p.texte))) : null,
    h('h4', {}, 'Où en est-elle ?'), etapes, resultat,
    h('p', { class: 'situation-fiche' }, f.situation),
    boutons,
    h('h4', {}, 'Dates'),
    h('div', { class: 'dates' },
      h('label', {}, h('span', {}, 'Envoyée le', tEnvoi), envoi),
      h('label', {}, h('span', {}, 'Relancer le', tRelance), relance),
      f.etape === 'entretien' || f.date_entretien ? h('label', {}, h('span', {}, 'Entretien', tEntretien), entretien) : null),
    h('h4', {}, 'Notes', tNotes), notes,
    annonce,
    h('div', { class: 'encart lien-dossier' },
      h('div', {}, h('b', {}, 'Dossier de candidature'),
        h('span', {}, f.lettre ? 'Lettre, conseils CV, analyse de l\'offre et conversation avec l\'IA.'
          : f.analyse_faite ? 'Analyse faite. La lettre et la conversation avec l\'IA sont dans le dossier.'
            : 'L\'IA analyse l\'offre face à ton CV, conseille ton CV et rédige la lettre avec toi.')),
      h('button', { class: 'bouton principal', type: 'button', onclick: () => versDossier(f) },
        f.analyse_faite || f.lettre ? 'Ouvrir le dossier' : 'Préparer')),
    f.lettre ? h('details', {}, h('summary', {}, f.etape === 'preparation' ? 'Lettre en cours' : 'Lettre envoyée'), h('p', { class: 'texte' }, f.lettre)) : null,
    !f.trouvee_ailleurs && (f.resume || f.description) ? h('details', {}, h('summary', {}, "L'offre"),
      f.resume ? h('p', { class: 'texte' }, f.resume) : null,
      f.pourquoi ? h('p', { class: 'texte', style: 'color:var(--doux)' }, `Pourquoi ${f.score}/10 : ${f.pourquoi}`) : null,
      f.description ? h('p', { class: 'texte' }, f.description) : null) : null,
    h('button', {
      class: 'retirer', type: 'button',
      title: f.trouvee_ailleurs ? "L'offre est supprimée ; l'analyse et la lettre sont gardées." : "L'offre retourne dans À trier ; l'analyse et la lettre sont gardées.",
      onclick: () => retirer(f),
    }, 'Retirer de ma sélection'),
  ].flat().filter(Boolean));
  if (garderDefilement) corps.scrollTop = defilement;
  if (dossier) versDossier(f);
}

async function retirer(f) {
  let r;
  try { r = await api(`/api/selection/${f.id}/retirer`, {}); } catch (e) { toast(e.message); return; }
  fermerFiche();
  await recharger();
  proposerAnnulation(`${f.entreprise} retirée de ta sélection${f.trouvee_ailleurs ? '' : ' (de retour dans À trier)'}.`, r.jeton);
}

// ======================================================================= offre trouvée ailleurs

function ouvrirNouvelle() {
  etat.ouverte = null;
  memoriser();
  const champ = (nom, attrs = {}) => h('input', { class: 'champ', name: nom, ...attrs });
  const deja = h('input', { type: 'checkbox', name: 'deja' });
  const quand = champ('envoyee', { type: 'date', value: new Date().toISOString().slice(0, 10) });
  const ligneDate = h('label', { hidden: true }, 'Envoyée le', quand);
  deja.addEventListener('change', () => { ligneDate.hidden = !deja.checked; });
  const erreur = h('p', { class: 'erreur', role: 'alert' });
  const annonce = h('textarea', { class: 'champ', name: 'annonce', rows: '6', placeholder: "Colle le texte de l'annonce : l'IA pourra l'analyser et écrire la lettre." });
  const form = h('form', {
    class: 'formulaire',
    onsubmit: async (e) => {
      e.preventDefault();
      const v = Object.fromEntries(new FormData(form));
      erreur.textContent = '';
      let r;
      try {
        r = await api('/api/selection/nouvelle', {
          entreprise: v.entreprise || '', poste: v.poste || '', lien: v.lien || '', lieu: v.lieu || '',
          annonce: v.annonce || '', envoyee: deja.checked ? (v.envoyee || null) : null,
        });
      } catch (err) { erreur.textContent = err.message; return; }
      etat.ouverte = r.id;
      await recharger({ suivre: true });
      toast('Ajoutée à ta sélection.');
    },
  },
  h('div', { class: 'deux' },
    h('label', {}, 'Entreprise', champ('entreprise', { autocomplete: 'organization' })),
    h('label', {}, 'Poste', champ('poste'))),
  h('div', { class: 'deux' },
    h('label', {}, "Lien de l'annonce (facultatif)", champ('lien', { type: 'url', placeholder: 'https://…' })),
    h('label', {}, 'Lieu (facultatif)', champ('lieu'))),
  h('label', {}, "Texte de l'annonce (facultatif)", annonce),
  h('label', { class: 'case' }, deja, 'Candidature déjà envoyée'),
  ligneDate,
  erreur,
  h('button', { class: 'bouton principal', type: 'submit' }, 'Ajouter à Ma sélection'));

  $('#fiche-corps').replaceChildren(
    h('h2', { id: 'fiche-titre' }, 'Offre trouvée ailleurs'),
    h('p', { class: 'texte', style: 'color:var(--doux)' }, "Une offre vue hors de l'outil : elle aura sa fiche comme les autres."),
    form);
  ouvrirPanneau();
  setTimeout(() => form.querySelector('input').focus(), 80);
}

// ======================================================================= branchements

$('#fiche-fermer').addEventListener('click', fermerFiche);
$('#nouvelle').addEventListener('click', ouvrirNouvelle);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && fermerFiche()) e.preventDefault(); });
brancherScrap(async (s) => {
  const d = await api('/api/selection');
  afficherScrap(d.scrap);
  $('#nb-a-trier').textContent = d.a_trier || '';
  toast(s.erreur ? `Le scrap a planté : ${s.erreur}` : 'Scrap terminé : les nouvelles offres sont dans À trier.');
});

charger().then(() => {
  const id = Number(new URLSearchParams(location.search).get('fiche'));
  if (id && etat.fiches.some(f => f.id === id)) ouvrirFiche(id, { dossier: new URLSearchParams(location.search).has('dossier') });
}).catch((e) => { console.error(e); toast('Impossible de charger ta sélection : le serveur tourne-t-il ?'); });
