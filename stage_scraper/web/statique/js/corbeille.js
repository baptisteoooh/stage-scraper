// Page Corbeille : les offres mises de côté (par toi, par le tri, expirées). Rien n'est supprimé :
// on peut vérifier que le tri ne se trompe pas, et remettre une offre dans À trier.
import { $, h, api, toast, brancherScrap, majMenu, detailOffre, ouvrirPanneau, fermerPanneau } from './commun.js';

const PAR_PAGE = 50;
const etat = { listes: [], cle: 'toi', recherche: '', nb: PAR_PAGE };

const sansAccents = (t) => (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

async function charger() {
  const d = await api('/api/corbeille');
  majMenu(d);
  etat.listes = d.listes;
  dessiner();
}

function liste() { return etat.listes.find(l => l.cle === etat.cle); }

function visibles() {
  const l = liste();
  if (!l) return [];
  const q = sansAccents(etat.recherche.trim());
  return q ? l.offres.filter(o => sansAccents(`${o.titre} ${o.entreprise} ${o.raison}`).includes(q)) : l.offres;
}

function dessiner() {
  $('#listes').replaceChildren(...etat.listes.map(l => h('button', {
    class: 'pastille', type: 'button', 'aria-pressed': String(l.cle === etat.cle),
    onclick: () => { etat.cle = l.cle; etat.nb = PAR_PAGE; dessiner(); },
  }, l.nom, h('small', {}, String(l.total)))));
  const l = liste();
  const offres = visibles();
  const tronquee = l.total > l.offres.length ? ` (les ${l.offres.length} plus récentes)` : '';
  $('#compte').textContent = etat.recherche ? `${offres.length} sur ${l.offres.length}` : `${l.total} offre${l.total > 1 ? 's' : ''}${tronquee}`;
  const zone = $('#corbeille');
  zone.replaceChildren(...[
    h('p', { class: 'aide-liste' }, l.aide),
    offres.length ? h('div', { class: 'lignes' }, offres.slice(0, etat.nb).map(ligne))
      : h('p', { class: 'rien-ici' }, etat.recherche ? 'Aucune offre ne correspond.' : 'Rien ici.'),
    offres.length > etat.nb ? h('button', {
      class: 'pastille plus-de', type: 'button', onclick: () => { etat.nb += PAR_PAGE; dessiner(); },
    }, `Afficher plus (${offres.length - etat.nb} autres)`) : null].filter(Boolean));
  zone.scrollTop = 0;
}

function ligne(o, i) {
  const note = o.score === null || o.score === undefined ? '' : ` · ${o.score}/10`;
  return h('div', { class: 'ligne-offre apparait', style: `--i:${Math.min(i, 14)}`, 'data-id': o.id },
    h('div', { class: 'quoi', onclick: () => ouvrir(o) },
      h('b', {}, o.titre),
      h('span', {}, `${o.entreprise}${o.lieu ? ` · ${o.lieu}` : ''}${note} · `, h('em', {}, o.raison || ''))),
    h('div', { class: 'boutons' },
      o.remettre ? h('button', { class: 'pastille', type: 'button', onclick: (e) => remettre(o, e.currentTarget.closest('.ligne-offre')) },
        etat.cle === 'expirees' ? 'Remettre en ligne' : 'Remettre à trier') : null,
      h('button', { class: 'pastille', type: 'button', onclick: () => ouvrir(o) }, 'Détails')));
}

async function remettre(o, el) {
  try { await api('/api/corbeille/remettre', { offre_id: o.id, liste: etat.cle }); } catch (e) { toast(e.message); return; }
  el?.classList.add('part');
  fermerPanneau();
  await new Promise(r => setTimeout(r, 280));
  await charger();
  toast(`« ${o.titre} » est de retour dans À trier.`);
}

async function ouvrir(o) {
  const corps = $('#fiche-corps');
  corps.replaceChildren(h('p', { class: 'texte' }, 'Chargement…'));
  ouvrirPanneau();
  let detail;
  try { detail = await api(`/api/offres/${o.id}`); } catch {
    corps.replaceChildren(h('p', { class: 'texte' }, "Impossible de charger l'offre.")); return;
  }
  const actions = h('div', { class: 'fiche-decisions' },
    o.remettre ? h('button', { class: 'bouton principal', type: 'button', onclick: () => remettre(o, document.querySelector(`.ligne-offre[data-id="${o.id}"]`)) },
      etat.cle === 'expirees' ? 'Remettre en ligne' : 'Remettre à trier') : null,
    o.raison ? h('p', { class: 'texte', style: 'color:var(--doux)' }, `Mise de côté : ${o.raison}`) : null);
  corps.replaceChildren(...detailOffre(detail, actions));
}

$('#fiche-fermer').addEventListener('click', fermerPanneau);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && fermerPanneau()) e.preventDefault(); });
let attente = 0;
$('#recherche').addEventListener('input', (e) => {
  clearTimeout(attente);
  attente = setTimeout(() => { etat.recherche = e.target.value; etat.nb = PAR_PAGE; dessiner(); }, 160);
});
brancherScrap(async (s) => {
  await charger();
  toast(s.erreur ? `Le scrap a planté : ${s.erreur}` : 'Scrap terminé.');
});
charger().catch((e) => { console.error(e); toast('Impossible de charger la corbeille : le serveur tourne-t-il ?'); });
