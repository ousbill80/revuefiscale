-- 043 — Suivi du plan d'actions post-revue
-- Une ligne par action du plan sur laquelle le fiscaliste a pris une
-- décision explicite : « retenue », « écartée » ou « faite ». Le plan
-- lui-même reste DÉRIVÉ à la volée (consultatif, non persisté) ; cette
-- table ne stocke QUE les décisions humaines saisies par-dessus.
-- RLS stricte.

CREATE TABLE IF NOT EXISTS suivi_plan_actions (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  BIGINT NOT NULL REFERENCES tenant(id),
    mission_id BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    cle_action TEXT NOT NULL,
    decision   TEXT NOT NULL
               CHECK (decision IN ('retenue', 'ecartee', 'faite')),
    note       TEXT,
    maj_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, mission_id, cle_action)
);

CREATE INDEX IF NOT EXISTS idx_suivi_plan_actions_mission
    ON suivi_plan_actions (tenant_id, mission_id);

COMMENT ON TABLE suivi_plan_actions IS
    'Suivi du plan d''actions — décision du fiscaliste par action dérivée.';
COMMENT ON COLUMN suivi_plan_actions.cle_action IS
    'Identifiant stable de l''action dérivée : risque:{risque_id}.';
COMMENT ON COLUMN suivi_plan_actions.decision IS
    'Décision humaine : retenue (à mettre en œuvre), ecartee, faite.';

DO $$
DECLARE t TEXT := 'suivi_plan_actions';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON suivi_plan_actions TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE suivi_plan_actions_id_seq TO app_revue;
