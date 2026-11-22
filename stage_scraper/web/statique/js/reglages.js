// Page Réglages : les mails (récap et alertes). Ils s'enregistrent d'un seul bouton.
// Le CV et la lettre modèle sont dans « Mon profil » ; le tri se refait tout seul quand le profil change.
import { $, h, api, toast, brancherScrap, majMenu } from './commun.js';

// Les critères et les entreprises suivies sont dans « Mon profil » (/profil).
const ONGLETS = [{ cle: 'mails', nom: 'Mails' }];

const etat = { onglet: 'mails', d: null, initial: null, courant: null };

const copie = (x) => JSON.parse(JSON.stringify(x));

// Ce qui s'enregistre dans config.yaml (le reste de la réponse ne fait qu'informer)
function modifiables(d) {
  return { alerte_seuil_score: d.mails.alerte_seuil_score, envoi_actif: d.mails.envoi_actif };
}

async function charger() {
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
  const contenu = { mails }[etat.onglet]();
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
