// Page Réglages : critères (ce qui est gardé ou écarté), entreprises suivies, mails, documents (CV, lettre
// modèle) et « refaire le tri ». Les critères et les mails s'enregistrent dans config.yaml d'un seul bouton.
import { $, h, api, toast, brancherScrap, majMenu } from './commun.js';

const ONGLETS = [
  { cle: 'criteres', nom: 'Critères' },
  { cle: 'entreprises', nom: 'Entreprises suivies' },
  { cle: 'mails', nom: 'Mails' },
  { cle: 'documents', nom: 'Mes documents' },
  { cle: 'avance', nom: 'Avancé' },
];

const etat = { onglet: 'criteres', d: null, initial: null, courant: null };

const copie = (x) => JSON.parse(JSON.stringify(x));

// Ce qui s'enregistre dans config.yaml (le reste de la réponse ne fait qu'informer)
function modifiables(d) {
  return { ...d.criteres, alerte_seuil_score: d.mails.alerte_seuil_score, envoi_actif: d.mails.envoi_actif };
}

async function charger() {
  const d = await api('/api/reglages');
  majMenu(d);
  etat.d = d;
  etat.initial = modifiables(d);
  etat.courant = copie(etat.initial);
  const demande = location.hash.slice(1);
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
  $('#onglets').replaceChildren(...ONGLETS.map(o => h('button', {
    class: 'pastille', type: 'button', role: 'tab', 'aria-selected': String(o.cle === etat.onglet),
    'aria-pressed': String(o.cle === etat.onglet),
    onclick: () => { etat.onglet = o.cle; history.replaceState(null, '', `#${o.cle}`); dessiner(); },
  }, o.nom)));
  const contenu = { criteres, entreprises, mails, documents, avance }[etat.onglet]();
  const zone = $('#reglages');
  zone.replaceChildren(h('div', { class: 'rubrique apparait' }, contenu));
  zone.scrollTop = 0;
  majBarre();
}

function bloc(titre, aide, ...contenu) {
  return h('section', { class: 'bloc' }, h('h2', {}, titre), aide ? h('p', { class: 'aide-liste' }, aide) : null, contenu);
}

// Liste de mots-clés modifiable : une pastille par mot, × pour retirer, Entrée pour ajouter.
function listeMots(cle, placeholder) {
  const mots = h('div', { class: 'mots' });
  const champ = h('input', { class: 'champ ajout', type: 'text', placeholder, 'aria-label': placeholder });
  const dessinerMots = () => mots.replaceChildren(...etat.courant[cle].map((m, i) => h('span', { class: 'mot', translate: 'no' }, m,
    h('button', {
      type: 'button', 'aria-label': `Retirer ${m}`,
      onclick: () => { changer(cle, etat.courant[cle].filter((_, j) => j !== i)); dessinerMots(); },
    }, '×'))), champ);
  champ.addEventListener('keydown', (e) => {
    if (e.key === 'Backspace' && !champ.value && etat.courant[cle].length) {
      changer(cle, etat.courant[cle].slice(0, -1)); dessinerMots(); champ.focus(); return;
    }
    if (e.key !== 'Enter' && e.key !== ',') return;
    e.preventDefault();
    const v = champ.value.trim();
    if (v && !etat.courant[cle].some(x => x.toLowerCase() === v.toLowerCase())) {
      changer(cle, [...etat.courant[cle], v]); dessinerMots();
    }
    champ.value = ''; champ.focus();
  });
  dessinerMots();
  return mots;
}

function criteres() {
  const anciennete = h('input', { class: 'champ court', type: 'number', min: '1', max: '365', value: etat.courant.anciennete_max_jours });
  anciennete.addEventListener('input', () => changer('anciennete_max_jours', Number(anciennete.value)));
  return [
    h('p', { class: 'aide-liste' }, "Ce que l'outil garde ou écarte. Enregistré dans config.yaml (l'ancienne version reste dans config.yaml.bak). "
      + "Pour l'appliquer aux offres déjà collectées : Avancé › Refaire le tri."),
    bloc('Ancienneté maximale', "Une offre publiée il y a plus longtemps est rangée dans « Expirées ».",
      h('label', { class: 'ligne-champ' }, anciennete, h('span', {}, 'jours'))),
    bloc('Types de contrat exclus', 'Un mot ou une expression par pastille. Entrée pour ajouter.', listeMots('contrats', 'Ajouter un type de contrat')),
    bloc('Postes exclus', 'Cherchés dans le titre de l\'offre.', listeMots('postes', 'Ajouter un poste')),
    bloc('Niveaux trop élevés', 'Cherchés dans le titre de l\'offre.', listeMots('niveaux', 'Ajouter un niveau')),
  ];
}

// ======================================================================= entreprises suivies

function entreprises() {
  const lignes = h('div', { class: 'entreprises' });
  const options = (dict, valeur) => Object.entries(dict).map(([v, nom]) => h('option', { value: v, selected: v === valeur }, nom));
  const dessinerLignes = () => lignes.replaceChildren(
    h('div', { class: 'entreprise entete', 'aria-hidden': 'true' },
      h('span', {}, 'Nom'), h('span', {}, 'Groupe'), h('span', {}, 'Autres noms'), h('span', {}, 'Outil carrières'),
      h('span', {}, 'Adresse ou identifiant'), h('span', {})),
    ...etat.courant.entreprises_suivies.map((e, i) => {
      const maj = (champ) => (ev) => {
        const liste = copie(etat.courant.entreprises_suivies);
        liste[i][champ] = ev.target.value;
        changer('entreprises_suivies', liste);
      };
      return h('div', { class: 'entreprise' },
        h('input', { class: 'champ', value: e.nom, 'aria-label': 'Nom', oninput: maj('nom') }),
        h('select', { class: 'champ', 'aria-label': 'Groupe', onchange: maj('groupe') }, options(etat.d.groupes, e.groupe)),
        h('input', { class: 'champ', value: e.alias, placeholder: 'séparés par des virgules', 'aria-label': 'Autres noms', oninput: maj('alias') }),
        h('select', { class: 'champ', 'aria-label': 'Outil carrières', onchange: maj('outil') }, options(etat.d.outils, e.outil)),
        h('input', { class: 'champ', value: e.adresse_ou_id, 'aria-label': 'Adresse ou identifiant', oninput: maj('adresse_ou_id') }),
        h('button', {
          class: 'retirer-ligne', type: 'button', 'aria-label': `Retirer ${e.nom || 'cette entreprise'}`,
          onclick: () => { changer('entreprises_suivies', etat.courant.entreprises_suivies.filter((_, j) => j !== i)); dessinerLignes(); },
        }, '×'));
    }));
  dessinerLignes();
  return [
    h('p', { class: 'aide-liste' }, "Leurs offres ont un bonus dans la note, et une offre de 6 mois chez elles va dans « À négocier ». "
      + "Outil carrières : Ashby (avec l'identifiant de la page) ou Workday (avec l'adresse complète) ; laisser « Aucun » si inconnu."),
    lignes,
    h('button', {
      class: 'pastille ajouter', type: 'button',
      onclick: () => {
        changer('entreprises_suivies', [...etat.courant.entreprises_suivies, { nom: '', groupe: 'scale_up', alias: '', outil: '', adresse_ou_id: '' }]);
        dessiner();
        const champs = document.querySelectorAll('.entreprise:last-child input');
        champs[0]?.focus();
      },
    }, '+ Ajouter une entreprise'),
  ];
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

// ======================================================================= documents

function documents() {
  const doc = etat.d.documents;
  const carteDoc = (nom, titre, present, accepte, aide) => {
    const entree = h('input', { type: 'file', accept: accepte, class: 'sr-only' });
    const texte = h('div', { class: 'texte-ia' });
    const zone = h('label', { class: `depot${present ? ' present' : ''}` }, entree,
      h('b', {}, titre), h('span', {}, present ? 'Présent · clique ou dépose un fichier pour le remplacer' : aide));
    const deposer = async (fichier) => {
      if (!fichier) return;
      zone.classList.add('envoi');
      try {
        const r = await fetch(`/api/reglages/documents/${nom}?fichier=${encodeURIComponent(fichier.name)}`, { method: 'POST', body: fichier });
        if (!r.ok) throw new Error((await r.json()).detail || `Erreur ${r.status}`);
        toast(`${titre} enregistré${nom === 'cv' ? '' : 'e'}.`);
        await charger();
      } catch (e) { toast(e.message); }
      zone.classList.remove('envoi');
    };
    entree.addEventListener('change', () => deposer(entree.files[0]));
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('survol'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('survol'));
    zone.addEventListener('drop', (e) => { e.preventDefault(); zone.classList.remove('survol'); deposer(e.dataTransfer.files[0]); });
    const voir = present ? h('details', { class: 'voir-ia', ontoggle: async (e) => {
      if (!e.target.open || texte.childElementCount) return;
      const t = await api(`/api/reglages/documents/${nom}`).catch(() => ({ texte: null }));
      texte.replaceChildren(h('pre', {}, t.texte || 'Texte illisible.'));
    } }, h('summary', {}, "Ce que l'IA reçoit (anonymisé)"), texte) : null;
    return h('div', { class: 'document' }, zone, voir);
  };
  return [
    h('p', { class: 'aide-liste' }, "Ton CV et une lettre que tu as écrite (modèle de style). Ils restent sur ton ordinateur, dans profil/ "
      + "(ignoré par Git). Les IA ne reçoivent que leur texte, sans ton nom ni tes coordonnées."),
    doc.nom_masque ? null : h('p', { class: 'alerte' }, "Ton nom n'a pas été reconnu en tête du CV : vérifie dans le texte ci-dessous qu'il n'apparaît pas."),
    h('div', { class: 'documents' },
      carteDoc('cv', 'CV', doc.cv, 'application/pdf,.pdf', 'Dépose ton CV en PDF, ou clique pour le choisir'),
      carteDoc('modele', 'Lettre modèle', doc.modele, '.txt,.docx', 'Facultatif : une lettre à toi (.txt ou .docx)')),
  ];
}

// ======================================================================= avancé

function avance() {
  const resultat = h('p', { class: 'aide-liste', 'aria-live': 'polite' });
  return [
    bloc('Refaire le tri', 'Applique les critères actuels (pré-filtre et doublons) à toutes les offres déjà collectées. '
      + "Les notes de l'IA déjà obtenues sont gardées.",
    h('button', {
      class: 'bouton discret', type: 'button',
      onclick: async (e) => {
        const b = e.currentTarget; b.disabled = true; b.textContent = 'Tri en cours…';
        try { resultat.textContent = (await api('/api/reglages/retrier', {})).texte; } catch (err) { resultat.textContent = err.message; }
        b.disabled = false; b.textContent = 'Refaire le tri de toutes les offres';
        api('/api/reglages').then(majMenu).catch(() => {});
      },
    }, 'Refaire le tri de toutes les offres'), resultat),
    bloc('Autres paramètres', "Les domaines (et leur ordre de priorité), les secteurs, les sources et les modèles d'IA se règlent dans "
      + 'le fichier config.yaml, à la racine du projet.'),
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
  const critere = ['contrats', 'postes', 'niveaux', 'anciennete_max_jours', 'entreprises_suivies'].some(c => c in modifs);
  if (!r.changements.length) { toast('Aucun changement.'); return; }
  toast(`Enregistré : ${r.changements.join(', ')}.`, critere ? [h('button', {
    type: 'button', onclick: () => { etat.onglet = 'avance'; dessiner(); },
  }, 'Refaire le tri')] : [], { duree: 7000 });
}

$('#enregistrer').addEventListener('click', enregistrer);
$('#defaire').addEventListener('click', () => { etat.courant = copie(etat.initial); dessiner(); });
window.addEventListener('beforeunload', (e) => { if (etat.courant && modifie()) e.preventDefault(); });
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); if (modifie()) enregistrer(); }
});
brancherScrap(async (s) => { toast(s.erreur ? `Le scrap a planté : ${s.erreur}` : 'Scrap terminé.'); api('/api/reglages').then(majMenu); });
charger().catch((e) => { console.error(e); toast('Impossible de charger les réglages : le serveur tourne-t-il ?'); });
