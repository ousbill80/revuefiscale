-- 029 — Preuve de résolution obligatoire d'un risque, validée par IA
-- Le passage à « resolu » exige un justificatif ; le verdict IA est
-- consultatif (probante / insuffisante / sans_rapport / indisponible),
-- l'humain décide (decision acceptee ou forcee avec motif).
-- Stockage fichier : même mécanique que piece_contribuable (chemin var/pieces/).
-- RLS stricte : tenant_id NOT NULL.

CREATE TABLE IF NOT EXISTS preuve_resolution_risque (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT NOT NULL REFERENCES tenant(id),
    risque_id        BIGINT NOT NULL REFERENCES risque(id) ON DELETE CASCADE,
    nom_fichier      TEXT NOT NULL,
    format           TEXT NOT NULL,
    chemin_stockage  TEXT NOT NULL,
    taille_octets    BIGINT,
    verdict_ia       TEXT
                     CHECK (verdict_ia IN (
                         'probante',
                         'insuffisante',
                         'sans_rapport',
                         'indisponible'
                     )),
    justification_ia TEXT,
    modele           TEXT,
    decision         TEXT
                     CHECK (decision IN ('acceptee', 'forcee')),
    motif_forcage    TEXT,
    auteur           TEXT,
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_preuve_resolution_risque_tenant
    ON preuve_resolution_risque (tenant_id, risque_id);

COMMENT ON TABLE preuve_resolution_risque IS
    'Justificatifs de résolution des risques — verdict IA consultatif, décision humaine.';
COMMENT ON COLUMN preuve_resolution_risque.verdict_ia IS
    'NULL tant que non analysée ; indisponible = analyse IA impossible.';
COMMENT ON COLUMN preuve_resolution_risque.decision IS
    'acceptee = verdict probante suivi ; forcee = résolution malgré le verdict (motif_forcage).';
COMMENT ON COLUMN preuve_resolution_risque.chemin_stockage IS
    'Chemin relatif sous var/pieces/ (même racine que piece_contribuable).';

DO $$
DECLARE t TEXT := 'preuve_resolution_risque';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON preuve_resolution_risque TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE preuve_resolution_risque_id_seq TO app_revue;
