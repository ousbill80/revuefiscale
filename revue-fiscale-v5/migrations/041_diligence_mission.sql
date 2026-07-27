-- 041 — Programme de travail par mission (diligences)
-- Normes d'exercice : chaque mission de revue fiscale suit un programme
-- de travail standard — une liste de diligences par phase (cadrage,
-- collecte, controles, restitution, suivi) que le collaborateur coche au
-- fur et à mesure. Le %% d'avancement par phase complète les visas de
-- supervision (039) : l'associé vise une phase dont les diligences sont
-- faites. RLS stricte.

CREATE TABLE IF NOT EXISTS diligence_mission (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   BIGINT NOT NULL,
    mission_id  BIGINT NOT NULL REFERENCES mission(id),
    phase       TEXT NOT NULL CHECK (
        phase IN ('cadrage', 'collecte', 'controles', 'restitution', 'suivi')
    ),
    code        TEXT NOT NULL,
    libelle     TEXT NOT NULL,
    fait        BOOLEAN NOT NULL DEFAULT false,
    fait_par    TEXT NULL,
    fait_le     TIMESTAMPTZ NULL,
    UNIQUE (tenant_id, mission_id, code)
);

CREATE INDEX IF NOT EXISTS idx_diligence_mission_mission
    ON diligence_mission (tenant_id, mission_id);

COMMENT ON TABLE diligence_mission IS
    'Programme de travail par mission : diligences standard par phase, cochées au fil de l''exécution.';
COMMENT ON COLUMN diligence_mission.code IS
    'Code de la diligence standard (CAD-01, COL-01, CTL-01, RES-01, SUI-01…).';
COMMENT ON COLUMN diligence_mission.fait IS
    'Diligence effectuée — fait_par / fait_le renseignés lorsqu''elle est cochée.';

DO $$
DECLARE t TEXT := 'diligence_mission';
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

GRANT SELECT, INSERT, UPDATE ON diligence_mission TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE diligence_mission_id_seq TO app_revue;
