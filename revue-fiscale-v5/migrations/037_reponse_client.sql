-- 037 — Réponses client à la demande de renseignements
-- Une ligne par item de circularisation répondu : contenu de la réponse
-- du client et pièces reçues, tracés AVANT toute relance d'exécution.
-- La saisie d'une réponse marque l'item de suivi « recu » côté backend.
-- RLS stricte.

CREATE TABLE IF NOT EXISTS reponse_client (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL,
    mission_id    BIGINT NOT NULL REFERENCES mission(id),
    cle_item      TEXT NOT NULL,
    contenu       TEXT NOT NULL,
    pieces_recues TEXT NULL,
    saisie_par    TEXT NOT NULL,
    saisie_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, mission_id, cle_item)
);

CREATE INDEX IF NOT EXISTS idx_reponse_client_mission
    ON reponse_client (tenant_id, mission_id);

COMMENT ON TABLE reponse_client IS
    'Réponses client aux items de la demande de renseignements (circularisation).';
COMMENT ON COLUMN reponse_client.cle_item IS
    'Identifiant stable de l''item : analytique:{poste} ou piece:{regle_id}.';
COMMENT ON COLUMN reponse_client.pieces_recues IS
    'Description libre des pièces jointes reçues du client (nullable).';

DO $$
DECLARE t TEXT := 'reponse_client';
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

GRANT SELECT, INSERT, UPDATE ON reponse_client TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE reponse_client_id_seq TO app_revue;
