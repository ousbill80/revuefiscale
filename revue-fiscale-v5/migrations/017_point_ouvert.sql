-- 017 — Points ouverts inter-missions (domaine abonné)
-- Lot 4 engagement : suivi recommandations N→N+1 — hors calcul fiscal.
-- tenant_id NOT NULL + RLS (même pattern que piece_mission).

CREATE TABLE IF NOT EXISTS point_ouvert (
    id                 BIGSERIAL PRIMARY KEY,
    tenant_id          BIGINT NOT NULL REFERENCES tenant(id),
    contribuable_id    BIGINT NOT NULL REFERENCES contribuable(id),
    mission_source_id  BIGINT REFERENCES mission(id) ON DELETE SET NULL,
    conclusion_id      BIGINT REFERENCES conclusion(id) ON DELETE SET NULL,
    texte              TEXT NOT NULL,
    statut             TEXT NOT NULL DEFAULT 'ouvert'
                       CHECK (statut IN ('ouvert', 'repris', 'clos')),
    mission_reprise_id BIGINT REFERENCES mission(id) ON DELETE SET NULL,
    cree_le            TIMESTAMPTZ NOT NULL DEFAULT now(),
    maj_le             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_point_ouvert_tenant_contrib
    ON point_ouvert (tenant_id, contribuable_id, statut);

CREATE INDEX IF NOT EXISTS idx_point_ouvert_mission_source
    ON point_ouvert (mission_source_id)
    WHERE mission_source_id IS NOT NULL;

COMMENT ON TABLE point_ouvert IS
    'Recommandations / points à reprendre — hors moteur fiscal.';
COMMENT ON COLUMN point_ouvert.statut IS
    'ouvert = à traiter ; repris = vu en mission N+1 ; clos = soldé.';

DO $$
DECLARE t TEXT := 'point_ouvert';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON point_ouvert TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE point_ouvert_id_seq TO app_revue;
