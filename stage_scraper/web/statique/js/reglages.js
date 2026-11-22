// Page Réglages : les mails (récap et alertes). Ils s'enregistrent d'un seul bouton.
// Le CV et la lettre modèle sont dans « Mon profil » ; le tri se refait tout seul quand le profil change.
import { $, h, api, toast, brancherScrap, majMenu, compteCourant } from './commun.js';

// Les critères et les entreprises suivies sont dans « Mon profil » (/profil).
// Site partagé : BAP a aussi « Comptes » (inviter, supprimer) ; un ami a « Mon compte » (les mails partent de la
// boîte Gmail de BAP : pas pour lui).
let ONGLETS = [{ cle: 'mails', nom: 'Mails' }];

const etat = { onglet: 'mails', d: null, initial: null, courant: null, compte: { mode: false } };

const copie = (x) => JSON.parse(JSON.stringify(x));

// Ce qui s'enregistre dans config.yaml (le reste de la réponse ne fait qu'informer)
function modifiables(d) {
  return { alerte_seuil_score: d.mails.alerte_seuil_score, envoi_actif: d.mails.envoi_actif };
}

async function charger() {
  etat.compte = await compteCourant;
  if (etat.compte.mode) {
    ONGLETS = etat.compte.admin
      ? [{ cle: 'mails', nom: 'Mails' }, { cle: 'comptes', nom: 'Comptes' }, { cle: 'moncompte', nom: 'Mon compte' }]
      : [{ cle: 'moncompte', nom: 'Mon compte' }];
    if (!ONGLETS.some(o => o.cle === etat.onglet)) etat.onglet = ONGLETS[0].cle;
  }
  const d = await api('/api/reglages');
  majMenu(d);
  etat.d = d;
  etat.initial = modifiables(d);
  etat.courant = copie(etat.initial);
  const demande = location.hash.slice(1);
  if (demande === 'criteres' || demande === 'entreprises') { location.replace('/profil'); return; }
  if (demande === 'documents') { location.replace('/profil#documents'); return; }
  if (ONGLETS.some(o => o.cle === demande)) etat.onglet = demande;
  dessiner();
}

function modifie() { return JSON.stringify(etat.courant) !== JSON.stringify(etat.initial); }

function majBarre() {
  const barre = $('#a-enregistrer');
  const oui = modifie();
  barre.classList.toggle('visible', oui);
  barre.setAttribute('aria-hidden', String(!oui));
}

function changer(cle, valeur) { etat.courant[cle] = valeur; majBarre(); }

// ======================================================================= onglets

function dessiner() {
  $('#onglets').hidden = ONGLETS.length < 2;
  $('#onglets').replaceChildren(...ONGLETS.map(o => h('button', {
    class: 'pastille', type: 'button', role: 'tab', 'aria-selected': String(o.cle === etat.onglet),
    'aria-pressed': String(o.cle === etat.onglet),
    onclick: () => { etat.onglet = o.cle; history.replaceState(null, '', `#${o.cle}`); dessiner(); },
  }, o.nom)));
  const contenu = { mails, comptes: rubriqueComptes, moncompte: monCompte }[etat.onglet]();
  const zone = $('#reglages');
  zone.replaceChildren(h('div', { class: 'rubrique apparait' }, contenu));
  zone.scrollTop = 0;
  majBarre();
}

function bloc(titre, aide, ...contenu) {
  return h('section', { class: 'bloc' }, h('h2', {}, titre), aide ? h('p', { class: 'aide-liste' }, aide) : null, contenu);
}

// ======================================================================= mails

function mails() {
  const m = etat.d.mails;
  const seuil = h('input', { class: 'champ court', type: 'number', min: '0', max: '10', value: etat.courant.alerte_seuil_score });
  seuil.addEventListener('input', () => changer('alerte_seuil_score', Number(seuil.value)));
  const interrupteur = h('button', {
    class: 'interrupteur', type: 'button', role: 'switch', 'aria-checked': String(etat.courant.envoi_actif),
    onclick: () => {
      const v = !etat.courant.envoi_actif;
      changer('envoi_actif', v);
      interrupteur.setAttribute('aria-checked', String(v));
      etatEnvoi.textContent = v ? 'Les mails partent vraiment (après enregistrement).' : 'Aperçus seulement : rien ne part.';
    },
  }, h('i'));
  const etatEnvoi = h('span', {}, etat.courant.envoi_actif ? 'Les mails partent vraiment.' : 'Aperçus seulement : rien ne part.');
  const apercu = h('div', { class: 'apercu' });
  const montrer = async (type) => {
    apercu.replaceChildren(h('p', { class: 'aide-liste' }, 'Chargement…'));
    let a;
    try { a = await api(`/api/reglages/apercu/${type}`); } catch (e) { apercu.replaceChildren(h('p', {}, e.message)); return; }
    if (!a.html) { apercu.replaceChildren(h('p', { class: 'aide-liste' }, 'Rien en attente pour ce mail.')); return; }
    // Le mail s'affiche dans un cadre isolé (sandbox) : son HTML ne peut rien faire sur la page.
    apercu.replaceChildren(h('p', { class: 'sujet' }, h('b', {}, 'Sujet : '), a.sujet),
      h('iframe', { class: 'cadre-mail', sandbox: '', srcdoc: a.html, title: `Aperçu du mail : ${a.sujet}` }));
  };
  return [
    bloc('Alerte immédiate', 'Un mail à part, à chaque scrap, pour une offre notée au moins ce seuil (ou un poste IA/data chez une entreprise suivie).',
      h('label', { class: 'ligne-champ' }, seuil, h('span', {}, 'sur 10'))),
    bloc('Envoi', `Destinataire : ${m.destinataire || 'GMAIL_ADRESSE manquant dans .env'}.`,
      h('div', { class: 'ligne-champ' }, interrupteur, etatEnvoi)),
    bloc('En attente', `${m.en_attente.alerte} offre(s) pour l'alerte immédiate, ${m.en_attente.recap} pour le récap du matin `
      + '(offres déjà notées par l\'IA et jamais envoyées).',
    h('div', { class: 'boutons-ligne' },
      h('button', { class: 'pastille', type: 'button', disabled: !m.en_attente.alerte, onclick: () => montrer('alerte') }, "Aperçu de l'alerte"),
      h('button', { class: 'pastille', type: 'button', disabled: !m.en_attente.recap, onclick: () => montrer('recap') }, 'Aperçu du récap'),
      h('button', {
        class: 'pastille', type: 'button', disabled: !m.pret,
        title: m.pret ? `Envoie un petit mail à ${m.destinataire}` : 'Adresse ou mot de passe d\'application manquant dans .env',
        onclick: async (e) => {
          const b = e.currentTarget; b.disabled = true;
          try { await api('/api/reglages/mail-test', {}); toast(`Mail de test envoyé à ${m.destinataire}.`); } catch (err) { toast(err.message); }
          b.disabled = false;
        },
      }, 'Envoyer un mail de test')),
    apercu),
  ];
}

// ======================================================================= site partagé

function rubriqueComptes() {
  const lien = h('div', { class: 'lien-invitation' });
  const liste = h('ul', { class: 'liste-comptes' });
  const dessinerListe = (comptes) => liste.replaceChildren(...comptes.map(c => h('li', {},
    h('b', { translate: 'no' }, c.nom), h('span', {}, c.admin ? 'toi (compte principal)' : `depuis le ${c.cree_le.slice(8, 10)}/${c.cree_le.slice(5, 7)}`),
    c.admin ? null : h('button', { class: 'lien', type: 'button', onclick: () => supprimer(c.nom) }, 'Supprimer'))));
  const supprimer = (nom) => toast(`Supprimer le compte de ${nom} ? Ses offres, sa sélection, son CV et sa clé seront effacés.`, [
    h('button', { type: 'button', onclick: async () => {
      try { dessinerListe((await api('/api/compte/supprimer', { nom })).comptes); toast(`Compte de ${nom} supprimé.`); } catch (e) { toast(e.message); }
    } }, 'Supprimer')], { duree: 9000 });
  dessinerListe(etat.compte.comptes || []);
  return [
    bloc('Inviter quelqu\'un', "Crée un lien et envoie-le : la personne choisit son nom et son mot de passe. Le lien ne sert qu'une fois "
      + 'et dure 7 jours. Elle reçoit les offres que tu collectes et les note avec sa propre clé Gemini (ton quota reste à toi).',
    h('button', { class: 'pastille', type: 'button', onclick: async () => {
      try {
        const r = await api('/api/compte/inviter', {});
        const champ = h('input', { class: 'champ', type: 'text', readonly: true, value: r.lien, 'aria-label': "Lien d'invitation" });
        lien.replaceChildren(champ, h('button', { class: 'pastille', type: 'button', onclick: async () => {
          try { await navigator.clipboard.writeText(r.lien); toast('Lien copié.'); } catch { champ.select(); toast('Sélectionné : fais Ctrl+C.'); }
        } }, 'Copier'));
      } catch (e) { toast(e.message); }
    } }, 'Créer un lien d\'invitation'), lien),
    bloc('Comptes', null, liste),
  ];
}

function monCompte() {
  const ancien = h('input', { class: 'champ', type: 'password', autocomplete: 'current-password', placeholder: 'Mot de passe actuel' });
  const nouveau = h('input', { class: 'champ', type: 'password', autocomplete: 'new-password', placeholder: 'Nouveau mot de passe (8 caractères ou plus)' });
  return [
    bloc('Connecté en tant que', null, h('p', { class: 'nom-compte', translate: 'no' }, etat.compte.nom)),
    bloc('Changer de mot de passe', null, h('form', { class: 'pile-champs', onsubmit: async (e) => {
      e.preventDefault();
      try { await api('/api/compte/mot-de-passe', { ancien: ancien.value, nouveau: nouveau.value }); toast('Mot de passe changé.'); ancien.value = nouveau.value = ''; } catch (err) { toast(err.message); }
    } }, ancien, nouveau, h('button', { class: 'pastille', type: 'submit' }, 'Changer'))),
    etat.compte.admin ? null : bloc('Mails', 'Le récap du matin et les alertes ne sont pas encore disponibles pour ton compte : regarde « À trier ».'),
  ];
}

// ======================================================================= enregistrer

async function enregistrer() {
  const modifs = {};
  for (const [cle, v] of Object.entries(etat.courant)) {
    if (JSON.stringify(v) !== JSON.stringify(etat.initial[cle])) modifs[cle] = v;
  }
  let r;
  try { r = await api('/api/reglages', modifs); } catch (e) { toast(`Pas enregistré : ${e.message}`); return; }
  await charger();
  if (!r.changements.length) { toast('Aucun changement.'); return; }
  toast(`Enregistré : ${r.changements.join(', ')}.`, [], { duree: 7000 });
}

$('#enregistrer').addEventListener('click', enregistrer);
$('#defaire').addEventListener('click', () => { etat.courant = copie(etat.initial); dessiner(); });
window.addEventListener('beforeunload', (e) => { if (etat.courant && modifie()) e.preventDefault(); });
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); if (modifie()) enregistrer(); }
});
brancherScrap(async (s) => { toast(s.erreur ? `Le scrap a planté : ${s.erreur}` : 'Scrap terminé.'); api('/api/reglages').then(majMenu); });
charger().catch((e) => { console.error(e); toast('Impossible de charger les réglages : le serveur tourne-t-il ?'); });
