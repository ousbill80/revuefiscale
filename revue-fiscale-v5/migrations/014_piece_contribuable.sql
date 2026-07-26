-- 014 — Pièces d'identité au niveau contribuable (domaine abonné)
-- Upload avant création (contribuable_id NULL + session_upload) puis rattachement.
-- Types métier : DFE, RCCM, bail, CIE, SODECI — pas de calcul fiscal.
-- RLS stricte : tenant_id NOT NULL.

CREATE TABLE IF NOT EXISTS piece_contribuable (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT NOT NULL REFERENCES tenant(id),
    contribuable_id  BIGINT REFERENCES contribuable(id) ON DELETE CASCADE,
    session_upload   TEXT,
    type_piece       TEXT NOT NULL
                     CHECK (type_piece IN (
                         'dfe',
                         'rccm',
                         'bail',
                         'cie',
                         'sodeci',
                         'autre'
                     )),
    nom_fichier      TEXT NOT NULL,
    chemin_stockage  TEXT NOT NULL,
    taille_octets    BIGINT,
    content_type     TEXT,
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT piece_contribuable_ancre CHECK (
        contribuable_id IS NOT NULL OR (
            session_upload IS NOT NULL AND length(trim(session_upload)) > 0
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_piece_contribuable_tenant
    ON piece_contribuable (tenant_id, contribuable_id);

CREATE INDEX IF NOT EXISTS idx_piece_contribuable_session
    ON piece_contribuable (tenant_id, session_upload)
    WHERE session_upload IS NOT NULL;

COMMENT ON TABLE piece_contribuable IS
    'Pièces d''identité abonné (DFE/RCCM/bail/…) — cloisonnées, hors moteur fiscal.';
COMMENT ON COLUMN piece_contribuable.contribuable_id IS
    'NULL si upload avant création fiche ; rattacher ensuite via session_upload.';
COMMENT ON COLUMN piece_contribuable.session_upload IS
    'UUID client pour regrouper les pièces orphelines avant POST contribuable.';
COMMENT ON COLUMN piece_contribuable.chemin_stockage IS
    'Chemin relatif sous var/pieces/ (même racine que piece_mission).';

-- Brouillon d'extraction IA : jamais écrit automatiquement dans contribuable.
CREATE TABLE IF NOT EXISTS proposition_identite (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         BIGINT NOT NULL REFERENCES tenant(id),
    contribuable_id   BIGINT REFERENCES contribuable(id) ON DELETE SET NULL,
    session_upload    TEXT,
    piece_ids         BIGINT[] NOT NULL,
    champs_proposes   JSONB NOT NULL DEFAULT '{}'::jsonb,
    citations         JSONB NOT NULL DEFAULT '[]'::jsonb,
    statut            TEXT NOT NULL DEFAULT 'brouillon'
                      CHECK (statut IN (
                          'brouillon',
                          'applique',
                          'ignore',
                          'indisponible'
                      )),
    message           TEXT,
    cree_le           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_proposition_identite_tenant
    ON proposition_identite (tenant_id, cree_le DESC);

COMMENT ON TABLE proposition_identite IS
    'Sortie LLM d''extraction identité — brouillon sourcé ; l''humain valide.';
COMMENT ON COLUMN proposition_identite.citations IS
    '[{champ, piece_id, extrait, confiance}] — traçabilité pièce → champ.';

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['piece_contribuable', 'proposition_identite']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE  ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS %1$I_tenant ON %1$I', t);
        EXECUTE format($f$
            CREATE POLICY %1$I_tenant ON %1$I
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::BIGINT)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::BIGINT)
        $f$, t);
    END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON piece_contribuable TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE piece_contribuable_id_seq TO app_revue;
GRANT SELECT, INSERT, UPDATE, DELETE ON proposition_identite TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE proposition_identite_id_seq TO app_revue;
