-- 004 — Domaine editorial + auth + tables mission avancees + FK epinglage
-- Editorial : SANS tenant_id. Abonne : tenant_id + RLS dans la meme migration.

-- ── Auth : mot de passe sur utilisateur ───────────────────────────
ALTER TABLE utilisateur
    ADD COLUMN IF NOT EXISTS password_hash TEXT;

-- ── Domaine editorial (commun) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS version_referentiel (
    id           BIGSERIAL PRIMARY KEY,
    libelle      TEXT NOT NULL UNIQUE,
    publiee_le   TIMESTAMPTZ,
    publiee_par  TEXT,
    note         TEXT
);

CREATE TABLE IF NOT EXISTS regle (
    identifiant TEXT PRIMARY KEY,
    impot       TEXT NOT NULL,
    categorie   TEXT,
    libelle     TEXT NOT NULL,
    actif       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS regle_version (
    id                      BIGSERIAL PRIMARY KEY,
    regle_id                TEXT NOT NULL REFERENCES regle(identifiant),
    version_referentiel_id  BIGINT NOT NULL REFERENCES version_referentiel(id),
    reference_article       TEXT NOT NULL,
    reference_source        TEXT NOT NULL,
    millesime               SMALLINT NOT NULL,
    date_effet              DATE NOT NULL,
    date_fin                DATE,
    profils_applicables     JSONB NOT NULL DEFAULT '[]',
    comptes_declencheurs    TEXT[] NOT NULL DEFAULT '{}',
    nature                  TEXT NOT NULL,
    condition_declenchement TEXT NOT NULL,
    conditions_fond         TEXT,
    formule_plafonnement    TEXT,
    questions               JSONB NOT NULL DEFAULT '[]',
    expression_resultat     TEXT NOT NULL,
    niveau_risque           TEXT NOT NULL CHECK (niveau_risque IN ('faible','moyen','eleve')),
    a_confirmer             JSONB NOT NULL DEFAULT '[]',
    CHECK (date_fin IS NULL OR date_fin > date_effet)
);
CREATE INDEX IF NOT EXISTS idx_regle_version_vr ON regle_version (version_referentiel_id, regle_id);

CREATE TABLE IF NOT EXISTS effet_croise (
    source_id   BIGINT NOT NULL REFERENCES regle_version(id),
    cible_regle TEXT   NOT NULL REFERENCES regle(identifiant),
    type        TEXT   NOT NULL CHECK (type IN ('declenche','remet_en_cause','alimente','neutralise')),
    commentaire TEXT,
    PRIMARY KEY (source_id, cible_regle, type)
);

CREATE TABLE IF NOT EXISTS sanction (
    id           BIGSERIAL PRIMARY KEY,
    reference    TEXT NOT NULL,
    type         TEXT NOT NULL CHECK (type IN ('amende_fixe','majoration','interet_retard')),
    montant_fixe NUMERIC(18,2),
    taux         NUMERIC(6,4),
    base         TEXT,
    date_effet   DATE NOT NULL,
    date_fin     DATE
);

CREATE TABLE IF NOT EXISTS proposition_editoriale (
    id           BIGSERIAL PRIMARY KEY,
    deposee_le   TIMESTAMPTZ NOT NULL DEFAULT now(),
    source       TEXT NOT NULL DEFAULT 'copilote',
    statut       TEXT NOT NULL DEFAULT 'ouverte'
                 CHECK (statut IN ('ouverte','acceptee','corrigee','rejetee')),
    charge_utile JSONB NOT NULL DEFAULT '{}',
    sources      JSONB NOT NULL DEFAULT '[]',
    traitee_par  TEXT,
    traitee_le   TIMESTAMPTZ
);

-- Corpus editorial (etape 7)
CREATE TABLE IF NOT EXISTS source_document (
    id           BIGSERIAL PRIMARY KEY,
    titre        TEXT NOT NULL,
    type         TEXT NOT NULL,
    millesime    SMALLINT,
    fichier_uri  TEXT,
    ingestee_le  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS article_corpus (
    id                BIGSERIAL PRIMARY KEY,
    source_document_id BIGINT NOT NULL REFERENCES source_document(id) ON DELETE CASCADE,
    reference         TEXT NOT NULL,
    titre             TEXT,
    texte             TEXT NOT NULL,
    date_effet        DATE,
    date_fin          DATE,
    UNIQUE (source_document_id, reference)
);
CREATE INDEX IF NOT EXISTS idx_article_ref ON article_corpus (reference);

CREATE TABLE IF NOT EXISTS fragment_corpus (
    id         BIGSERIAL PRIMARY KEY,
    article_id BIGINT NOT NULL REFERENCES article_corpus(id) ON DELETE CASCADE,
    contenu    TEXT NOT NULL,
    rang       INT NOT NULL DEFAULT 0
);

-- ── Domaine abonne avance ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS execution (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  BIGINT NOT NULL REFERENCES tenant(id),
    mission_id BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    lancee_le  TIMESTAMPTZ NOT NULL DEFAULT now(),
    lancee_par TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_tenant ON execution (tenant_id);

CREATE TABLE IF NOT EXISTS conclusion (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT NOT NULL REFERENCES tenant(id),
    execution_id     BIGINT NOT NULL REFERENCES execution(id) ON DELETE CASCADE,
    regle_version_id BIGINT NOT NULL REFERENCES regle_version(id),
    montant          NUMERIC(18,2),
    sens             TEXT CHECK (sens IS NULL OR sens IN ('reintegration','deduction')),
    niveau_risque    TEXT NOT NULL,
    reponses         JSONB NOT NULL DEFAULT '{}',
    amendee_par      TEXT,
    commentaire      TEXT
);
CREATE INDEX IF NOT EXISTS idx_conclusion_tenant ON conclusion (tenant_id);

CREATE TABLE IF NOT EXISTS contestation (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenant(id),
    regle_id    TEXT   NOT NULL REFERENCES regle(identifiant),
    version_ref TEXT   NOT NULL,
    motif       TEXT   NOT NULL,
    statut      TEXT   NOT NULL DEFAULT 'ouverte',
    reponse     TEXT,
    traitee_le  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_contestation_tenant ON contestation (tenant_id);

CREATE TABLE IF NOT EXISTS rapport_fiabilisation (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  BIGINT NOT NULL REFERENCES tenant(id),
    mission_id BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    cree_le    TIMESTAMPTZ NOT NULL DEFAULT now(),
    statut     TEXT NOT NULL CHECK (statut IN ('ok','refuse')),
    anomalies  JSONB NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_fiab_tenant ON rapport_fiabilisation (tenant_id);

CREATE TABLE IF NOT EXISTS metrage_ia (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenant(id),
    horodatage    TIMESTAMPTZ NOT NULL DEFAULT now(),
    modele        TEXT NOT NULL,
    tokens_entree BIGINT NOT NULL DEFAULT 0,
    tokens_sortie BIGINT NOT NULL DEFAULT 0,
    cout_estime   NUMERIC(12,4) NOT NULL DEFAULT 0,
    usage         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrage_tenant ON metrage_ia (tenant_id);

-- Epinglage : FK version referentiel sur mission
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'mission_version_referentiel_id_fkey'
    ) THEN
        ALTER TABLE mission
            ADD CONSTRAINT mission_version_referentiel_id_fkey
            FOREIGN KEY (version_referentiel_id) REFERENCES version_referentiel(id);
    END IF;
END $$;

-- ── RLS tables abonne nouvelles ───────────────────────────────────
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'execution','conclusion','contestation','rapport_fiabilisation','metrage_ia'
    ]
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE  ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS %1$I_tenant ON %1$I', t);
        EXECUTE format($f$
            CREATE POLICY %1$I_tenant ON %1$I
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::BIGINT)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::BIGINT)
        $f$, t);
    END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON
    version_referentiel, regle, regle_version, effet_croise, sanction,
    proposition_editoriale, source_document, article_corpus, fragment_corpus,
    execution, conclusion, contestation, rapport_fiabilisation, metrage_ia
TO app_revue;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_revue;

-- Version initiale brouillon (epinglage possible apres publication)
INSERT INTO version_referentiel (libelle, note)
VALUES ('v2026.0-brouillon', 'Version initiale scaffold — a publier apres chargement des regles')
ON CONFLICT (libelle) DO NOTHING;

-- Lookup login : SECURITY DEFINER (owner = postgres) pour lire email sans
-- contexte tenant, sans BYPASSRLS sur app_revue. Ne renvoie qu une ligne.
CREATE OR REPLACE FUNCTION auth_lookup_utilisateur(p_email TEXT)
RETURNS TABLE (
    id BIGINT,
    tenant_id BIGINT,
    email TEXT,
    role TEXT,
    actif BOOLEAN,
    password_hash TEXT
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT u.id, u.tenant_id, u.email, u.role, u.actif, u.password_hash
    FROM utilisateur u
    WHERE u.email = lower(trim(p_email))
    LIMIT 1;
$$;

REVOKE ALL ON FUNCTION auth_lookup_utilisateur(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_lookup_utilisateur(TEXT) TO app_revue;
