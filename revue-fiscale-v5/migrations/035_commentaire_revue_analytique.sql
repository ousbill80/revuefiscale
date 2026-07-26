-- 035 — Commentaire IA de revue analytique (versionné par mission)
-- Lecture commentée des variations significatives N/N-1 : pour chaque
-- poste, hypothèse explicative et question à poser au client. Construit
-- UNIQUEMENT à partir des variations calculées par la revue analytique
-- déterministe — tout poste non fourni est retiré. Consultatif : l'humain
-- valide. RLS stricte.

CREATE TABLE IF NOT EXISTS commentaire_revue_analytique (
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

CREATE INDEX IF NOT EXISTS idx_commentaire_revue_analytique_mission
    ON commentaire_revue_analytique (tenant_id, mission_id, version DESC);

COMMENT ON TABLE commentaire_revue_analytique IS
    'Commentaire IA de revue analytique N/N-1 — versionné, l''humain valide.';
COMMENT ON COLUMN commentaire_revue_analytique.version IS
    'Version incrémentale par mission (max + 1 à chaque génération).';
COMMENT ON COLUMN commentaire_revue_analytique.contenu IS
    '{resume, explications[{poste, hypothese_explicative, question_a_poser_au_client, gravite}], alertes_coherence[]}.';
COMMENT ON COLUMN commentaire_revue_analytique.modele IS
    'Identifiant du fournisseur / modèle ayant produit le commentaire.';

DO $$
DECLARE t TEXT := 'commentaire_revue_analytique';
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

GRANT SELECT, INSERT, UPDATE, DELETE ON commentaire_revue_analytique TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE commentaire_revue_analytique_id_seq TO app_revue;
