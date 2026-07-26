-- 021 — Actions sur risques (domaine abonné)
-- Corrective | préventive ; clôture = vérification cabinet (docs/25).
-- Pas d'auto-clôture client.

CREATE TABLE IF NOT EXISTS action_risque (
    id                   BIGSERIAL PRIMARY KEY,
    tenant_id            BIGINT NOT NULL REFERENCES tenant(id),
    risque_id            BIGINT NOT NULL REFERENCES risque(id) ON DELETE CASCADE,
    nature               TEXT NOT NULL
                         CHECK (nature IN ('corrective', 'preventive')),
    libelle              TEXT NOT NULL,
    responsable_user_id  BIGINT REFERENCES utilisateur(id) ON DELETE SET NULL,
    responsable_label    TEXT,
    echeance             DATE,
    statut               TEXT NOT NULL DEFAULT 'proposee'
                         CHECK (statut IN (
                           'proposee', 'acceptee', 'refusee', 'en_cours',
                           'preuve_deposee', 'verifiee', 'close', 'abandonnee'
                         )),
    motif_refus          TEXT,
    preuve_piece_id      BIGINT REFERENCES piece_mission(id) ON DELETE SET NULL,
    preuve_uri           TEXT,
    preuve_deposee_le    TIMESTAMPTZ,
    verifiee_par         TEXT,
    verifiee_le          TIMESTAMPTZ,
    cree_le              TIMESTAMPTZ NOT NULL DEFAULT now(),
    maj_le               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT action_risque_libelle_non_vide CHECK (length(trim(libelle)) > 0),
    CONSTRAINT action_risque_refus_motif CHECK (
        statut <> 'refusee'
        OR (motif_refus IS NOT NULL AND length(trim(motif_refus)) > 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_action_risque_risque_statut
    ON action_risque (risque_id, statut);

CREATE INDEX IF NOT EXISTS idx_action_risque_retards
    ON action_risque (tenant_id, echeance)
    WHERE echeance IS NOT NULL
      AND statut IN ('acceptee', 'en_cours', 'preuve_deposee');

COMMENT ON TABLE action_risque IS
    'Actions corrective/préventive d''un risque — vérif cabinet seule clôture.';
COMMENT ON COLUMN action_risque.nature IS
    'corrective = réparer le passé ; preventive = empêcher la récurrence.';

DO $$
DECLARE t TEXT := 'action_risque';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON action_risque TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE action_risque_id_seq TO app_revue;
