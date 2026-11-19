// Assistant : une conversation avec Gemini (gratuit) sur les offres en base. Il propose des offres (lignes
// cliquables : la fiche s'ouvre à droite, avec « Je candidate »), compare, répond sur une annonce ou tes candidatures.
import { $, h, api, toast, cacherToast, brancherScrap, detailOffre, ouvrirPanneau, fermerPanneau, majMenu } from './commun.js';

const EXEMPLES = [
  'Un stage en computer vision sur l\'imagerie médicale',
  'Les offres IA chez les entreprises que je suis',
  'Compare les deux meilleures offres data en santé',
  'Où en sont mes candidatures ?',
];
const ETATS = { selection: 'Dans ma sélection', ecartee: 'Écartée', a_trier: 'À trier' };

const etat = { messages: [], enCours: false, confirmer: false };

function texteRiche(texte) {
  return (texte || '').split(/(\*\*[^*]+\*\*)/g).map(m => (m.startsWith('**') && m.endsWith('**') ? h('b', {}, m.slice(2, -2)) : m));
}

async function charger() {
  const d = await api('/api/assistant');
  majMenu(d.menu);
  etat.messages = d.messages;
  dessiner();
}

function dessiner({ defiler = true } = {}) {
  const fil = $('#fil');
  $('#effacer').hidden = !etat.messages.length;
  if (!etat.messages.length) {
    fil.replaceChildren(h('div', { class: 'accueil-chat' },
      h('h2', {}, 'Que cherches-tu ?'),
      h('p', {}, "Je connais toutes tes offres et tes candidatures. Demande-moi d'en trouver, d'en comparer, "
        + "ou ce qu'il faut savoir sur l'une d'elles : je lis les annonces en entier avant de répondre."),
      h('div', { class: 'exemples' }, EXEMPLES.map(e => h('button', {
        class: 'pastille', type: 'button', onclick: () => envoyer(e),
      }, e)))));
    return;
  }
  fil.replaceChildren(...etat.messages.flatMap(message));
  if (defiler) fil.scrollTop = fil.scrollHeight;
}

function message(m) {
  const bulle = h('div', { class: `bulle ${m.role === 'user' ? 'moi' : 'ia'}` },
    m.lues?.length ? h('small', { class: 'lu' }, `Lu : ${m.lues.join(' · ')}`) : null,
    h('p', {}, texteRiche(m.texte)));
  if (!m.offres?.length) return [bulle];
  return [bulle, h('div', { class: 'propositions' }, m.offres.map(proposition))];
}

function proposition(o) {
  return h('button', { class: 'proposition', type: 'button', 'data-id': o.id, onclick: () => ouvrirOffre(o) },
    h('span', { class: 'initiale', 'aria-hidden': 'true' }, o.initiale),
    h('span', {}, h('b', {}, o.titre), h('span', { class: 'ou' }, [o.entreprise, o.lieu].filter(Boolean).join(' · ')),
      o.raison ? h('span', { class: 'raison' }, o.raison) : null),
    h('span', { class: 'droite' },
      o.score === null ? null : h('span', { class: 'sur10' }, String(o.score), h('small', {}, '/10')),
      h('span', { class: `etat ${o.etat}` }, ETATS[o.etat])));
}

// ======================================================================= envoyer une question

async function envoyer(texte) {
  const question = (texte ?? $('#question').value).trim();
  if (!question || etat.enCours) return;
  etat.enCours = true;
  etat.confirmer = false;
  $('#effacer').textContent = 'Nouvelle conversation';
  $('#question').value = '';
  $('#envoyer').disabled = true;
  const fil = $('#fil');
  fil.querySelector('.accueil-chat')?.remove();
  fil.querySelector('.erreur-fil')?.remove();
  fil.append(h('div', { class: 'bulle moi' }, h('p', {}, question)),
    h('div', { class: 'bulle ia ecrit', 'aria-label': "L'assistant réfléchit" }, h('i'), h('i'), h('i')));
  fil.scrollTo({ top: fil.scrollHeight, behavior: 'smooth' });
  try {
    const d = await api('/api/assistant', { question });
    etat.messages = d.messages;
    dessiner({ defiler: false });
    // on montre le début de la réponse (pas la fin des offres proposées)
    const reponses = fil.querySelectorAll('.bulle.moi');
    reponses[reponses.length - 1]?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  } catch (e) {
    fil.querySelector('.ecrit')?.remove();
    fil.lastElementChild?.remove();   // la question non gardée : elle revient dans le champ
    fil.append(h('p', { class: 'erreur-fil' }, e.message));
    if (!etat.messages.length && !fil.querySelector('.bulle')) dessinerErreurSeule(e.message);
    $('#question').value = question;
  } finally {
    etat.enCours = false;
    $('#envoyer').disabled = false;
    $('#question').focus();
  }
}

function dessinerErreurSeule(texte) {
  dessiner();
  $('#fil').append(h('p', { class: 'erreur-fil' }, texte));
}

// ======================================================================= fiche d'une offre proposée

async function ouvrirOffre(resume) {
  const corps = $('#fiche-corps');
  corps.replaceChildren(h('p', { class: 'texte' }, 'Chargement…'));
  ouvrirPanneau();
  let o;
  try { o = await api(`/api/offres/${resume.id}`); } catch (e) {
    corps.replaceChildren(h('p', { class: 'texte' }, e.message)); return;
  }
  corps.replaceChildren(...detailOffre(o, actions(resume)));
  corps.scrollTop = 0;
}

function actions(o) {
  if (o.etat === 'selection') {
    return h('div', { class: 'fiche-decisions' },
      h('a', { class: 'bouton principal', href: `/selection?fiche=${o.candidature_id}` }, 'Ouvrir dans Ma sélection'));
  }
  if (o.etat === 'ecartee') {
    return h('div', { class: 'fiche-decisions' },
      h('button', { class: 'bouton', type: 'button', onclick: () => decider(o, 'remettre') }, 'Remettre à trier'));
  }
  return h('div', { class: 'fiche-decisions' },
    h('button', { class: 'bouton principal', type: 'button', onclick: () => decider(o, 'candidate') }, 'Je candidate'),
    h('button', { class: 'bouton non', type: 'button', onclick: () => decider(o, 'ecarte') }, 'Pas pour moi'));
}

const APRES = { candidate: 'ajoutée à Ma sélection', ecarte: 'écartée', remettre: 'remise à trier' };

async function decider(o, action) {
  let decision;
  try {
    if (action === 'remettre') {   // une offre écartée revient de la corbeille ; l'annulation l'y renvoie
      await api('/api/corbeille/remettre', { offre_id: o.id, liste: 'toi' });
      decision = { action: 'ecarte', offre_id: o.id, refaire: true };
    } else {
      decision = await api('/api/decision', { offre_id: o.id, action });
    }
  } catch (e) { toast(e.message); return; }
  fermerPanneau();
  const avant = { etat: o.etat, candidature_id: o.candidature_id };
  majEtat(o.id, action === 'candidate' ? 'selection' : action === 'ecarte' ? 'ecartee' : 'a_trier', decision.candidature_id ?? null);
  const boutons = [h('button', {
    class: 'pastille', type: 'button',
    onclick: async () => {
      cacherToast();
      try {
        if (decision.refaire) await api('/api/decision', { offre_id: o.id, action: 'ecarte' });
        else await api('/api/annuler', decision);
      } catch { toast("Impossible d'annuler pour l'instant."); return; }
      majEtat(o.id, avant.etat, avant.candidature_id);
      toast('Annulé.');
      majCompteurs();
    },
  }, 'Annuler')];
  if (action === 'candidate' && decision.candidature_id) {
    boutons.unshift(h('a', { class: 'pastille', href: `/selection?fiche=${decision.candidature_id}&dossier=1` }, 'Préparer'));
  }
  toast(`« ${o.titre} » ${APRES[action]}.`, boutons, { duree: 7000 });
  majCompteurs();
}

// L'état d'une offre change partout où l'assistant l'a proposée.
function majEtat(id, nouvel, candidatureId) {
  for (const m of etat.messages) {
    for (const o of m.offres || []) if (o.id === id) Object.assign(o, { etat: nouvel, candidature_id: candidatureId });
  }
  const fil = $('#fil'), haut = fil.scrollTop;
  dessiner({ defiler: false });
  fil.scrollTop = haut;
}

async function majCompteurs() {
  try { majMenu((await api('/api/assistant')).menu); } catch { /* sans gravité */ }
}

// ======================================================================= branchements

$('#saisie').addEventListener('submit', (e) => { e.preventDefault(); envoyer(); });
$('#question').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); envoyer(); }
});
$('#effacer').addEventListener('click', async () => {
  if (!etat.confirmer) {
    etat.confirmer = true;
    $('#effacer').textContent = 'Effacer la conversation ?';
    setTimeout(() => { etat.confirmer = false; $('#effacer').textContent = 'Nouvelle conversation'; }, 4000);
    return;
  }
  etat.confirmer = false;
  $('#effacer').textContent = 'Nouvelle conversation';
  try { await api('/api/assistant/effacer', {}); } catch (e) { toast(e.message); return; }
  etat.messages = [];
  dessiner();
  $('#question').focus();
});
$('#fiche-fermer').addEventListener('click', fermerPanneau);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') fermerPanneau(); });
brancherScrap(() => majCompteurs());

charger().catch((e) => { console.error(e); toast("Impossible de charger l'assistant : le serveur tourne-t-il ?"); });
