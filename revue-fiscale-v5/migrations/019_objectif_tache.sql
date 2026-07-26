-- 019 — Objectif fiscal + tâche (domaine abonné)
-- Objectif = unité fiscale (impôt + exercices) — source de vérité du périmètre.
-- mission_objectif (018) reste narratif (lettre) — noms distincts.
-- tache = machine à états ; conclusion = artefact de calcul (montants).
-- Plan dérivé déterministe — aucun LLM, aucun seuil CGI en dur.

CREATE TABLE IF NOT EXISTS objectif (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT NOT NULL REFERENCES tenant(id),
    mission_id       BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    impot            TEXT NOT NULL,
    exercices        SMALLINT[] NOT NULL,
    dans_perimetre   BOOLEAN NOT NULL DEFAULT TRUE,
    motif_exclusion  TEXT,
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT now(),
    maj_le           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT objectif_impot_mission_uq UNIQUE (tenant_id, mission_id, impot),
    CONSTRAINT objectif_impot_non_vide CHECK (length(trim(impot)) > 0),
    CONSTRAINT objectif_exercices_non_vide CHECK (cardinality(exercices) >= 1),
    CONSTRAINT objectif_motif_si_hors CHECK (
        dans_perimetre OR motif_exclusion IS NULL
        OR length(trim(motif_exclusion)) >= 0
    )
);

CREATE INDEX IF NOT EXISTS idx_objectif_mission
    ON objectif (tenant_id, mission_id, impot);

COMMENT ON TABLE objectif IS
    'Unité fiscale de mission (impôt + exercices) — pilote le périmètre.';
COMMENT ON COLUMN objectif.dans_perimetre IS
    'TRUE = examiné ; FALSE = hors lettre (non examiné au rapport).';
COMMENT ON COLUMN objectif.motif_exclusion IS
    'Motif hors périmètre — texte libre cabinet, pas un article inventé.';

CREATE TABLE IF NOT EXISTS tache (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT NOT NULL REFERENCES tenant(id),
    objectif_id      BIGINT NOT NULL REFERENCES objectif(id) ON DELETE CASCADE,
    regle_version_id BIGINT REFERENCES regle_version(id),
    statut           TEXT NOT NULL DEFAULT 'a_faire'
                     CHECK (statut IN (
                       'a_faire', 'en_cours', 'bloquee', 'sous_seuil',
                       'non_verifiable', 'conforme', 'anomalie', 'hors_perimetre'
                     )),
    assignee_a       BIGINT REFERENCES utilisateur(id) ON DELETE SET NULL,
    bloquee_par      BIGINT[] NOT NULL DEFAULT '{}',
    piece_attendue   TEXT,
    conclusion_id    BIGINT REFERENCES conclusion(id) ON DELETE SET NULL,
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT now(),
    maj_le           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tache_objectif_regle_uq UNIQUE (objectif_id, regle_version_id)
);

CREATE INDEX IF NOT EXISTS idx_tache_tenant_statut
    ON tache (tenant_id, statut);
CREATE INDEX IF NOT EXISTS idx_tache_objectif
    ON tache (objectif_id);
CREATE INDEX IF NOT EXISTS idx_tache_assignee
    ON tache (tenant_id, assignee_a)
    WHERE assignee_a IS NOT NULL;

COMMENT ON TABLE tache IS
    'Unité d''exécution dérivée du plan déterministe — hors choix LLM.';
COMMENT ON COLUMN tache.statut IS
    'Workflow (a_faire/en_cours/bloquee) + résultats (miroir conclusion).';
COMMENT ON COLUMN tache.bloquee_par IS
    'Ids de tâches bloquantes (effets croisés runtime).';
COMMENT ON COLUMN tache.piece_attendue IS
    'Libellé pièce manquante — alimente relances client.';
COMMENT ON COLUMN tache.assignee_a IS
    'Collaborateur cabinet (utilisateur.id) — hors calcul fiscal.';

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['objectif', 'tache']
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

GRANT SELECT, INSERT, UPDATE, DELETE ON objectif, tache TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE objectif_id_seq, tache_id_seq TO app_revue;

-- Backfill depuis perimetre_impots existant (revue partielle uniquement).
DO $$
DECLARE
    m RECORD;
    code TEXT;
    codes TEXT[];
    ex SMALLINT;
BEGIN
    FOR m IN
        SELECT id, tenant_id, exercice, perimetre_impots
        FROM mission
        WHERE perimetre_impots IS NOT NULL
    LOOP
        IF jsonb_typeof(m.perimetre_impots) <> 'array' THEN
            CONTINUE;
        END IF;
        SELECT ARRAY(
            SELECT upper(trim(value::text, '"'))
            FROM jsonb_array_elements_text(m.perimetre_impots) AS value
            WHERE length(trim(value)) > 0
        ) INTO codes;
        IF codes IS NULL OR cardinality(codes) = 0 THEN
            CONTINUE;
        END IF;
        ex := COALESCE(m.exercice, EXTRACT(YEAR FROM now())::SMALLINT);
        FOREACH code IN ARRAY ARRAY[
            'BIC','TVA','RAS','ITS','CE','IRC','IRVM','PAT',
            'FONC','ENR','TIMBRE','OBL','OBNL','RA'
        ]
        LOOP
            INSERT INTO objectif (
                tenant_id, mission_id, impot, exercices, dans_perimetre, motif_exclusion
            )
            VALUES (
                m.tenant_id,
                m.id,
                code,
                ARRAY[ex]::SMALLINT[],
                (code = ANY (codes)),
                CASE WHEN code = ANY (codes) THEN NULL
                     ELSE 'Hors périmètre déclaré (lettre de mission)'
                END
            )
            ON CONFLICT (tenant_id, mission_id, impot) DO NOTHING;
        END LOOP;
    END LOOP;
END $$;
