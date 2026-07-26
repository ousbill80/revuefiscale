-- 002 — Plateforme : tenants, utilisateurs, quotas
-- Domaine ABONNE : tenant_id NOT NULL + RLS activee ET forcee.

CREATE TABLE IF NOT EXISTS tenant (
    id           BIGSERIAL PRIMARY KEY,
    denomination TEXT NOT NULL,
    type         TEXT NOT NULL CHECK (type IN ('cabinet','entreprise')),
    palier       TEXT NOT NULL CHECK (palier IN ('essentiel','standard','premium','souverain')),
    statut       TEXT NOT NULL DEFAULT 'actif',
    cree_le      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS utilisateur (
    id        BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenant(id),
    email     TEXT NOT NULL UNIQUE,
    role      TEXT NOT NULL CHECK (role IN ('admin','reviseur','lecteur')),
    actif     BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_utilisateur_tenant ON utilisateur (tenant_id);

CREATE TABLE IF NOT EXISTS quota (
    tenant_id          BIGINT NOT NULL REFERENCES tenant(id),
    periode            DATE   NOT NULL,
    missions_incluses  INT    NOT NULL,
    missions_utilisees INT    NOT NULL DEFAULT 0,
    appels_modele      INT    NOT NULL DEFAULT 0,
    tokens_entree      BIGINT NOT NULL DEFAULT 0,
    tokens_sortie      BIGINT NOT NULL DEFAULT 0,
    cout_estime        NUMERIC(12,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, periode)
);

-- ── Politiques RLS ────────────────────────────────────────────────
-- USING filtre les lectures, WITH CHECK empeche d ecrire chez un autre.
-- Contexte absent -> current_setting(..., true) renvoie NULL -> zero ligne.

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['utilisateur','quota']
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

GRANT SELECT, INSERT, UPDATE, DELETE ON tenant, utilisateur, quota TO app_revue;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_revue;
