-- 034 — Note de synthèse de mission (executive summary IA versionné)
-- Document consultatif destiné à l'associé signataire : contexte, constats
-- chiffrés hiérarchisés (chaque constat cite la règle regle_id dont il
-- provient), exposition estimée, points d'attention, recommandations.
-- Jamais appliquée automatiquement — l'humain signe. RLS stricte.

CREATE TABLE IF NOT EXISTS note_synthese_mission (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenant(id),
    mission_id  BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    statut      TEXT NOT NULL
                CHECK (statut IN (
                    'en_cours',
                    'disponible',
                    'echec'
                )),
    contenu     JSONB,
    modele      TEXT,
    erreur      TEXT,
    auteur      TEXT,
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_note_synthese_mission_mission
    ON note_synthese_mission (tenant_id, mission_id, version DESC);

COMMENT ON TABLE note_synthese_mission IS
    'Note de synthèse IA de mission — executive summary versionné, l''humain valide.';
COMMENT ON COLUMN note_synthese_mission.version IS
    'Version incrémentale par mission (max + 1 à chaque génération).';
COMMENT ON COLUMN note_synthese_mission.contenu IS
    '{contexte, constats[{regle_id, resume, montant, gravite}], exposition, points_attention, recommandations}.';
COMMENT ON COLUMN note_synthese_mission.modele IS
    'Identifiant du fournisseur / modèle ayant produit la note.';

DO $$
DECLARE t TEXT := 'note_synthese_mission';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON note_synthese_mission TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE note_synthese_mission_id_seq TO app_revue;
