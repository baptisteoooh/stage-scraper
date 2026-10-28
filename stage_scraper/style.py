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
[data-testid="stMainBlockContainer"] { padding-top: 2.5rem; max-width: 1400px; }

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
  border-radius: 1.1rem !important;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04), 0 4px 14px rgba(0, 0, 0, 0.05);
  transition: transform 160ms ease-out, box-shadow 160ms ease-out;
}
[class*="st-key-carte_"]:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05), 0 10px 24px rgba(0, 0, 0, 0.08);
}
[class*="st-key-carte_"] p { margin-bottom: 0.15rem; }

/* En-têtes de colonnes du suivi des candidatures */
[class*="st-key-colonne_"] { gap: 0.6rem; }
.etape-titre { display: flex; align-items: baseline; gap: 0.45rem; margin: 0 0 0.35rem 0.15rem;
  font-weight: 650; letter-spacing: -0.01em; }
.etape-compte { font-weight: 500; opacity: 0.55; font-variant-numeric: tabular-nums; }
.carte-entreprise { font-weight: 650; letter-spacing: -0.01em; font-size: 1.02rem; }
.carte-poste { opacity: 0.8; font-size: 0.92rem; line-height: 1.35;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.carte-meta { opacity: 0.6; font-size: 0.8rem; font-variant-numeric: tabular-nums; }

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
