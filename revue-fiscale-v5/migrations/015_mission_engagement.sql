-- 015 — Cadrage d'engagement mission (domaine abonné)
-- Lot 1 engagement cabinet : type, périmètre impôts, exclusions.
-- seuil_signification inclus ici (Lot 3) pour éviter une migration colonnes dédiée.
-- RLS déjà en place sur mission (003) — pas de nouvelle table.
-- Aucun taux / délai CGI inventé : codes impot = taxonomie pivot uniquement.

ALTER TABLE mission
    ADD COLUMN IF NOT EXISTS type_engagement TEXT NOT NULL DEFAULT 'autre',
    ADD COLUMN IF NOT EXISTS perimetre_impots JSONB,
    ADD COLUMN IF NOT EXISTS exclusions_declarees TEXT,
    ADD COLUMN IF NOT EXISTS seuil_signification NUMERIC(18, 2);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'mission_type_engagement_check'
    ) THEN
        ALTER TABLE mission
            ADD CONSTRAINT mission_type_engagement_check
            CHECK (type_engagement IN (
                'preventive',
                'cac',
                'due_diligence',
                'assistance_controle',
                'autre'
            ));
    END IF;
END $$;

COMMENT ON COLUMN mission.type_engagement IS
    'Contexte d''engagement (UX / rapport) — n''altère aucune formule fiscale.';
COMMENT ON COLUMN mission.perimetre_impots IS
    'NULL = tous les impôts ; liste JSON non vide = filtre strict (codes pivot). [] rejeté en API.';
COMMENT ON COLUMN mission.exclusions_declarees IS
    'Exclusions narratives lettre de mission (hors codes impot).';
COMMENT ON COLUMN mission.seuil_signification IS
    'Seuil de matérialité cabinet (FCFA) — NULL = pas de classification auto sous_seuil.';
