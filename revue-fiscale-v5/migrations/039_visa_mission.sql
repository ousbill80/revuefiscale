-- 039 — Visas de supervision par mission
-- Normes d'exercice professionnel : la supervision hiérarchique exige des
-- visas formels par phase — le préparateur atteste son travail, le
-- réviseur revoit, l'associé signe. Un visa par (phase, rôle) au plus.
-- L'ordre hiérarchique (préparateur → réviseur → associé) est contrôlé
-- côté application. RLS stricte.

CREATE TABLE IF NOT EXISTS visa_mission (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   BIGINT NOT NULL,
    mission_id  BIGINT NOT NULL REFERENCES mission(id),
    phase       TEXT NOT NULL CHECK (
        phase IN ('cadrage', 'collecte', 'controles', 'restitution')
    ),
    role        TEXT NOT NULL CHECK (
        role IN ('preparateur', 'reviseur', 'associe')
    ),
    vise_par    TEXT NOT NULL,
    commentaire TEXT NULL,
    vise_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, mission_id, phase, role)
);

CREATE INDEX IF NOT EXISTS idx_visa_mission_mission
    ON visa_mission (tenant_id, mission_id);

COMMENT ON TABLE visa_mission IS
    'Visas de supervision par mission et par phase (préparateur, réviseur, associé).';
COMMENT ON COLUMN visa_mission.phase IS
    'Phase visée : cadrage, collecte, controles, restitution.';
COMMENT ON COLUMN visa_mission.role IS
    'Rang hiérarchique du visa : preparateur < reviseur < associe.';

DO $$
DECLARE t TEXT := 'visa_mission';
BEGIN
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE  ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS %1$I_tenant ON %1$I', t);
    EXECUTE format($f$
        CREATE POLICY %1$I_tenant ON %1$I
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::BIGINT)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::BIGINT)
    $f$, t);
END $$;

GRANT SELECT, INSERT, DELETE ON visa_mission TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE visa_mission_id_seq TO app_revue;
