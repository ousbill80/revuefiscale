-- 052 — Déclarations de salaires saisies : rapprochement déclaré / comptabilisé.
-- Aucune table ne stockait les DÉCLARATIONS DE SALAIRES déposées (masse
-- salariale brute, ITS retenu — part salariale —, contribution
-- employeur) : impossible de les rapprocher de la MASSE SALARIALE
-- COMPTABILISÉE (comptes 66x « Charges de personnel » de la balance
-- importée dans solde_compte). Cette table stocke UNE déclaration par
-- période mensuelle (AAAA-MM), saisie par le fiscaliste depuis la
-- déclaration papier/e-impôts du client. RLS stricte dans la même
-- migration (pattern 045-051).

CREATE TABLE IF NOT EXISTS declaration_salaires (
    id                     BIGSERIAL PRIMARY KEY,
    tenant_id              BIGINT NOT NULL REFERENCES tenant(id),
    mission_id             BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    periode                TEXT NOT NULL
                           CHECK (periode ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    masse_salariale_brute  NUMERIC(18,2) NOT NULL DEFAULT 0,
    its_retenu             NUMERIC(18,2) NOT NULL DEFAULT 0,
    contribution_employeur NUMERIC(18,2) NOT NULL DEFAULT 0,
    cree_le                TIMESTAMPTZ NOT NULL DEFAULT now(),
    mis_a_jour_le          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (mission_id, periode)
);

CREATE INDEX IF NOT EXISTS idx_declaration_salaires_mission
    ON declaration_salaires (tenant_id, mission_id);

COMMENT ON TABLE declaration_salaires IS
    'Déclarations de salaires déposées (DGI) par période mensuelle — saisie humaine, rapprochée de la balance.';
COMMENT ON COLUMN declaration_salaires.periode IS
    'Période mensuelle de la déclaration au format AAAA-MM.';
COMMENT ON COLUMN declaration_salaires.masse_salariale_brute IS
    'Masse salariale brute portée sur la déclaration de la période, en FCFA.';
COMMENT ON COLUMN declaration_salaires.its_retenu IS
    'ITS retenu (part salariale) porté sur la déclaration de la période, en FCFA.';
COMMENT ON COLUMN declaration_salaires.contribution_employeur IS
    'Contribution employeur sur salaires portée sur la déclaration de la période, en FCFA.';

DO $$
DECLARE t TEXT := 'declaration_salaires';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON declaration_salaires TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE declaration_salaires_id_seq TO app_revue;
