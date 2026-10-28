"""Base de données SQLite : création des tables et connexion."""
import sqlite3
from pathlib import Path

# À augmenter quand on modifie la structure des tables, en ajoutant la
# modification correspondante dans MIGRATIONS (pour mettre à jour les bases existantes).
VERSION_SCHEMA = 3

MIGRATIONS = {
    2: [
        "ALTER TABLE offres ADD COLUMN site_origine TEXT",
        "ALTER TABLE runs ADD COLUMN nb_requetes INTEGER NOT NULL DEFAULT 0",
    ],
    3: [
        "ALTER TABLE offres ADD COLUMN poste_ia_data INTEGER",
    ],
}

SCHEMA = """
-- Journal des passages : une ligne par source et par passage.
-- Toutes les lignes d'un même passage partagent le même passage_id.
-- Le scoring IA a sa propre ligne (source = 'scoring') avec les tokens et le coût.
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id      INTEGER NOT NULL,
    date_debut      TEXT    NOT NULL,
    date_fin        TEXT,
    declenchement   TEXT    NOT NULL CHECK (declenchement IN ('manuel', 'auto')),
    source          TEXT    NOT NULL,
    nb_offres       INTEGER NOT NULL DEFAULT 0,
    nb_nouvelles    INTEGER NOT NULL DEFAULT 0,
    nb_requetes     INTEGER NOT NULL DEFAULT 0,  -- requêtes envoyées (suivi des quotas d'API)
    erreurs         TEXT,
    tokens_entree   INTEGER NOT NULL DEFAULT 0,
    tokens_sortie   INTEGER NOT NULL DEFAULT 0,
    cout_usd        REAL    NOT NULL DEFAULT 0
);

-- Toutes les offres collectées, normalisées puis notées.
CREATE TABLE IF NOT EXISTS offres (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Origine
    source              TEXT    NOT NULL,   -- france_travail, adzuna, gmail_linkedin, ...
    source_id           TEXT    NOT NULL,   -- identifiant de l'offre chez la source
    passage_id          INTEGER,            -- passage où l'offre a été vue pour la première fois
    date_collecte       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),

    -- Données normalisées
    titre               TEXT    NOT NULL,
    entreprise          TEXT,
    type_contrat        TEXT,               -- stage ou cdd
    lieu                TEXT,
    departement         TEXT,
    teletravail         TEXT,               -- sur site, hybride, full remote
    date_publication    TEXT,
    duree               TEXT,               -- texte tel qu'affiché
    duree_mois          REAL,
    date_debut          TEXT,
    gratification       TEXT,
    lien                TEXT,
    description         TEXT,
    contact             TEXT,               -- recruteur ou manager, s'il apparaît
    site_origine        TEXT,               -- site qui publie l'offre (HelloWork, LinkedIn...) pour les agrégateurs

    -- Dédoublonnage
    empreinte           TEXT,               -- clé approximative entreprise + titre + lieu
    doublon_de          INTEGER REFERENCES offres(id),

    -- Pré-filtre
    exclusion_prefiltre TEXT,               -- raison de l'exclusion, NULL si gardée

    -- Scoring IA
    score               INTEGER CHECK (score BETWEEN 0 AND 10),
    categorie           TEXT,               -- À postuler vite, À regarder, Bof
    section             TEXT,               -- Santé, Hors santé mais intéressant, À négocier
    resume              TEXT,
    pourquoi            TEXT,
    duree_ia            TEXT,
    date_debut_ia       TEXT,
    exclusion_ia        TEXT,
    poste_ia_data       INTEGER,            -- 1 si l'IA juge que c'est un poste IA / data (sert aux alertes)
    date_scoring        TEXT,

    -- Indicateurs
    vue                 INTEGER NOT NULL DEFAULT 0,
    notifiee            INTEGER NOT NULL DEFAULT 0,
    pas_interesse       INTEGER NOT NULL DEFAULT 0,

    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_offres_empreinte ON offres (empreinte);
CREATE INDEX IF NOT EXISTS idx_offres_passage   ON offres (passage_id);
CREATE INDEX IF NOT EXISTS idx_offres_score     ON offres (score);

-- Suivi des candidatures (liées à une offre, ou ajoutées à la main).
CREATE TABLE IF NOT EXISTS candidatures (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    offre_id            INTEGER REFERENCES offres(id) ON DELETE SET NULL,
    entreprise          TEXT,
    poste               TEXT,
    lien                TEXT,
    statut              TEXT    NOT NULL DEFAULT 'à postuler'
                        CHECK (statut IN ('à postuler', 'postulé', 'relancé',
                                          'entretien', 'refus', 'accepté')),
    date_creation       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    date_candidature    TEXT,
    date_relance        TEXT,
    date_maj            TEXT,
    notes               TEXT
);

-- Offres marquées "pas intéressé", réutilisées comme exemples par le scoring.
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    offre_id    INTEGER NOT NULL REFERENCES offres(id) ON DELETE CASCADE,
    raison      TEXT,
    date        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


def connecter(chemin: Path) -> sqlite3.Connection:
    """Ouvre la base (et crée son dossier si besoin)."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(chemin)
    conn.row_factory = sqlite3.Row  # accès aux colonnes par leur nom : ligne["titre"]
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialiser(conn: sqlite3.Connection) -> None:
    """Crée les tables d'une base neuve, ou met à jour une base existante."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        conn.executescript(SCHEMA)  # base neuve : directement la dernière version
    else:
        for numero in range(version + 1, VERSION_SCHEMA + 1):
            for instruction in MIGRATIONS.get(numero, []):
                conn.execute(instruction)
        conn.executescript(SCHEMA)  # crée les éventuelles nouvelles tables ou index
    conn.execute(f"PRAGMA user_version = {VERSION_SCHEMA}")
    conn.commit()


def nouveau_passage_id(conn: sqlite3.Connection) -> int:
    """Numéro du prochain passage (1, 2, 3...)."""
    return conn.execute("SELECT COALESCE(MAX(passage_id), 0) + 1 FROM runs").fetchone()[0]


def enregistrer_offres(conn: sqlite3.Connection, offres: list[dict], passage_id: int) -> int:
    """Ajoute les offres pas encore connues (même source + même source_id = déjà connue).
    Renvoie le nombre d'offres réellement nouvelles."""
    nb_nouvelles = 0
    for offre in offres:
        colonnes = list(offre) + ["passage_id"]
        valeurs = list(offre.values()) + [passage_id]
        curseur = conn.execute(
            f"INSERT INTO offres ({', '.join(colonnes)}) VALUES ({', '.join('?' * len(colonnes))}) "
            "ON CONFLICT (source, source_id) DO NOTHING",
            valeurs,
        )
        nb_nouvelles += curseur.rowcount
    conn.commit()
    return nb_nouvelles


def journaliser_run(conn: sqlite3.Connection, **valeurs) -> None:
    """Ajoute une ligne au journal des passages (table runs)."""
    colonnes = list(valeurs)
    conn.execute(
        f"INSERT INTO runs ({', '.join(colonnes)}) VALUES ({', '.join('?' * len(colonnes))})",
        list(valeurs.values()),
    )
    conn.commit()


def compter_lignes(conn: sqlite3.Connection) -> dict[str, int]:
    """Nombre de lignes de chaque table, pour vérifier l'état de la base."""
    tables = [
        ligne["name"]
        for ligne in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
