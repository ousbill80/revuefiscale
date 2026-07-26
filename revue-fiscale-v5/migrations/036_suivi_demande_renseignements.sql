-- 036 — Suivi de circularisation de la demande de renseignements
-- Une ligne par item demandé au client (question analytique ou pièce
-- non vérifiable) : statut de réponse, date de relance, note libre.
-- La liste des items est reconstruite à la volée (mêmes sources que le
-- livrable .docx) ; cette table ne stocke QUE les statuts saisis.
-- RLS stricte.

CREATE TABLE IF NOT EXISTS suivi_demande_renseignements (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenant(id),
    mission_id   BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    cle_item     TEXT NOT NULL,
    libelle      TEXT,
    statut       TEXT NOT NULL DEFAULT 'en_attente'
                 CHECK (statut IN ('en_attente', 'recu', 'sans_objet')),
    date_relance DATE,
    note         TEXT,
    maj_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, mission_id, cle_item)
);

CREATE INDEX IF NOT EXISTS idx_suivi_demande_renseignements_mission
    ON suivi_demande_renseignements (tenant_id, mission_id);

COMMENT ON TABLE suivi_demande_renseignements IS
    'Suivi de circularisation — statut de réponse client par item demandé.';
COMMENT ON COLUMN suivi_demande_renseignements.cle_item IS
    'Identifiant stable de l''item : analytique:{poste} ou piece:{regle_id}.';
COMMENT ON COLUMN suivi_demande_renseignements.date_relance IS
    'Date de relance prévue — item à relancer si en_attente et date échue.';

DO $$
DECLARE t TEXT := 'suivi_demande_renseignements';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON suivi_demande_renseignements TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE suivi_demande_renseignements_id_seq TO app_revue;
