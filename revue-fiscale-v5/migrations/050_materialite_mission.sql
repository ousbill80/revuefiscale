-- 050 — Seuil de matérialité retenu par mission (ciblage des travaux).
-- Le seuil de signification PROPOSÉ se calcule de façon déterministe
-- depuis la balance (solde_compte) selon les référentiels d'audit
-- usuels (% CA classe 70, % total bilan, % résultat). Cette table ne
-- stocke QUE la décision HUMAINE : le seuil RETENU par le fiscaliste
-- (proposition confirmée ou montant manuel), une ligne par mission.
-- RLS stricte dans la même migration (pattern 045-049).

CREATE TABLE IF NOT EXISTS materialite_mission (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenant(id),
    mission_id    BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    seuil_retenu  NUMERIC(18,2) NOT NULL CHECK (seuil_retenu > 0),
    source        TEXT NOT NULL CHECK (source IN ('proposition', 'manuel')),
    referentiel   TEXT NOT NULL DEFAULT '',
    commentaire   TEXT NOT NULL DEFAULT '',
    decide_par    TEXT NOT NULL,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    mis_a_jour_le TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (mission_id)
);

CREATE INDEX IF NOT EXISTS idx_materialite_mission_tenant
    ON materialite_mission (tenant_id, mission_id);

COMMENT ON TABLE materialite_mission IS
    'Seuil de matérialité RETENU par mission — décision humaine (proposition confirmée ou seuil manuel).';
COMMENT ON COLUMN materialite_mission.seuil_retenu IS
    'Seuil de signification retenu pour cibler les travaux, en FCFA (> 0).';
COMMENT ON COLUMN materialite_mission.source IS
    'proposition = seuil proposé confirmé ; manuel = montant saisi par le fiscaliste.';
COMMENT ON COLUMN materialite_mission.referentiel IS
    'Référentiel de la proposition confirmée (ca, resultat, bilan) — vide si manuel.';

DO $$
DECLARE t TEXT := 'materialite_mission';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON materialite_mission TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE materialite_mission_id_seq TO app_revue;
