-- 038 — Temps passés par mission
-- Chaque collaborateur saisit ses temps (phase, date, heures) par mission.
-- L'associé pilote la rentabilité : total heures, répartition par phase et
-- par collaborateur, valorisation au taux horaire. RLS stricte.

CREATE TABLE IF NOT EXISTS temps_mission (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL,
    mission_id    BIGINT NOT NULL REFERENCES mission(id),
    collaborateur TEXT NOT NULL,
    phase         TEXT NOT NULL CHECK (
        phase IN ('cadrage', 'collecte', 'controles', 'restitution', 'suivi')
    ),
    date_jour     DATE NOT NULL,
    heures        NUMERIC(5,2) NOT NULL CHECK (heures > 0 AND heures <= 24),
    note          TEXT NULL,
    saisi_le      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_temps_mission_mission
    ON temps_mission (tenant_id, mission_id);

COMMENT ON TABLE temps_mission IS
    'Temps passés par mission (pilotage de la rentabilité cabinet).';
COMMENT ON COLUMN temps_mission.phase IS
    'Phase de la mission : cadrage, collecte, controles, restitution, suivi.';
COMMENT ON COLUMN temps_mission.heures IS
    'Heures saisies pour la journée (0 < heures <= 24).';

DO $$
DECLARE t TEXT := 'temps_mission';
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

GRANT SELECT, INSERT, DELETE ON temps_mission TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE temps_mission_id_seq TO app_revue;
