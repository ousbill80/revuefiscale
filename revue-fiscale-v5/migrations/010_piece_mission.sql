-- 010 — Pièces de mission (source active vs annexes)
-- Domaine abonné : tenant_id NOT NULL + RLS dans la même migration.
-- Une seule source_active par mission ; les annexes n'écrasent pas solde_compte.

CREATE TABLE IF NOT EXISTS piece_mission (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT NOT NULL REFERENCES tenant(id),
    mission_id       BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    type_piece       TEXT NOT NULL
                     CHECK (type_piece IN (
                         'balance',
                         'etats_financiers',
                         'grand_livre',
                         'fec',
                         'autre'
                     )),
    role             TEXT NOT NULL
                     CHECK (role IN ('source_active', 'annexe')),
    nom_fichier      TEXT NOT NULL,
    chemin_stockage  TEXT NOT NULL,
    taille_octets    BIGINT,
    content_type     TEXT,
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_piece_mission_tenant
    ON piece_mission (tenant_id, mission_id);

CREATE INDEX IF NOT EXISTS idx_piece_mission_mission
    ON piece_mission (mission_id, role);

-- Une seule source active alimentant solde_compte par mission.
CREATE UNIQUE INDEX IF NOT EXISTS uq_piece_mission_source_active
    ON piece_mission (mission_id)
    WHERE role = 'source_active';

COMMENT ON TABLE piece_mission IS
    'Pièces dossier abonné : source_active (soldes) ou annexe (traçabilité, sans écrasement).';
COMMENT ON COLUMN piece_mission.role IS
    'source_active = unique source importée dans solde_compte ; annexe = pièce jointe.';
COMMENT ON COLUMN piece_mission.chemin_stockage IS
    'Chemin relatif sous var/pieces/ (stockage local/dev).';

DO $$
DECLARE t TEXT := 'piece_mission';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON piece_mission TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE piece_mission_id_seq TO app_revue;
