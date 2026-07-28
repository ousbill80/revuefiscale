-- 049 — Suivi des contrôles fiscaux et contentieux d'une mission.
-- Aucune table ne stockait les événements de procédure (avis de
-- vérification, notification de redressement, mise en demeure,
-- réclamation contentieuse, réponse de l'administration, dégrèvement,
-- recours…) : impossible de suivre les délais de riposte du Livre de
-- Procédures Fiscales ivoirien. Cette table stocke UN événement par
-- ligne, consigné par le fiscaliste (date, type, montant en jeu
-- éventuel, commentaire). Les délais sont CALCULÉS à la lecture, rien
-- n'est stocké de dérivé. RLS stricte dans la même migration
-- (pattern 045-048).

CREATE TABLE IF NOT EXISTS evenement_controle_fiscal (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT NOT NULL REFERENCES tenant(id),
    mission_id      BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    type_evenement  TEXT NOT NULL CHECK (type_evenement IN (
        'avis_verification',
        'notification_redressement',
        'mise_en_demeure',
        'avis_mise_en_recouvrement',
        'reclamation_contentieuse',
        'reponse_administration',
        'degrevement',
        'recours_juridictionnel'
    )),
    date_evenement  DATE NOT NULL,
    montant_en_jeu  NUMERIC(18,2) CHECK (montant_en_jeu >= 0),
    commentaire     TEXT NOT NULL DEFAULT '',
    cree_le         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_evenement_controle_fiscal_mission
    ON evenement_controle_fiscal (tenant_id, mission_id, date_evenement);

COMMENT ON TABLE evenement_controle_fiscal IS
    'Événements de procédure (contrôle fiscal / contentieux) consignés par le fiscaliste — délais LPF calculés à la lecture, consultatif.';
COMMENT ON COLUMN evenement_controle_fiscal.type_evenement IS
    'Type d''acte de procédure (avis de vérification, notification de redressement, …).';
COMMENT ON COLUMN evenement_controle_fiscal.date_evenement IS
    'Date de réception ou d''envoi de l''acte (point de départ du délai de riposte).';
COMMENT ON COLUMN evenement_controle_fiscal.montant_en_jeu IS
    'Montant en jeu éventuel (droits + pénalités) en FCFA — NULL si sans objet.';

DO $$
DECLARE t TEXT := 'evenement_controle_fiscal';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON evenement_controle_fiscal TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE evenement_controle_fiscal_id_seq TO app_revue;
