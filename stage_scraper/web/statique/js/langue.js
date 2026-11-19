// Version anglaise : traduit ce que les scripts ajoutent à la page, avec le dictionnaire que le serveur a
// glissé dans window.TRADUCTION (chargé seulement en anglais). Même règle que stage_scraper/web/langue.py :
// texte connu ou motif avec des trous, sinon on ne touche à rien (offres, textes de l'IA, translate="no").
(() => {
  const D = window.TRADUCTION;
  if (!D) return;
  const MOTIFS = D.motifs.map(([source, en]) => [new RegExp(source, 's'), en]);
  const ATTRIBUTS = ['placeholder', 'aria-label', 'title', 'alt'];

  function traduire(texte, profondeur = 0) {
    const coeur = texte.trim();
    if (!coeur || profondeur > 3) return texte;
    let trouve = D.textes[coeur];
    if (trouve === undefined && profondeur && /^-?\d+(,\d+)?$/.test(coeur)) trouve = coeur.replace(',', '.');
    if (trouve === undefined) {
      for (const [motif, en] of MOTIFS) {
        const m = motif.exec(coeur);
        if (!m) continue;
        trouve = en;
        m.slice(1).forEach((morceau, i) => { trouve = trouve.replace(`{${i + 1}}`, traduire(morceau, profondeur + 1)); });
        break;
      }
    }
    if (trouve === undefined) return texte;
    return texte.slice(0, texte.length - texte.trimStart().length) + trouve + texte.slice(texte.trimEnd().length);
  }
  window.traduire = traduire;

  // Textes : pas dans les zones translate="no", ni dans les scripts, styles et champs de saisie.
  // Attributs (placeholder, aria-label…) : seulement pas dans translate="no".
  const exclu = (el) => !el || el.closest('[translate="no"]');

  function noeudTexte(n) {
    if (exclu(n.parentElement) || n.parentElement.closest('script, style, textarea')) return;
    const t = traduire(n.data);
    if (t !== n.data) n.data = t;
  }
  function element(el) {
    if (exclu(el)) return;
    for (const a of ATTRIBUTS) {
      const v = el.getAttribute(a);
      if (v) { const t = traduire(v); if (t !== v) el.setAttribute(a, t); }
    }
  }
  function parcourir(racine) {
    if (racine.nodeType === 3) { noeudTexte(racine); return; }
    if (racine.nodeType !== 1) return;
    element(racine);
    const marche = document.createTreeWalker(racine, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    for (let n = marche.nextNode(); n; n = marche.nextNode()) (n.nodeType === 3 ? noeudTexte : element)(n);
  }

  new MutationObserver((changements) => {
    for (const c of changements) {
      if (c.type === 'childList') c.addedNodes.forEach(parcourir);
      else if (c.type === 'characterData') noeudTexte(c.target);
      else element(c.target);
    }
  }).observe(document.documentElement, {
    childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRIBUTS,
  });
})();
