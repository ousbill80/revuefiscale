-- 044 — Compte-rendu de la réunion de restitution
-- Après la réunion avec le client (préparée par l'ordre du jour), le
-- fiscaliste consigne un compte-rendu simple et traçable : date de la
-- réunion, participants, points convenus. UN SEUL compte-rendu par
-- mission (UPSERT sur clic explicite « Enregistrer »). RLS stricte.

CREATE TABLE IF NOT EXISTS compte_rendu_reunion (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT NOT NULL REFERENCES tenant(id),
    mission_id      BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    date_reunion    DATE NOT NULL,
    participants    TEXT NOT NULL,
    points_convenus TEXT NOT NULL,
    maj_le          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, mission_id)
);

CREATE INDEX IF NOT EXISTS idx_compte_rendu_reunion_mission
    ON compte_rendu_reunion (tenant_id, mission_id);

COMMENT ON TABLE compte_rendu_reunion IS
    'Compte-rendu de la réunion de restitution — un seul par mission.';
COMMENT ON COLUMN compte_rendu_reunion.date_reunion IS
    'Date effective de la réunion (jamais future à l''enregistrement).';
COMMENT ON COLUMN compte_rendu_reunion.participants IS
    'Participants à la réunion — texte libre saisi par le fiscaliste.';
COMMENT ON COLUMN compte_rendu_reunion.points_convenus IS
    'Points convenus avec le client — texte libre saisi par le fiscaliste.';

DO $$
DECLARE t TEXT := 'compte_rendu_reunion';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON compte_rendu_reunion TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE compte_rendu_reunion_id_seq TO app_revue;
