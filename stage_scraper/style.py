"""Habillage de l'appli, inspiré des principes de design d'Apple.

- Retour immédiat : un bouton s'enfonce légèrement dès qu'on appuie (pas au relâchement).
- Profondeur douce : cartes arrondies avec une ombre légère, barre latérale translucide.
- Typographie : police du système, titres resserrés (interlettrage négatif), texte courant aéré.
- Accessibilité : animations coupées si Windows demande de réduire les animations,
  transparence supprimée si elle est réduite, contours renforcés en contraste élevé.
Les couleurs viennent du thème (.streamlit/config.toml), en clair comme en sombre.
"""
import streamlit as st

CSS = """
<style>
/* ---------- Typographie ---------- */
.stApp h1 { font-size: 2.1rem; line-height: 1.1; letter-spacing: -0.022em; font-weight: 700; }
.stApp h2 { line-height: 1.15; letter-spacing: -0.018em; }
.stApp h3 { line-height: 1.2; letter-spacing: -0.012em; }
.stApp p, .stApp li { line-height: 1.5; }
[data-testid="stCaptionContainer"] { letter-spacing: 0.005em; }
/* Place sous le menu du haut, contenu large pour les colonnes du suivi */
[data-testid="stMainBlockContainer"] { padding-top: 5rem; max-width: 1720px; }

/* ---------- Retour immédiat sur les boutons ---------- */
.stButton button, .stDownloadButton button, .stLinkButton a, .stFormSubmitButton button {
  transition: transform 100ms ease-out, box-shadow 150ms ease-out, background-color 150ms ease-out;
}
.stButton button:active, .stDownloadButton button:active, .stLinkButton a:active,
.stFormSubmitButton button:active { transform: scale(0.97); }

/* ---------- Chiffres clés en cartes ---------- */
[data-testid="stMetric"] {
  background: var(--carte-fond, rgba(127, 127, 127, 0.06));
  border-radius: 1.1rem; padding: 0.9rem 1.1rem;
}
[data-testid="stMetricValue"] { letter-spacing: -0.02em; font-weight: 650; }

/* ---------- Cartes (conteneurs avec une clé « carte_… ») ---------- */
[class*="st-key-carte_"] {
  border-radius: 1.1rem !important; padding: 1.15rem 1.25rem !important; gap: 0.55rem;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04), 0 4px 14px rgba(0, 0, 0, 0.05);
  transition: transform 160ms ease-out, box-shadow 160ms ease-out;
}
[class*="st-key-carte_"]:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05), 0 10px 24px rgba(0, 0, 0, 0.08);
}
[class*="st-key-carte_"] p { margin-bottom: 0.2rem; }
/* Streamlit remonte chaque bloc de texte de 1rem : dans une carte, ça fait chevaucher le bouton */
[class*="st-key-carte_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0 !important; }

/* En-têtes de colonnes du suivi des candidatures */
[class*="st-key-colonne_"] { gap: 0.9rem; }
.etape-titre { display: flex; align-items: baseline; gap: 0.5rem; margin: 0 0 0.5rem 0.2rem;
  font-size: 1.15rem; font-weight: 650; letter-spacing: -0.012em; }
.etape-compte { font-weight: 500; opacity: 0.55; font-variant-numeric: tabular-nums; }
.carte-entreprise { font-weight: 650; letter-spacing: -0.012em; font-size: 1.12rem; line-height: 1.25; }
.carte-poste { opacity: 0.82; font-size: 0.98rem; line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.carte-meta { opacity: 0.62; font-size: 0.86rem; font-variant-numeric: tabular-nums; }
.etape-vide { padding: 1.6rem 1rem; text-align: center; font-size: 0.9rem; opacity: 0.55;
  border: 1.5px dashed rgba(127, 127, 127, 0.35); border-radius: 1.1rem; }

/* ---------- Vignettes d'offres (page Offres) ---------- */
/* Grille automatique : autant de colonnes de 400 px minimum que la largeur le permet.
   Les vignettes d'une même rangée ont la même hauteur, boutons alignés en bas. */
[class*="st-key-grille_"] { display: grid !important; gap: 1.1rem;
  grid-template-columns: repeat(auto-fill, minmax(min(400px, 100%), 1fr)); align-items: stretch; }
[class*="st-key-grille_"] > * { width: auto !important; min-width: 0; }
[class*="st-key-carte_offre_"] { height: 100%; padding: 1.5rem 1.6rem 1.25rem !important; }
[class*="st-key-carte_offre_"] [data-testid="stElementContainer"]:has(.vignette) { flex-grow: 1; }
.vignette { display: flex; flex-direction: column; gap: 0.7rem; height: 100%; }
.v-haut { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.8rem; }
.v-entreprise { font-size: 0.95rem; font-weight: 600; opacity: 0.7; letter-spacing: -0.005em;
  line-height: 1.3; padding-top: 0.15rem; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.v-titre { font-size: 1.18rem; font-weight: 650; line-height: 1.3; letter-spacing: -0.015em;
  min-height: 2.6em; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
/* Note : couleur mélangée à la couleur du texte, donc lisible en clair comme en sombre */
.v-note { flex-shrink: 0; border-radius: 999px; padding: 0.28rem 0.75rem; font-variant-numeric: tabular-nums;
  line-height: 1.2; white-space: nowrap; }
.v-note b { font-size: 1.2rem; font-weight: 700; letter-spacing: -0.02em; }
.v-note span { font-size: 0.8rem; opacity: 0.7; margin-left: 0.1rem; }
.v-note-haute { background: rgba(52, 199, 89, 0.17); color: color-mix(in srgb, #34c759 65%, currentColor); }
.v-note-moyenne { background: rgba(10, 132, 255, 0.14); color: color-mix(in srgb, #0a84ff 65%, currentColor); }
.v-note-basse, .v-note-attente { background: rgba(142, 142, 147, 0.16); }
.v-badges { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.v-badges:empty { display: none; }
.v-badge { font-size: 0.75rem; font-weight: 600; padding: 0.15rem 0.6rem; border-radius: 999px; }
.v-nouveau { background: rgba(10, 132, 255, 0.14); color: color-mix(in srgb, #0a84ff 70%, currentColor); }
.v-ia { background: rgba(175, 82, 222, 0.15); color: color-mix(in srgb, #af52de 70%, currentColor); }
.v-cdd { background: rgba(255, 149, 0, 0.17); color: color-mix(in srgb, #ff9500 60%, currentColor); }
.v-suivie { background: rgba(52, 199, 89, 0.15); color: color-mix(in srgb, #34c759 65%, currentColor); }
.v-favori { background: rgba(255, 204, 0, 0.2); color: color-mix(in srgb, #d4a000 75%, currentColor); }
.chat-raison { font-size: 0.86rem; opacity: 0.75; }
.v-expiree { background: rgba(255, 59, 48, 0.13); color: color-mix(in srgb, #ff3b30 65%, currentColor); }
/* Vignette d'une offre en favori : liseré doré */
[class*="st-key-carte_offre_"]:has(.v-est-favori) { border-color: rgba(255, 204, 0, 0.65) !important; }
.v-infos { display: flex; flex-wrap: wrap; gap: 0.4rem 0.45rem; }
.v-info { font-size: 0.86rem; padding: 0.25rem 0.65rem; border-radius: 0.6rem;
  background: rgba(127, 127, 127, 0.09); white-space: nowrap; }
.v-inconnu { opacity: 0.5; }
/* Résumé de l'IA en entier (2 à 3 lignes), puis l'extrait de l'annonce */
.v-resume { font-size: 0.97rem; line-height: 1.55; opacity: 0.9;
  display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
.v-extrait { font-size: 0.89rem; line-height: 1.55; opacity: 0.68; padding-left: 0.8rem;
  border-left: 2px solid rgba(127, 127, 127, 0.28);
  display: -webkit-box; -webkit-line-clamp: 6; -webkit-box-orient: vertical; overflow: hidden; }
.v-label { display: block; font-size: 0.72rem; font-weight: 650; text-transform: uppercase;
  letter-spacing: 0.06em; opacity: 0.75; margin-bottom: 0.15rem; }
.v-section { background: rgba(127, 127, 127, 0.14); }
.v-pied { font-size: 0.8rem; opacity: 0.5; margin-top: auto; }

/* Description dans la fiche : lisible, avec ses retours à la ligne */
.fiche-description { white-space: pre-line; line-height: 1.6; font-size: 0.97rem; }

/* ---------- Barre latérale translucide ---------- */
[data-testid="stSidebar"] > div:first-child {
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
}

/* ---------- Fenêtres (détail d'une candidature) ---------- */
[data-testid="stDialog"] div[role="dialog"] { border-radius: 1.4rem; }

/* ---------- Accessibilité ---------- */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; }
  [class*="st-key-carte_"]:hover { transform: none; }
  .stButton button:active, .stDownloadButton button:active { transform: none; }
}
@media (prefers-reduced-transparency: reduce) {
  [data-testid="stSidebar"] > div:first-child { backdrop-filter: none; -webkit-backdrop-filter: none; }
}
@media (prefers-contrast: more) {
  [class*="st-key-carte_"] { box-shadow: none; outline: 1px solid currentColor; }
}
</style>
"""


def appliquer() -> None:
    """À appeler une fois par affichage, avant les pages."""
    st.html(CSS)
