-- 028 — Synthèse IA client (Data Room phase 2, domaine abonné)
-- Document consultatif versionné généré par IA sur le dossier d'un
-- contribuable (résumé, points clés, incohérences, recommandations,
-- toutes affirmations sourcées). Jamais appliqué automatiquement.
-- RLS stricte : tenant_id NOT NULL.

CREATE TABLE IF NOT EXISTS synthese_client (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT NOT NULL REFERENCES tenant(id),
    contribuable_id  BIGINT NOT NULL REFERENCES contribuable(id) ON DELETE CASCADE,
    version          INTEGER NOT NULL,
    statut           TEXT NOT NULL
                     CHECK (statut IN (
                         'en_cours',
                         'disponible',
                         'echec'
                     )),
    contenu          JSONB,
    modele           TEXT,
    erreur           TEXT,
    auteur           TEXT,
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_synthese_client_contribuable
    ON synthese_client (tenant_id, contribuable_id, version DESC);

COMMENT ON TABLE synthese_client IS
    'Synthèse IA Data Room — document consultatif versionné, l''humain valide.';
COMMENT ON COLUMN synthese_client.version IS
    'Version incrémentale par contribuable (max + 1 à chaque génération).';
COMMENT ON COLUMN synthese_client.contenu IS
    '{resume, points_cles, incoherences, recommandations} — sources citées.';
COMMENT ON COLUMN synthese_client.modele IS
    'Identifiant du fournisseur / modèle ayant produit la synthèse.';

DO $$
DECLARE t TEXT := 'synthese_client';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON synthese_client TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE synthese_client_id_seq TO app_revue;

-- Extension mémoire client : la génération d'une synthèse alimente la
-- mémoire (type contexte) avec une source dédiée.
ALTER TABLE memoire_client
    DROP CONSTRAINT IF EXISTS memoire_client_source_type_check;
ALTER TABLE memoire_client
    ADD CONSTRAINT memoire_client_source_type_check
    CHECK (source_type IN (
        'extraction',
        'mission',
        'risque',
        'manuel',
        'synthese'
    ));
