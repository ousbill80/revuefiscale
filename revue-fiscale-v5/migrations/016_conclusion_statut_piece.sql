-- 016 — Statut conclusion + lien pièce dossier (domaine abonné)
-- Lot 2 engagement : brouillon moteur, validation humaine.
-- Aucun taux / seuil CGI — statut sous_seuil vient du seuil mission (015).

ALTER TABLE conclusion
    ADD COLUMN IF NOT EXISTS statut TEXT NOT NULL DEFAULT 'anomalie',
    ADD COLUMN IF NOT EXISTS piece_mission_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'conclusion_statut_check'
    ) THEN
        ALTER TABLE conclusion
            ADD CONSTRAINT conclusion_statut_check
            CHECK (statut IN (
                'conforme',
                'anomalie',
                'sous_seuil',
                'non_verifiable',
                'hors_perimetre'
            ));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'conclusion_piece_mission_id_fkey'
    ) THEN
        ALTER TABLE conclusion
            ADD CONSTRAINT conclusion_piece_mission_id_fkey
            FOREIGN KEY (piece_mission_id)
            REFERENCES piece_mission(id)
            ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_conclusion_piece
    ON conclusion (piece_mission_id)
    WHERE piece_mission_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_conclusion_statut
    ON conclusion (tenant_id, statut);

COMMENT ON COLUMN conclusion.statut IS
    'Brouillon moteur (anomalie / non_verifiable / sous_seuil) — humain valide.';
COMMENT ON COLUMN conclusion.piece_mission_id IS
    'Pièce dossier de travail (même mission / tenant) — NULL autorisé.';

-- Cohérence pièce ↔ mission de l'exécution + tenant (filet DB + contrôle API).
CREATE OR REPLACE FUNCTION conclusion_piece_coherence()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_mission_id BIGINT;
    v_piece_mission BIGINT;
    v_piece_tenant BIGINT;
BEGIN
    IF NEW.piece_mission_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT e.mission_id INTO v_mission_id
    FROM execution e
    WHERE e.id = NEW.execution_id;

    IF v_mission_id IS NULL THEN
        RAISE EXCEPTION 'execution % introuvable pour conclusion', NEW.execution_id;
    END IF;

    SELECT p.mission_id, p.tenant_id
    INTO v_piece_mission, v_piece_tenant
    FROM piece_mission p
    WHERE p.id = NEW.piece_mission_id;

    IF v_piece_mission IS NULL THEN
        RAISE EXCEPTION 'piece_mission % introuvable', NEW.piece_mission_id;
    END IF;

    IF v_piece_mission IS DISTINCT FROM v_mission_id THEN
        RAISE EXCEPTION
            'piece_mission % hors mission de la conclusion (attendu %)',
            NEW.piece_mission_id, v_mission_id;
    END IF;

    IF v_piece_tenant IS DISTINCT FROM NEW.tenant_id THEN
        RAISE EXCEPTION
            'piece_mission % hors tenant de la conclusion',
            NEW.piece_mission_id;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_conclusion_piece_coherence ON conclusion;
CREATE TRIGGER trg_conclusion_piece_coherence
    BEFORE INSERT OR UPDATE OF piece_mission_id, execution_id, tenant_id
    ON conclusion
    FOR EACH ROW
    EXECUTE FUNCTION conclusion_piece_coherence();
