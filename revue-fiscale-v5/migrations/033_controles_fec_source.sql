-- 033 — Contrôles de vraisemblance FEC de la source active d'une mission
-- Restitués à l'expert (fiabilité de la source), jamais bloquants pour
-- l'import. Un enregistrement par import FEC ; la restitution lit le
-- dernier. Détail jsonb : liste de contrôles
-- [{code, libelle, statut ok|alerte, compteur, echantillon[{ligne, valeur}]}].
-- RLS stricte : tenant_id NOT NULL.

CREATE TABLE IF NOT EXISTS controle_source_fec (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenant(id),
    mission_id  BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    exercice    SMALLINT NOT NULL,
    controles   JSONB NOT NULL,
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_controle_source_fec_mission
    ON controle_source_fec (tenant_id, mission_id, cree_le DESC);

COMMENT ON TABLE controle_source_fec IS
    'Contrôles de vraisemblance FEC (informationnels) au moment de l''import de la source active.';
COMMENT ON COLUMN controle_source_fec.controles IS
    'Liste jsonb [{code, libelle, statut, compteur, echantillon[{ligne, valeur}]}] — max 5 occurrences par échantillon.';
COMMENT ON COLUMN controle_source_fec.exercice IS
    'Exercice de la mission au moment du contrôle (référence des dates hors exercice).';

DO $$
DECLARE t TEXT := 'controle_source_fec';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON controle_source_fec TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE controle_source_fec_id_seq TO app_revue;
