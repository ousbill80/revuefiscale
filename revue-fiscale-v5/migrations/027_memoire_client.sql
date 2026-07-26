-- 027 — Mémoire client (Data Room phase 1, domaine abonné)
-- Entrées persistantes rattachées au contribuable : faits, contexte,
-- alertes, notes manuelles. Soft-delete via actif ; pas de calcul fiscal.
-- RLS stricte : tenant_id NOT NULL.

CREATE TABLE IF NOT EXISTS memoire_client (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT NOT NULL REFERENCES tenant(id),
    contribuable_id  BIGINT NOT NULL REFERENCES contribuable(id) ON DELETE CASCADE,
    type_entree      TEXT NOT NULL
                     CHECK (type_entree IN (
                         'fait',
                         'contexte',
                         'alerte',
                         'note'
                     )),
    contenu          TEXT NOT NULL,
    source_type      TEXT NOT NULL
                     CHECK (source_type IN (
                         'extraction',
                         'mission',
                         'risque',
                         'manuel'
                     )),
    source_ref       TEXT,
    auteur           TEXT,
    actif            BOOLEAN NOT NULL DEFAULT true,
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT memoire_client_contenu_non_vide CHECK (length(trim(contenu)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_memoire_client_contribuable
    ON memoire_client (tenant_id, contribuable_id, cree_le DESC);

COMMENT ON TABLE memoire_client IS
    'Mémoire client Data Room — contexte persistant du contribuable.';
COMMENT ON COLUMN memoire_client.source_ref IS
    'Référence origine, ex. piece:123, mission:45, risque:40.';
COMMENT ON COLUMN memoire_client.auteur IS
    'Email utilisateur pour les notes manuelles ; ''systeme'' sinon.';
COMMENT ON COLUMN memoire_client.actif IS
    'false = entrée retirée (soft-delete) — jamais de DELETE physique.';

DO $$
DECLARE t TEXT := 'memoire_client';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON memoire_client TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE memoire_client_id_seq TO app_revue;
