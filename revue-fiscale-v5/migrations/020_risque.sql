-- 020 — Registre des risques (domaine abonné)
-- Le risque appartient au CONTRIBUABLE, pas à la mission (docs/25).
-- Naît d'une conclusion ; survit à la clôture. Pas de délai CGI inventé.
-- Statut prescrit = manuel seulement (R5 auto bloqué visa).

CREATE TABLE IF NOT EXISTS risque (
    id                     BIGSERIAL PRIMARY KEY,
    tenant_id              BIGINT NOT NULL REFERENCES tenant(id),
    contribuable_id        BIGINT NOT NULL REFERENCES contribuable(id),
    origine_conclusion_id  BIGINT REFERENCES conclusion(id) ON DELETE SET NULL,
    origine_mission_id     BIGINT REFERENCES mission(id) ON DELETE SET NULL,
    origine_tache_id       BIGINT REFERENCES tache(id) ON DELETE SET NULL,
    impot                  TEXT NOT NULL,
    reference_legale       TEXT,
    libelle                TEXT NOT NULL,
    montant_estime         NUMERIC(18,2),
    penalites_estimees     NUMERIC(18,2),
    probabilite            TEXT NOT NULL DEFAULT 'possible'
                           CHECK (probabilite IN ('probable', 'possible', 'faible')),
    statut                 TEXT NOT NULL DEFAULT 'ouvert'
                           CHECK (statut IN (
                             'ouvert', 'en_traitement', 'resolu',
                             'accepte', 'prescrit'
                           )),
    exercice_origine       SMALLINT NOT NULL,
    derniere_revue         DATE,
    motif_acceptation      TEXT,
    accepte_le             TIMESTAMPTZ,
    accepte_par            TEXT,
    prescrit_le            TIMESTAMPTZ,
    cree_le                TIMESTAMPTZ NOT NULL DEFAULT now(),
    maj_le                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT risque_libelle_non_vide CHECK (length(trim(libelle)) > 0),
    CONSTRAINT risque_impot_non_vide CHECK (length(trim(impot)) > 0),
    CONSTRAINT risque_accepte_motif CHECK (
        statut <> 'accepte'
        OR (motif_acceptation IS NOT NULL AND length(trim(motif_acceptation)) > 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_risque_contribuable_statut
    ON risque (tenant_id, contribuable_id, statut);

CREATE INDEX IF NOT EXISTS idx_risque_origine_conclusion
    ON risque (origine_conclusion_id)
    WHERE origine_conclusion_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_risque_origine_conclusion_uq
    ON risque (tenant_id, origine_conclusion_id)
    WHERE origine_conclusion_id IS NOT NULL;

COMMENT ON TABLE risque IS
    'Registre post-mission — appartient au contribuable (docs/25).';
COMMENT ON COLUMN risque.statut IS
    'ouvert|en_traitement|resolu|accepte|prescrit — prescrit manuel seulement.';
COMMENT ON COLUMN risque.montant_estime IS
    'Estimation humaine de suivi — distincte du montant conclusion moteur.';

DO $$
DECLARE t TEXT := 'risque';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON risque TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE risque_id_seq TO app_revue;
