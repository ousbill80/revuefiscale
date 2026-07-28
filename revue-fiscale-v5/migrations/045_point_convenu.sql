-- 045 — Points convenus du compte-rendu de restitution : suivi.
-- Le compte-rendu de réunion (044) consigne les points convenus avec le
-- client en texte libre, mais rien ne permet de suivre s'ils ont été
-- traités ensuite. Cette table stocke UN point par ligne, saisi par le
-- fiscaliste, avec un statut de suivi explicite ('a_faire' par défaut,
-- puis 'fait' ou 'abandonne' sur clic humain). RLS stricte.

CREATE TABLE IF NOT EXISTS point_convenu (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenant(id),
    mission_id    BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    libelle       TEXT NOT NULL,
    statut        TEXT NOT NULL DEFAULT 'a_faire'
                  CHECK (statut IN ('a_faire', 'fait', 'abandonne')),
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    mis_a_jour_le TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_point_convenu_mission
    ON point_convenu (tenant_id, mission_id);

COMMENT ON TABLE point_convenu IS
    'Suivi des points convenus avec le client lors de la restitution.';
COMMENT ON COLUMN point_convenu.libelle IS
    'Point convenu — texte libre saisi par le fiscaliste (≤ 500 chars).';
COMMENT ON COLUMN point_convenu.statut IS
    'Suivi humain : a_faire (défaut), fait, abandonne.';

DO $$
DECLARE t TEXT := 'point_convenu';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON point_convenu TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE point_convenu_id_seq TO app_revue;
