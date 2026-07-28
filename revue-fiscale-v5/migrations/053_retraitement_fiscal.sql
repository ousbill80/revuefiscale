-- 053 — Tableau de passage résultat comptable → résultat fiscal.
-- Aucune table ne stockait les RETRAITEMENTS EXTRA-COMPTABLES saisis
-- par le fiscaliste (réintégrations / déductions, libellé libre,
-- référence CGI facultative) ni le REPORT DÉFICITAIRE ANTÉRIEUR :
-- impossible de dérouler le passage du résultat comptable (balance)
-- au résultat fiscal et à l'IS théorique. Le moteur n'expose pas ce
-- passage — les retraitements sont SAISIS par le fiscaliste.
-- RLS stricte dans la même migration (pattern 045-052).

CREATE TABLE IF NOT EXISTS retraitement_fiscal (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenant(id),
    mission_id    BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    sens          TEXT NOT NULL
                  CHECK (sens IN ('reintegration', 'deduction')),
    libelle       TEXT NOT NULL CHECK (btrim(libelle) <> ''),
    montant       NUMERIC(18,2) NOT NULL CHECK (montant >= 0),
    reference_cgi TEXT,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    mis_a_jour_le TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_retraitement_fiscal_mission
    ON retraitement_fiscal (tenant_id, mission_id);

COMMENT ON TABLE retraitement_fiscal IS
    'Retraitements extra-comptables du passage résultat comptable → résultat fiscal (réintégrations / déductions) — saisie humaine.';
COMMENT ON COLUMN retraitement_fiscal.sens IS
    'Sens du retraitement : reintegration (ajoute) ou deduction (retranche).';
COMMENT ON COLUMN retraitement_fiscal.reference_cgi IS
    'Référence CGI ivoirien — facultative (ex. art. 18).';

CREATE TABLE IF NOT EXISTS report_deficitaire_mission (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenant(id),
    mission_id    BIGINT NOT NULL UNIQUE REFERENCES mission(id) ON DELETE CASCADE,
    montant       NUMERIC(18,2) NOT NULL CHECK (montant >= 0),
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    mis_a_jour_le TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE report_deficitaire_mission IS
    'Report déficitaire antérieur saisi par le fiscaliste — une valeur par mission, imputée dans la limite du bénéfice fiscal.';

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['retraitement_fiscal', 'report_deficitaire_mission'] LOOP
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

GRANT SELECT, INSERT, UPDATE, DELETE ON retraitement_fiscal TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE retraitement_fiscal_id_seq TO app_revue;
GRANT SELECT, INSERT, UPDATE, DELETE ON report_deficitaire_mission TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE report_deficitaire_mission_id_seq TO app_revue;
