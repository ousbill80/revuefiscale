-- 018 — Objectifs de mission (domaine abonné)
-- Plusieurs objectifs narratifs par mission (lettre d'engagement).
-- Libellés libres cabinet — PAS de catalogue CGI / taux / seuil.
-- Ne pilotent pas selectionner_regles (reste perimetre_impots).
-- Gel métier : API refuse écriture si mission.statut ≠ 'cadrage'.

CREATE TABLE IF NOT EXISTS mission_objectif (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenant(id),
    mission_id  BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    ordre       INT NOT NULL DEFAULT 0,
    libelle     TEXT NOT NULL,
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    maj_le      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT mission_objectif_libelle_non_vide
        CHECK (length(trim(libelle)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_mission_objectif_mission
    ON mission_objectif (tenant_id, mission_id, ordre, id);

COMMENT ON TABLE mission_objectif IS
    'Objectifs déclarés de la mission (libellés libres) — hors moteur fiscal.';
COMMENT ON COLUMN mission_objectif.libelle IS
    'Texte libre cabinet (lettre de mission) — aucun code CGI inventé.';
COMMENT ON COLUMN mission_objectif.ordre IS
    'Ordre d''affichage (0-based) — rapport et UI.';

DO $$
DECLARE t TEXT := 'mission_objectif';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON mission_objectif TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE mission_objectif_id_seq TO app_revue;
