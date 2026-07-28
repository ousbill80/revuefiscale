-- 048 — Déclarations TVA saisies : rapprochement déclaré / comptabilisé.
-- Aucune table ne stockait la TVA DÉCLARÉE (les déclarations déposées à
-- la DGI) : impossible de la rapprocher de la TVA COMPTABILISÉE
-- (comptes 443x/445x de la balance importée dans solde_compte). Cette
-- table stocke UNE déclaration par période mensuelle (AAAA-MM), saisie
-- par le fiscaliste depuis la déclaration papier/e-impôts du client.
-- RLS stricte dans la même migration (pattern 045-047).

CREATE TABLE IF NOT EXISTS declaration_tva (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      BIGINT NOT NULL REFERENCES tenant(id),
    mission_id     BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    periode        TEXT NOT NULL
                   CHECK (periode ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    tva_collectee  NUMERIC(18,2) NOT NULL DEFAULT 0,
    tva_deductible NUMERIC(18,2) NOT NULL DEFAULT 0,
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    mis_a_jour_le  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (mission_id, periode)
);

CREATE INDEX IF NOT EXISTS idx_declaration_tva_mission
    ON declaration_tva (tenant_id, mission_id);

COMMENT ON TABLE declaration_tva IS
    'TVA déclarée (DGI) par période mensuelle — saisie humaine, rapprochée de la balance.';
COMMENT ON COLUMN declaration_tva.periode IS
    'Période mensuelle de la déclaration au format AAAA-MM.';
COMMENT ON COLUMN declaration_tva.tva_collectee IS
    'TVA collectée (facturée) portée sur la déclaration de la période, en FCFA.';
COMMENT ON COLUMN declaration_tva.tva_deductible IS
    'TVA déductible (récupérable) portée sur la déclaration de la période, en FCFA.';

DO $$
DECLARE t TEXT := 'declaration_tva';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON declaration_tva TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE declaration_tva_id_seq TO app_revue;
