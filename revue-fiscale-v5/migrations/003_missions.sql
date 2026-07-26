-- 003 — Domaine abonne : contribuables et missions
-- Toute table creee ici porte tenant_id NOT NULL et sa politique RLS
-- DANS LA MEME MIGRATION. Une table cloisonnee sans politique est une fuite.

CREATE TABLE IF NOT EXISTS contribuable (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenant(id),
    denomination TEXT NOT NULL,
    ncc          TEXT,
    rccm         TEXT
);
CREATE INDEX IF NOT EXISTS idx_contribuable_tenant ON contribuable (tenant_id);

CREATE TABLE IF NOT EXISTS mission (
    id                     BIGSERIAL PRIMARY KEY,
    tenant_id              BIGINT NOT NULL REFERENCES tenant(id),
    contribuable_id        BIGINT NOT NULL REFERENCES contribuable(id),
    exercice               SMALLINT NOT NULL,
    profil                 JSONB NOT NULL DEFAULT '{}',
    version_referentiel_id BIGINT,          -- EPINGLAGE (FK ajoutee en 004)
    statut                 TEXT NOT NULL DEFAULT 'cadrage',
    cree_le                TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mission_tenant ON mission (tenant_id, exercice);

CREATE TABLE IF NOT EXISTS solde_compte (
    tenant_id  BIGINT NOT NULL REFERENCES tenant(id),
    mission_id BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    compte     TEXT   NOT NULL,
    libelle    TEXT,
    debit      NUMERIC(18,2) NOT NULL DEFAULT 0,
    credit     NUMERIC(18,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (mission_id, compte)
);

CREATE TABLE IF NOT EXISTS journal_audit (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenant(id),
    mission_id   BIGINT REFERENCES mission(id),
    horodatage   TIMESTAMPTZ NOT NULL DEFAULT now(),
    acteur       TEXT NOT NULL,
    action       TEXT NOT NULL,
    charge_utile JSONB NOT NULL DEFAULT '{}',
    hash_prec    TEXT,
    hash         TEXT NOT NULL
);

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['contribuable','mission','solde_compte','journal_audit']
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

-- Journal d audit : ecriture seule
REVOKE UPDATE, DELETE ON journal_audit FROM app_revue;

GRANT SELECT, INSERT, UPDATE, DELETE ON contribuable, mission, solde_compte TO app_revue;
GRANT SELECT, INSERT ON journal_audit TO app_revue;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_revue;
