-- 051 — Acomptes IS versés + IS dû estimé : position de solde de l'exercice.
-- Aucune table ne stockait les ACOMPTES D'IMPÔT VERSÉS dans l'exercice
-- (acomptes IS, retenues à la source, crédits reportés) ni l'IS DÛ
-- ESTIMÉ par le fiscaliste : impossible de projeter la position de
-- solde (solde à payer ou crédit d'impôt à reporter). Le moteur
-- n'expose pas d'IS estimé — le dû est SAISI par le fiscaliste.
-- RLS stricte dans la même migration (pattern 045-050).

CREATE TABLE IF NOT EXISTS acompte_impot (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           BIGINT NOT NULL REFERENCES tenant(id),
    mission_id          BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    nature              TEXT NOT NULL
                        CHECK (nature IN ('acompte_is', 'retenue_source',
                                          'credit_reporte')),
    date_versement      DATE NOT NULL,
    montant             NUMERIC(18,2) NOT NULL CHECK (montant >= 0),
    reference_quittance TEXT,
    cree_le             TIMESTAMPTZ NOT NULL DEFAULT now(),
    mis_a_jour_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (mission_id, nature, date_versement)
);

CREATE INDEX IF NOT EXISTS idx_acompte_impot_mission
    ON acompte_impot (tenant_id, mission_id);

COMMENT ON TABLE acompte_impot IS
    'Acomptes d''impôt versés dans l''exercice (acompte IS, retenue à la source, crédit reporté) — saisie humaine.';
COMMENT ON COLUMN acompte_impot.nature IS
    'Nature du versement : acompte_is, retenue_source ou credit_reporte.';
COMMENT ON COLUMN acompte_impot.reference_quittance IS
    'Référence de quittance DGI — facultative.';

CREATE TABLE IF NOT EXISTS is_du_estime_mission (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenant(id),
    mission_id    BIGINT NOT NULL UNIQUE REFERENCES mission(id) ON DELETE CASCADE,
    montant       NUMERIC(18,2) NOT NULL CHECK (montant >= 0),
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    mis_a_jour_le TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE is_du_estime_mission IS
    'IS dû estimé de l''exercice, saisi par le fiscaliste (le moteur n''expose pas d''IS estimé) — une valeur par mission.';

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['acompte_impot', 'is_du_estime_mission'] LOOP
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

GRANT SELECT, INSERT, UPDATE, DELETE ON acompte_impot TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE acompte_impot_id_seq TO app_revue;
GRANT SELECT, INSERT, UPDATE, DELETE ON is_du_estime_mission TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE is_du_estime_mission_id_seq TO app_revue;
