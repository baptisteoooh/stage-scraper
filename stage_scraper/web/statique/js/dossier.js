// Dossier de candidature d'une offre (dans le panneau de Ma sélection, en grand) : la lettre (versions,
// modifications gardées toutes seules, Word), les conseils CV, l'analyse face au CV, et la conversation avec l'IA.
// L'IA ne s'appuie que sur le CV (anonymisé) et l'offre. Chaque appel payant affiche son prix avant.
import { $, h, api, toast } from './commun.js';

const ACTIONS_CONSEIL = { reformuler: 'Reformuler', deplacer: 'Déplacer', retirer: 'Retirer', ajouter: 'Mettre en avant' };
const COUVERTURE = { couverte: ['✓', 'oui'], partielle: ['~', 'moyen'], absente: ['✕', 'non'] };
const ATTENTES = [
  [0, "J'analyse l'offre face à ton CV…"],
  [9000, 'Je relève les exigences et je cherche les preuves dans ton CV…'],
  [20000, 'Je rédige un premier jet de lettre…'],
  [45000, 'Encore un instant…'],
];

let ctx = null;   // { f, d, onglet, zoneLettre, sauvegarde, envoi }

// **gras** du texte de l'IA, sans jamais interpréter de HTML
function texteRiche(texte) {
  return (texte || '').split(/(\*\*[^*]+\*\*)/g).map(m => (m.startsWith('**') && m.endsWith('**') ? h('b', {}, m.slice(2, -2)) : m));
}

function mots(texte) { return (texte.trim().match(/\S+/g) || []).length; }

export async function ouvrirDossier(f, { retour, envoyee }) {
  ctx = { f, d: null, onglet: null, retour, envoyee, sauvegarde: 0, enCours: false };
  const panneau = $('#fiche');
  panneau.classList.add('large');
  const corps = $('#fiche-corps');
  corps.replaceChildren(h('p', { class: 'texte' }, 'Chargement du dossier…'));
  try { ctx.d = await api(`/api/selection/${f.id}/dossier`); } catch (e) {
    corps.replaceChildren(h('p', { class: 'texte' }, e.message)); return;
  }
  ctx.onglet = ctx.d.lettre ? 'lettre' : ctx.d.diagnostic ? 'conseils' : 'lettre';
  dessiner();
}

export function fermerDossier() {
  if (!ctx) return;
  garderLettre();
  $('#fiche').classList.remove('large');
  ctx = null;
}

export function dossierOuvert() { return !!ctx; }

// ======================================================================= dessin

function dessiner() {
  const { f, d } = ctx;
  const entete = h('div', { class: 'dossier-tete' },
    h('button', { class: 'pastille', type: 'button', onclick: () => { const r = ctx.retour; fermerDossier(); r(); } },
      h('span', { 'aria-hidden': 'true' }, '←'), 'Fiche'),
    h('div', { class: 'dossier-titre' }, h('b', {}, f.entreprise), h('span', {}, f.titre)),
    d.etape === 'preparation' && d.lettre ? h('button', {
      class: 'bouton principal petit', type: 'button', title: 'Range l\'offre dans « Envoyées » et prévoit une relance',
      onclick: () => { garderLettre(); ctx.envoyee(); },
    }, "C'est envoyé") : null,
    h('button', { class: 'fermer-dossier', type: 'button', 'aria-label': 'Fermer', title: 'Fermer (Échap)', onclick: () => $('#fiche-fermer').click() }, '×'));

  // Sans CV : la lettre et l'analyse déjà faites restent visibles ; seul ce qui demande l'IA attend le CV,
  // qu'on dépose ici même (pas de détour par une autre page).
  if (!d.cv_present && !d.lettre && !d.diagnostic) {
    $('#fiche-corps').replaceChildren(entete, h('div', { class: 'preparer apparait' },
      h('h2', {}, 'Dépose ton CV pour préparer'),
      h('p', {}, "L'IA analyse l'offre et écrit la lettre à partir de ton CV et de l'offre seulement. Ton CV reste sur "
        + "ton ordinateur : l'IA n'en reçoit que le texte, sans ton nom ni tes coordonnées."),
      depotCv()));
    return;
  }

  const manqueAnalyse = !d.diagnostic;
  const manqueLettre = d.etape === 'preparation' && !d.lettre;
  if (manqueAnalyse || (manqueLettre && !d.messages.length)) {
    $('#fiche-corps').replaceChildren(entete, panneauPreparer(manqueAnalyse, manqueLettre));
    return;
  }

  const onglets = [['lettre', 'Lettre'], ['conseils', 'Conseils CV'], ['analyse', "Analyse de l'offre"]];
  const gauche = h('div', { class: 'dossier-gauche' },
    h('div', { class: 'onglets-dossier', role: 'tablist' }, onglets.map(([cle, nom]) => h('button', {
      class: 'pastille', type: 'button', role: 'tab', 'aria-selected': String(cle === ctx.onglet), 'aria-pressed': String(cle === ctx.onglet),
      onclick: () => { garderLettre(); ctx.onglet = cle; dessiner(); },
    }, nom))),
    d.claude_en_pause ? h('p', { class: 'note-ia' }, `Claude en pause (${d.claude_en_pause}) : Gemini, gratuit, prend le relais.`) : null,
    h('div', { class: 'onglet-dossier apparait' }, { lettre: ongletLettre, conseils: ongletConseils, analyse: ongletAnalyse }[ctx.onglet]()));
  const droite = d.cv_present ? conversation() : h('div', { class: 'dossier-droite sans-cv' },
    h('p', { class: 'aide-liste' }, "Pour parler à l'IA (retoucher la lettre, poser une question), dépose d'abord ton CV."), depotCv());
  $('#fiche-corps').replaceChildren(entete, h('div', { class: 'dossier-corps' }, gauche, droite));
  const fil = document.querySelector('.fil');
  if (fil) fil.scrollTop = fil.scrollHeight;
}

// Zone de dépôt du CV (PDF), cliquable ou glisser-déposer. Une fois déposé, le dossier se redessine avec l'IA.
function depotCv() {
  const entree = h('input', { type: 'file', accept: 'application/pdf,.pdf', class: 'sr-only' });
  const zone = h('label', { class: 'depot' }, entree, h('b', {}, 'Mon CV (PDF)'), h('span', {}, 'Clique ou dépose le fichier ici'));
  const deposer = async (fichier) => {
    if (!fichier) return;
    zone.classList.add('envoi');
    try {
      const r = await fetch(`/api/reglages/documents/cv?fichier=${encodeURIComponent(fichier.name)}`, { method: 'POST', body: fichier });
      if (!r.ok) throw new Error((await r.json()).detail || `Erreur ${r.status}`);
      toast('CV enregistré.');
      ctx.d = await api(`/api/selection/${ctx.f.id}/dossier`);
      dessiner();
    } catch (e) { toast(e.message); zone.classList.remove('envoi'); }
  };
  entree.addEventListener('change', () => deposer(entree.files[0]));
  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('survol'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('survol'));
  zone.addEventListener('drop', (e) => { e.preventDefault(); zone.classList.remove('survol'); deposer(e.dataTransfer.files[0]); });
  return zone;
}

function panneauPreparer(manqueAnalyse, manqueLettre) {
  const d = ctx.d;
  const prix = [manqueAnalyse ? d.prix.analyse : null, manqueLettre ? d.prix.premier_jet : null].filter(Boolean);
  const gratuit = prix.every(p => p.startsWith('gratuit'));
  const total = gratuit ? 'gratuit, Gemini' : `≈ ${prix.reduce((s, p) => s + (parseFloat(p.replace(/[^\d,]/g, '').replace(',', '.')) || 0), 0)} c`;
  const quoi = [manqueAnalyse ? "analyse l'offre face à ton CV" : null, manqueLettre ? 'rédige un premier jet de lettre' : null].filter(Boolean).join(' et ');
  const statut = h('p', { class: 'statut-ia', 'aria-live': 'polite' });
  const bouton = h('button', {
    class: 'bouton principal', type: 'button',
    onclick: async () => {
      bouton.disabled = true; bouton.classList.add('attente');
      const debut = performance.now();
      const etapes = manqueAnalyse ? ATTENTES : [[0, 'Je rédige un premier jet de lettre…'], [25000, 'Encore un instant…']];
      const minuteurs = etapes.map(([t, texte]) => setTimeout(() => { statut.textContent = texte; }, t));
      try {
        ctx.d = await api(`/api/selection/${ctx.f.id}/dossier/preparer`, { analyse: true, lettre: manqueLettre });
        ctx.onglet = ctx.d.lettre ? 'lettre' : 'analyse';
        minuteurs.forEach(clearTimeout);
        dessiner();
        toast(`Dossier prêt en ${Math.round((performance.now() - debut) / 1000)} s.`);
      } catch (e) {
        minuteurs.forEach(clearTimeout);
        statut.textContent = e.message;
        bouton.disabled = false; bouton.classList.remove('attente');
      }
    },
  }, `Préparer avec l'IA (${total})`);
  return h('div', { class: 'preparer apparait' },
    h('h2', {}, manqueAnalyse ? 'Préparer la candidature' : 'Écrire la lettre'),
    h('p', {}, `L'IA ${quoi}, à partir de ton CV et de l'offre seulement.`, ' ',
      (manqueLettre ? 'Ensuite, tu ajustes la lettre en lui parlant (une retouche ≈ 0,1 c).' : 'Tu pourras ensuite lui poser tes questions.')),
    d.claude_en_pause ? h('p', { class: 'note-ia' }, `Claude en pause (${d.claude_en_pause}) : Gemini, gratuit, prend le relais.`) : null,
    bouton, statut);
}

// ======================================================================= lettre

function ongletLettre() {
  const L = ctx.d.lettre;
  if (!L) {
    return h('p', { class: 'aide-liste' }, ctx.d.etape === 'preparation'
      ? (ctx.d.cv_present ? 'Pas encore de lettre : demande-la dans la conversation (« rédige la lettre »).' : 'Pas encore de lettre.')
      : "Pas de lettre pour cette candidature. Tu peux préparer l'entretien en parlant à l'IA, à droite.");
  }
  const zone = h('textarea', { class: 'champ lettre', spellcheck: 'true', 'aria-label': 'Lettre de motivation' });
  zone.value = L.texte;
  ctx.zoneLettre = zone;
  const compte = h('span', {}, `${mots(L.texte)} mots`);
  const etatGarde = h('span', { class: 'garde' }, 'Gardé');
  const quelle = h('span', {}, `Version ${L.numero}/${L.total} · écrite par ${L.auteur} · `);
  ctx.majMeta = (n) => { quelle.textContent = `Version ${n.numero}/${n.total} · écrite par ${n.auteur} · `; };
  zone.addEventListener('input', () => {
    compte.textContent = `${mots(zone.value)} mots`;
    clearTimeout(ctx.sauvegarde);
    ctx.sauvegarde = setTimeout(() => garderLettre(etatGarde), 1200);
  });
  zone.addEventListener('blur', () => garderLettre(etatGarde));
  const historique = ctx.d.versions.length > 1 ? h('details', { class: 'versions' },
    h('summary', {}, `Historique (${ctx.d.versions.length} versions)`),
    ctx.d.versions.map(v => h('div', { class: 'version' },
      h('b', {}, `v${v.numero}`), h('span', {}, `${v.date} · ${v.auteur}`), h('em', {}, v.demande),
      v.numero === L.numero ? h('small', {}, 'affichée') : h('button', {
        class: 'pastille', type: 'button', onclick: () => choisirVersion(v.numero),
      }, 'Reprendre')))) : null;
  return [
    h('p', { class: 'meta-lettre' }, quelle, compte, ' (250 à 350 conseillés)', etatGarde),
    L.figee ? h('p', { class: 'note-ia' }, 'Candidature envoyée : la lettre gardée dans ta candidature ne change plus, même si tu modifies celle-ci.') : null,
    zone,
    L.alertes.length ? h('div', { class: 'alerte' }, h('b', {}, 'Non retrouvé dans ton CV'), ' (à vérifier ou à retirer) :',
      h('ul', { translate: 'no' }, L.alertes.map(a => h('li', {}, a)))) : null,
    h('div', { class: 'boutons-ligne' },
      h('button', { class: 'pastille', type: 'button', disabled: L.numero <= 1, onclick: () => choisirVersion(L.numero - 1) }, 'Version précédente'),
      lienTelechargement('docx', 'Télécharger (Word)'), lienTelechargement('txt', 'Texte')),
    h('p', { class: 'aide-liste' }, '[Prénom Nom] est remplacé par ton nom dans les fichiers téléchargés (sur ton ordinateur seulement).'),
    historique,
  ];
}

// Le fichier téléchargé contient ce qui vient d'être tapé : on garde la lettre avant de télécharger.
function lienTelechargement(format, nom) {
  const url = `/api/selection/${ctx.f.id}/dossier/lettre.${format}`;
  return h('a', {
    class: 'pastille', href: url, download: '',
    onclick: async (e) => { e.preventDefault(); await garderLettre(); location.href = url; },
  }, nom);
}

// Garde ce qui a été tapé dans la lettre (une seule version pour plusieurs modifications d'affilée).
async function garderLettre(temoin) {
  if (!ctx?.zoneLettre || !ctx.d.lettre) return;
  clearTimeout(ctx.sauvegarde);
  const texte = ctx.zoneLettre.value;
  if (texte.trim() === ctx.d.lettre.texte.trim()) return;
  const f = ctx.f;
  try {
    const r = await api(`/api/selection/${f.id}/dossier/lettre`, { texte });
    if (ctx?.f.id === f.id) {
      const zone = ctx.zoneLettre;
      ctx.d = r;
      ctx.zoneLettre = zone;
      if (r.lettre) ctx.majMeta?.(r.lettre);
      if (temoin) { temoin.classList.add('visible'); setTimeout(() => temoin.classList.remove('visible'), 1500); }
    }
  } catch (e) { toast(`Lettre pas gardée : ${e.message}`); }
}

async function choisirVersion(numero) {
  await garderLettre();
  try { ctx.d = await api(`/api/selection/${ctx.f.id}/dossier/version`, { numero }); } catch (e) { toast(e.message); return; }
  dessiner();
  toast(`Version ${numero} affichée.`);
}

// ======================================================================= conseils et analyse

function ongletConseils() {
  const diag = ctx.d.diagnostic;
  if (!diag) return h('p', { class: 'aide-liste' }, "Les conseils apparaissent une fois l'offre analysée.");
  return [
    h('p', { class: 'aide-liste' }, 'Retouches de ton CV pour cette offre, à partir de ce qui y figure déjà. Rien n\'est modifié tout seul : à toi de les reporter.'),
    (diag.conseils_cv || []).length ? h('div', { class: 'conseils' }, diag.conseils_cv.map(c => h('div', { class: 'conseil' },
      h('p', { class: 'conseil-tete' }, h('b', {}, ACTIONS_CONSEIL[c.action] || c.action), ` · ${c.section}`,
        c.a_verifier ? h('span', { class: 'a-verifier' }, 'à vérifier : source introuvable dans ton CV') : null),
      c.avant ? h('p', { class: 'avant' }, h('span', {}, 'Avant'), h('s', { translate: 'no' }, c.avant)) : null,
      c.apres ? h('p', { class: 'apres' }, h('span', {}, 'Après'), h('b', { translate: 'no' }, c.apres)) : null,
      h('p', { class: 'pourquoi-conseil' }, h('span', { translate: 'no' }, c.justification || ''),
        (c.mots_cles || []).length ? ` · mots de l'offre : ${c.mots_cles.map(m => `« ${m} »`).join(', ')}` : '')))) : h('p', { class: 'aide-liste' }, 'Aucun conseil retenu.'),
    diag.conseils_ecartes ? h('p', { class: 'aide-liste' }, `${diag.conseils_ecartes} conseil(s) écarté(s) : ils citaient une ligne absente de ton CV.`) : null,
    (diag.a_apprendre || []).length ? [h('h4', {}, 'À travailler avant l\'entretien'),
      h('p', { class: 'aide-liste' }, 'Absent de ton CV : à ne pas y ajouter sans l\'avoir fait.'),
      h('ul', { class: 'liste', translate: 'no' }, diag.a_apprendre.map(a => h('li', {}, a)))] : null,
  ];
}

function ongletAnalyse() {
  const d = ctx.d, diag = d.diagnostic;
  if (!diag) return h('p', { class: 'aide-liste' }, 'Offre pas encore analysée.');
  let confirmer = false;
  const refaire = h('button', {
    class: 'pastille', type: 'button',
    onclick: async () => {
      if (!confirmer) { confirmer = true; refaire.textContent = `Confirmer : refaire l'analyse (${d.prix.analyse})`; return; }
      refaire.disabled = true; refaire.textContent = "J'analyse l'offre face à ton CV (environ 20 secondes)…";
      try { ctx.d = await api(`/api/selection/${ctx.f.id}/dossier/analyser`, {}); dessiner(); toast('Analyse refaite.'); } catch (e) {
        toast(e.message); refaire.disabled = false; confirmer = false; refaire.textContent = "Refaire l'analyse";
      }
    },
  }, "Refaire l'analyse");
  return [
    d.a_refaire ? h('p', { class: 'note-ia' }, 'Ton CV a changé depuis cette analyse : refais-la pour en tenir compte.') : null,
    h('div', { class: 'synthese' }, h('span', { class: `adequation ${diag.adequation}` }, `Adéquation ${diag.adequation}`), h('p', { translate: 'no' }, diag.synthese)),
    h('div', { class: 'pour-contre' },
      h('div', {}, h('h4', {}, 'Pour'), h('ul', { class: 'liste', translate: 'no' }, (diag.pour || []).map(p => h('li', {}, p)))),
      h('div', {}, h('h4', {}, 'Contre'), h('ul', { class: 'liste', translate: 'no' }, (diag.contre || []).map(p => h('li', {}, p))))),
    (diag.alertes || []).map(a => h('div', { class: 'alerte' }, h('p', { translate: 'no' }, a.alerte), h('p', {}, h('b', {}, 'Question à poser : '), h('span', { translate: 'no' }, a.question_recruteur)))),
    h('h4', {}, "Exigences de l'offre"),
    h('div', { class: 'exigences' }, (diag.exigences || []).map(e => {
      const [signe, cls] = COUVERTURE[e.couverture] || ['•', ''];
      return h('div', { class: 'exigence' }, h('span', { class: `signe ${cls}`, 'aria-label': e.couverture }, signe),
        h('div', {}, h('b', { translate: 'no' }, e.exigence), e.obligatoire ? null : h('small', {}, ' (souhaité)'),
          h('p', {}, e.preuve_cv ? `Ton CV : « ${e.preuve_cv} »` : `Absent de ton CV${e.preuve_retiree ? " (preuve proposée par l'IA introuvable)" : ''}`,
            e.action && e.action !== '-' ? h('span', { translate: 'no' }, ` · ${e.action}`) : '')));
    })),
    h('p', { class: 'aide-liste' }, `Analyse du ${d.date_diagnostic} (${d.modele_diagnostic}).`),
    refaire,
  ];
}

// ======================================================================= conversation

function bulle(m) {
  return h('div', { class: `bulle ${m.role === 'user' ? 'moi' : 'ia'}` },
    h('p', { translate: 'no' }, texteRiche(m.texte)),
    m.version || m.detail ? h('small', {}, [m.version ? `Lettre mise à jour (version ${m.version})` : null, m.detail].filter(Boolean).join(' · ')) : null);
}

function conversation() {
  const d = ctx.d;
  const fil = h('div', { class: 'fil', 'aria-live': 'polite' },
    d.messages.length ? d.messages.map(bulle) : h('p', { class: 'aide-liste' },
      'Demande une retouche (« plus court », « insiste sur mon projet glycémie ») ou pose une question sur l\'offre.'));
  const champ = h('textarea', { class: 'champ', rows: '2', placeholder: 'Demande une retouche ou pose une question…', 'aria-label': 'Message à l\'IA' });
  const envoyer = h('button', { class: 'bouton principal', type: 'button', 'aria-label': 'Envoyer' }, '↑');
  const partir = async () => {
    const texte = champ.value.trim();
    if (!texte || ctx.enCours) return;
    ctx.enCours = true;
    champ.value = ''; envoyer.disabled = true;
    fil.querySelector('.aide-liste')?.remove();
    fil.append(bulle({ role: 'user', texte }), h('div', { class: 'bulle ia ecrit', 'aria-label': 'L\'IA écrit' }, h('i'), h('i'), h('i')));
    fil.scrollTop = fil.scrollHeight;
    const lettre = ctx.zoneLettre && ctx.d.lettre && ctx.zoneLettre.value.trim() !== ctx.d.lettre.texte.trim() ? ctx.zoneLettre.value : null;
    const f = ctx.f;
    try {
      const r = await api(`/api/selection/${f.id}/dossier/message`, lettre === null ? { texte } : { texte, lettre_actuelle: lettre });
      if (ctx?.f.id !== f.id) return;
      const avant = ctx.d.lettre?.numero;
      ctx.d = r;
      if (r.lettre && r.lettre.numero !== avant) ctx.onglet = 'lettre';
      ctx.enCours = false;
      dessiner();
    } catch (e) {
      ctx.enCours = false;
      fil.querySelector('.ecrit')?.remove();
      fil.append(h('p', { class: 'erreur-fil' }, e.message));
      champ.value = texte; envoyer.disabled = false;
    }
  };
  envoyer.addEventListener('click', partir);
  champ.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); partir(); } });
  return h('div', { class: 'dossier-droite' }, fil,
    h('div', { class: 'saisie' }, champ, envoyer),
    h('p', { class: 'aide-liste' }, `Entrée pour envoyer · une retouche : ${d.prix.retouche} · l'IA ne s'appuie que sur ton CV et l'offre.`));
}
