-- 025 — Traçabilité création contribuable (qui / quand)
-- Domaine abonné : colonnes sur fiche cloisonnée (RLS déjà en place via 003).
-- Pas de fiscalité — identité opérationnelle uniquement.
-- Historique : cree_le / cree_par restent NULL (création antérieure non tracée).

ALTER TABLE contribuable
    ADD COLUMN IF NOT EXISTS cree_le TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS cree_par BIGINT REFERENCES utilisateur(id);

ALTER TABLE contribuable
    ALTER COLUMN cree_le SET DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_contribuable_cree_par
    ON contribuable (tenant_id, cree_par);

COMMENT ON COLUMN contribuable.cree_le IS
    'Horodatage création fiche (TIMESTAMPTZ). NULL = antérieur à la traçabilité.';
COMMENT ON COLUMN contribuable.cree_par IS
    'Utilisateur cabinet ayant créé la fiche (FK utilisateur).';
