// Page Journal : la semaine en une phrase, l'historique des scraps (source par source), et le coût de l'IA replié.
import { LOCALE, LANGUE, $, h, api, toast, afficherScrap, brancherScrap, majMenu, montant } from './commun.js';

const JOURS = new Intl.DateTimeFormat(LOCALE, { weekday: 'short', day: 'numeric', month: 'short' });

function quand(texte) {
  const d = new Date(texte.replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return texte;
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${JOURS.format(d)} · ${LANGUE === 'en' ? `${d.getHours()}:${mm}` : `${d.getHours()} h ${mm}`}`;
}

function pluriel(n, mot) { return `${n} ${mot}${n > 1 ? 's' : ''}`; }

// Noms lisibles des sources (le journal stocke des noms techniques).
const NOMS = { scoring: "Notation par l'IA", google_jobs: 'Google Jobs', careerjet: 'Careerjet', gmail: 'Alertes mail',
  carrieres: 'Pages carrières', mail_alerte: 'Mails', france_travail: 'France Travail', commune: 'Offres partagées' };
const nomSource = (s) => NOMS[s] || s;

function vide(p) { return !p.trouvees && !p.nouvelles && !p.notees; }

// Les passages sans rien de nouveau qui se suivent tiennent sur une seule ligne.
function regrouper(passages) {
  const lignes = [];
  for (const p of passages) {
    const derniere = lignes[lignes.length - 1];
    if (vide(p) && derniere?.groupe) derniere.groupe.push(p);
    else if (vide(p)) lignes.push({ groupe: [p] });
    else lignes.push(p);
  }
  return lignes.map(l => (l.groupe && l.groupe.length === 1 ? l.groupe[0] : l));
}

function groupe(g, i) {
  const enErreur = g.groupe.filter(p => Object.keys(p.erreurs).length).length;
  const fin = g.groupe[0].date, debut = g.groupe[g.groupe.length - 1].date;
  return h('details', { class: 'passage apparait', style: `--i:${Math.min(i, 12)}` },
    h('summary', {},
      h('span', { class: 'quand' }, `${quand(debut)} → ${quand(fin)}`),
      h('span', { class: 'nombres' }, `${g.groupe.length} passages sans nouvelle offre`),
      h('span', { class: `etat${enErreur ? ' erreur' : ''}` }, enErreur ? `${enErreur} avec une erreur` : 'OK')),
    h('div', { class: 'groupe' }, g.groupe.map((p, j) => passage(p, j))));
}

// « Cette semaine : 26 nouvelles offres, dont 3 notées 8 ou plus. »
function semaine(passages) {
  const depuis = Date.now() - 7 * 86400000;
  const recents = passages.filter(p => new Date(p.date.replace(' ', 'T')).getTime() >= depuis);
  const gardees = recents.reduce((n, p) => n + (p.gardees || 0), 0), top = recents.reduce((n, p) => n + (p.top || 0), 0);
  if (!gardees) return 'Cette semaine : pas de nouvelle offre gardée.';
  return `Cette semaine : ${gardees > 1 ? `${gardees} nouvelles offres` : '1 nouvelle offre'}${top ? `, dont ${top} notée${top > 1 ? 's' : ''} 8 ou plus` : ''}.`;
}

function chiffre(titre, valeur, detail, part = null) {
  return h('div', { class: 'chiffre apparait' }, h('small', {}, titre), h('b', {}, valeur), h('span', {}, detail),
    part === null ? null : h('div', { class: 'jauge', role: 'img', 'aria-label': `${Math.round(part * 100)} %` },
      h('i', { style: `width:${Math.max(0, Math.min(1, part)) * 100}%` })));
}

function passage(p, i) {
  const erreurs = Object.keys(p.erreurs);
  const resume = p.trouvees || p.nouvelles
    ? [h('b', {}, String(p.trouvees)), ' trouvées · ', h('b', {}, String(p.nouvelles)), ' nouvelles · ',
      h('b', {}, String(p.gardees)), p.gardees === 1 ? ' gardée' : ' gardées', p.top ? [' · ', h('b', {}, String(p.top)), p.top === 1 ? ' notée 8+' : ' notées 8+'] : null]
    : [p.notees ? `Notation seule : ${pluriel(p.notees, 'offre')}` : 'Rien de nouveau'];
  return h('details', { class: 'passage apparait', style: `--i:${Math.min(i, 12)}` },
    h('summary', {},
      h('span', { class: 'quand' }, quand(p.date)),
      p.auto ? h('span', { class: 'mode auto' }, 'auto') : null,
      h('span', { class: 'nombres' }, resume),
      h('span', { class: `etat${erreurs.length ? ' erreur' : ''}` },
        erreurs.length ? `${pluriel(erreurs.length, 'source')} en erreur` : p.cout ? montant(p.cout, 4) : 'OK')),
    h('div', { class: 'sources' }, p.sources.map(s => h('div', { class: 'source' },
      h('b', {}, nomSource(s.source)),
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
    h('p', { class: 'semaine' }, semaine(d.passages)),
    h('h2', {}, 'Passages'),
    d.passages.length ? h('div', { class: 'passages' }, regrouper(d.passages).map((p, i) => (p.groupe ? groupe(p, i) : passage(p, i))))
      : h('p', { class: 'rien-ici' }, 'Aucun passage pour l\'instant : lance un scrap.'),
    d.passages.length ? h('p', { class: 'explication' }, 'Trouvées : offres reçues des sources · Nouvelles : jamais vues avant · '
      + 'Gardées : nouvelles qui passent le tri (ni doublon, ni exclue, ni expirée). Clique un passage pour le détail par source.') : null,
    h('details', { class: 'appels' },
      h('summary', {}, `Coût de l'IA : crédit Claude restant ${montant(c.restant)} sur ${montant(c.total)}`),
      h('div', { class: 'chiffres' },
        chiffre('Crédit Claude restant', montant(c.restant), `sur ${montant(c.total)} · ≈ ${pluriel(c.dossiers, 'dossier')}`, c.restant / c.total),
        chiffre('Claude ce mois-ci', montant(c.mois, 3), `plafond ${montant(c.plafond_mois)}`, c.mois / c.plafond_mois),
        chiffre('Offres en base', d.offres_en_base.toLocaleString(LOCALE), 'toutes sources, doublons compris')),
      h('p', { class: 'explication' },
        `Claude ne sert qu'aux fiches de Ma sélection (analyse, lettre) ; le reste passe par Gemini, gratuit. Au-delà de ${montant(c.plafond_mois)} par mois `
        + `ou ${montant(c.plafond_total)} au total, Gemini prend le relais.`)),
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
