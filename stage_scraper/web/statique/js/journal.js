// Page Journal : crédit Claude restant, coût de l'IA, et l'historique des scraps (source par source).
import { LOCALE, LANGUE, $, h, api, toast, afficherScrap, brancherScrap, majMenu, montant } from './commun.js';

const JOURS = new Intl.DateTimeFormat(LOCALE, { weekday: 'short', day: 'numeric', month: 'short' });

function quand(texte) {
  const d = new Date(texte.replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return texte;
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${JOURS.format(d)} · ${LANGUE === 'en' ? `${d.getHours()}:${mm}` : `${d.getHours()} h ${mm}`}`;
}

function pluriel(n, mot) { return `${n} ${mot}${n > 1 ? 's' : ''}`; }

function chiffre(titre, valeur, detail, part = null) {
  return h('div', { class: 'chiffre apparait' }, h('small', {}, titre), h('b', {}, valeur), h('span', {}, detail),
    part === null ? null : h('div', { class: 'jauge', role: 'img', 'aria-label': `${Math.round(part * 100)} %` },
      h('i', { style: `width:${Math.max(0, Math.min(1, part)) * 100}%` })));
}

function passage(p, i) {
  const erreurs = Object.keys(p.erreurs);
  const resume = p.trouvees || p.nouvelles
    ? [h('b', {}, String(p.trouvees)), ' trouvées · ', h('b', {}, String(p.nouvelles)), ' nouvelles · ',
      h('b', {}, String(p.gardees)), ' gardées', p.top ? [' · ', h('b', {}, String(p.top)), ' notées 8+'] : null]
    : [p.notees ? `Notation seule : ${pluriel(p.notees, 'offre')}` : 'Rien de nouveau'];
  return h('details', { class: 'passage apparait', style: `--i:${Math.min(i, 12)}` },
    h('summary', {},
      h('span', { class: 'quand' }, quand(p.date)),
      h('span', { class: `mode${p.auto ? ' auto' : ''}` }, p.auto ? 'auto' : 'manuel'),
      h('span', { class: 'nombres' }, resume),
      h('span', { class: `etat${erreurs.length ? ' erreur' : ''}` },
        erreurs.length ? `${pluriel(erreurs.length, 'source')} en erreur` : p.cout ? montant(p.cout, 4) : 'OK')),
    h('div', { class: 'sources' }, p.sources.map(s => h('div', { class: 'source' },
      h('b', {}, s.source),
      h('span', {}, s.source === 'scoring' ? `${pluriel(s.offres, 'offre')} notée${s.offres > 1 ? 's' : ''}`
        : `${s.offres} reçues, ${s.nouvelles} nouv.`),
      s.erreur ? h('span', { class: 'err', translate: 'no' }, s.erreur) : h('span', {}, s.cout ? montant(s.cout, 4) : '')))));
}

async function charger() {
  const d = await api('/api/journal');
  majMenu(d);
  const c = d.credit;
  const zone = $('#journal');
  zone.replaceChildren(...[
    h('div', { class: 'chiffres' },
      chiffre('Crédit Claude restant', montant(c.restant), `sur ${montant(c.total)} · ≈ ${pluriel(c.dossiers, 'dossier')}`, c.restant / c.total),
      chiffre('Claude ce mois-ci', montant(c.mois, 3), `plafond ${montant(c.plafond_mois)}`, c.mois / c.plafond_mois),
      chiffre('Offres en base', d.offres_en_base.toLocaleString(LOCALE), 'toutes sources, doublons compris')),
    h('p', { class: 'explication' },
      `Claude ne sert qu'aux fiches de Ma sélection (analyse, lettre) ; le reste passe par Gemini, gratuit. Au-delà de ${montant(c.plafond_mois)} par mois `
      + `ou ${montant(c.plafond_total)} au total, Gemini prend le relais. Le solde exact est dans la console Anthropic (Billing).`),
    h('h2', {}, 'Passages'),
    d.passages.length ? h('div', { class: 'passages' }, d.passages.map(passage))
      : h('p', { class: 'rien-ici' }, 'Aucun passage pour l\'instant : lance un scrap.'),
    d.passages.length ? h('p', { class: 'explication' }, 'Trouvées : offres reçues des sources · Nouvelles : jamais vues avant · '
      + 'Gardées : nouvelles qui passent le tri (ni doublon, ni exclue, ni expirée). Clique un passage pour le détail par source.') : null,
    d.appels.length ? h('details', { class: 'appels' },
      h('summary', {}, `Appels d'IA depuis l'appli (${d.appels.length} : fiches et Assistant)`),
      h('div', { class: 'sources' }, d.appels.map(a => h('div', { class: 'source' },
        h('span', {}, quand(a.date)), h('b', {}, a.ou), h('span', { class: a.erreur ? 'err' : '', translate: 'no' }, a.erreur || a.modele || ''),
        h('span', {}, montant(a.cout || 0, 4)))))) : null,
  ].filter(Boolean));
}

brancherScrap(async (s) => {
  await charger();
  toast(s.erreur ? `Le scrap a planté : ${s.erreur}` : 'Scrap terminé : le passage est en haut de la liste.');
});
charger().catch((e) => { console.error(e); afficherScrap(null); toast('Impossible de charger le journal : le serveur tourne-t-il ?'); });
