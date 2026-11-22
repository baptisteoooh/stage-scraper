// Mes documents (CV, lettre modèle) : dépôt par clic ou glisser-déposer, et ce que l'IA en reçoit (anonymisé).
// Affiché dans Mon profil.
import { h, api, toast } from './commun.js';

export function blocDocuments(doc, recharger) {
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
        await recharger();
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
    h('p', { class: 'aide-liste' }, "Ton CV et une lettre que tu as écrite (modèle de style). Ils restent sur ton ordinateur ; "
      + "les IA ne reçoivent que leur texte, sans ton nom ni tes coordonnées."),
    doc.nom_masque ? null : h('p', { class: 'alerte' }, "Ton nom n'a pas été reconnu en tête du CV : vérifie dans le texte ci-dessous qu'il n'apparaît pas."),
    h('div', { class: 'documents' },
      carteDoc('cv', 'CV', doc.cv, 'application/pdf,.pdf', 'Dépose ton CV en PDF, ou clique pour le choisir'),
      carteDoc('modele', 'Lettre modèle', doc.modele, '.txt,.docx', 'Facultatif : une lettre à toi (.txt ou .docx)')),
  ];
}

