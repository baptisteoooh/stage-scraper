// Moteur de glissement façon Tinder, partagé par l'accueil (carte d'exemple) et la page À trier.
//
// - la carte suit le doigt / la souris image par image (requestAnimationFrame), avec une rotation douce ;
// - au lâcher, on regarde la distance ET la vitesse : un geste vif suffit, même court ;
// - la carte part à la vitesse du geste (animation Web Animations, fluide même si la page travaille) ;
// - sinon elle revient au centre avec un léger rebond (ressort) ;
// - on peut la rattraper pendant qu'elle revient : l'animation s'arrête là où elle en est ;
// - « mouvement réduit » (réglage Windows) : un simple fondu, sans voyage.

const reduit = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const borne = (v, min, max) => Math.min(max, Math.max(min, v));

const RESSORT = 'cubic-bezier(.2, 1.4, .36, 1)';      // retour au centre, petit dépassement
const LANCER = 'cubic-bezier(.25, .7, .35, 1)';       // départ hors de l'écran

export class Glisseur {
  /**
   * @param {HTMLElement} carte
   * @param {{auBouger?: Function, auLacher?: Function, haut?: boolean}} options
   *   auBouger({dx, dy, force, dir, retour}) : à chaque image (force de 0 à 1, dir : droite|gauche|haut|null)
   *   auLacher(dir, fin) : la carte part dans cette direction (fin : promesse tenue quand elle est sortie)
   *   auTap() : un simple toucher / clic sur la carte, sans la faire glisser (ouvrir les détails)
   *   haut : autoriser le glissement vers le haut (Plus tard)
   */
  constructor(carte, { auBouger = () => {}, auLacher = () => {}, auTap = null, haut = true } = {}) {
    Object.assign(this, { carte, auBouger, auLacher, auTap, haut });
    this.dx = 0; this.dy = 0; this.actif = false; this.points = []; this.anim = null; this.image = 0;
    this.parti = false;
    this._bas = this._bas.bind(this); this._bouge = this._bouge.bind(this); this._haut = this._haut.bind(this);
    carte.addEventListener('pointerdown', this._bas);
    carte.addEventListener('pointermove', this._bouge);
    carte.addEventListener('pointerup', this._haut);
    carte.addEventListener('pointercancel', this._haut);
    carte.style.touchAction = 'pan-y';
  }

  detruire() {
    this.carte.removeEventListener('pointerdown', this._bas);
    this.carte.removeEventListener('pointermove', this._bouge);
    this.carte.removeEventListener('pointerup', this._haut);
    this.carte.removeEventListener('pointercancel', this._haut);
    cancelAnimationFrame(this.image);
  }

  // Position actuelle de la carte, même au milieu d'une animation.
  position() {
    const m = new DOMMatrix(getComputedStyle(this.carte).transform);
    return { x: m.m41, y: m.m42, rot: Math.atan2(m.b, m.a) * 180 / Math.PI };
  }

  _bas(e) {
    if (this.parti || e.button !== 0 || e.target.closest('a, button, input, [data-pas-glisser]')) return;
    const depart = this.position();        // rattrapée en plein retour (ou penchée au repos) : on part de là
    if (this.anim) { this.anim.cancel(); this.anim = null; }
    this.dx = depart.x; this.dy = depart.y;
    this.x0 = e.clientX - this.dx; this.y0 = e.clientY - this.dy;
    this.actif = true;
    this.points = [{ x: e.clientX, y: e.clientY, t: e.timeStamp }];
    this.debut = { x: e.clientX, y: e.clientY, t: e.timeStamp };
    this.carte.setPointerCapture(e.pointerId);
    this.carte.classList.add('tenue');
    this._peindre();
  }

  _bouge(e) {
    if (!this.actif) return;
    this.dx = e.clientX - this.x0;
    this.dy = e.clientY - this.y0;
    this.points.push({ x: e.clientX, y: e.clientY, t: e.timeStamp });
    if (this.points.length > 8) this.points.shift();
    if (!this.image) this.image = requestAnimationFrame(() => { this.image = 0; this._peindre(); });
  }

  // Vers le bas, la carte résiste (on ne range rien en bas) ; vers le haut, elle suit si « haut » est permis.
  _dyAffiche() {
    if (this.dy < 0) return this.haut ? this.dy : this.dy * .3;
    return this.dy * .3;
  }

  _etat() {
    const l = this.carte.offsetWidth || 1, h = this.carte.offsetHeight || 1;
    const dy = this._dyAffiche();
    const fx = Math.abs(this.dx) / (l * .32), fy = -dy / (h * .26);
    let dir = null, force = 0;
    if (Math.abs(this.dx) >= Math.abs(dy) && this.dx !== 0) { dir = this.dx > 0 ? 'droite' : 'gauche'; force = fx; }
    else if (dy < 0 && this.haut) { dir = 'haut'; force = fy; }
    return { dx: this.dx, dy, dir, force: borne(force, 0, 1) };
  }

  _peindre() {
    const { dx, dy } = this._etat();
    const rot = borne(dx / (this.carte.offsetWidth || 1) * 16, -20, 20);
    this.carte.style.transform = `translate3d(${dx}px, ${dy}px, 0) rotate(${rot}deg)`;
    this.auBouger(this._etat());
  }

  _vitesse() {
    const fin = this.points[this.points.length - 1];
    const debut = this.points.find(p => fin.t - p.t <= 100) || this.points[0];
    const dt = Math.max(fin.t - debut.t, 1);
    return { vx: (fin.x - debut.x) / dt, vy: (fin.y - debut.y) / dt };   // pixels par milliseconde
  }

  _haut(e) {
    if (!this.actif) return;
    this.actif = false;
    cancelAnimationFrame(this.image); this.image = 0;
    this.carte.classList.remove('tenue');
    if (this.carte.hasPointerCapture?.(e.pointerId)) this.carte.releasePointerCapture(e.pointerId);
    this._peindre();
    const { vx, vy } = this._vitesse();
    const l = this.carte.offsetWidth, h = this.carte.offsetHeight;
    const dy = this._dyAffiche();
    let dir = null;
    if (this.dx > l * .32 || (vx > .5 && this.dx > 24)) dir = 'droite';
    else if (this.dx < -l * .32 || (vx < -.5 && this.dx < -24)) dir = 'gauche';
    else if (this.haut && Math.abs(dy) > Math.abs(this.dx) && (dy < -h * .26 || (vy < -.5 && dy < -24))) dir = 'haut';
    if (dir) { this.auLacher(dir, this.envoyer(dir, Math.hypot(vx, vy))); return; }
    this.revenir();
    // Toucher sans bouger (pas un défilement annulé par le navigateur) : c'est un « tap ».
    const d = this.debut;
    if (this.auTap && e.type === 'pointerup' && d && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 8 && e.timeStamp - d.t < 500) this.auTap();
  }

  /** Fait partir la carte (geste, bouton ou clavier). Renvoie une promesse tenue quand elle est sortie. */
  envoyer(dir, vitesse = 0) {
    this.parti = true;
    const depart = this.anim ? this.position() : { x: this.dx, y: this._dyAffiche(), rot: this.position().rot };
    if (this.anim) { this.anim.cancel(); this.anim = null; }
    this.auBouger({ dx: depart.x, dy: depart.y, dir, force: 1, depart: true });
    const r = this.carte.getBoundingClientRect();
    if (reduit()) {
      this.anim = this.carte.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, fill: 'forwards' });
      return this.anim.finished.catch(() => {});
    }
    let x = depart.x, y = depart.y, rot = depart.rot;
    if (dir === 'droite') { x += innerWidth - r.left + 60; y += depart.y * .4 + 30; rot = Math.max(rot, 0) + 14; }
    else if (dir === 'gauche') { x -= r.right + 60; y += depart.y * .4 + 30; rot = Math.min(rot, 0) - 14; }
    else { y -= r.bottom + 60; x *= 1.3; rot *= .5; }
    const distance = Math.hypot(x - depart.x, y - depart.y);
    const duree = borne(distance / Math.max(vitesse, 1.9), 200, 420);
    this.anim = this.carte.animate([
      { transform: `translate3d(${depart.x}px, ${depart.y}px, 0) rotate(${depart.rot}deg)` },
      { transform: `translate3d(${x}px, ${y}px, 0) rotate(${rot}deg)` },
    ], { duration: duree, easing: LANCER, fill: 'forwards' });
    return this.anim.finished.catch(() => {});
  }

  /** Retour au centre, avec un léger rebond. */
  revenir() {
    const depart = this.position();
    this.dx = 0; this.dy = 0;
    this.carte.style.transform = '';
    this.auBouger({ dx: 0, dy: 0, dir: null, force: 0, retour: true });
    if (reduit() || (Math.abs(depart.x) < 1 && Math.abs(depart.y) < 1)) return;
    const anim = this.carte.animate([
      { transform: `translate3d(${depart.x}px, ${depart.y}px, 0) rotate(${depart.rot}deg)` },
      { transform: 'translate3d(0, 0, 0) rotate(0deg)' },
    ], { duration: 560, easing: RESSORT });
    this.anim = anim;
    anim.finished.then(() => { if (this.anim === anim) this.anim = null; }, () => {});
  }

  /** La carte revient d'un côté de l'écran (annulation d'une décision). */
  entrer(dir) {
    if (reduit()) return this.carte.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160 }).finished;
    const x = dir === 'droite' ? innerWidth * .7 : dir === 'gauche' ? -innerWidth * .7 : 0;
    const y = dir === 'haut' ? -innerHeight * .8 : 40;
    const rot = dir === 'droite' ? 14 : dir === 'gauche' ? -14 : 0;
    this.anim = this.carte.animate([
      { transform: `translate3d(${x}px, ${y}px, 0) rotate(${rot}deg)` },
      { transform: 'translate3d(0, 0, 0) rotate(0deg)' },
    ], { duration: 520, easing: 'cubic-bezier(.2, 1.15, .4, 1)' });
    const anim = this.anim;
    return anim.finished.then(() => { if (this.anim === anim) this.anim = null; }, () => {});
  }
}
