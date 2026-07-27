-- 040 — Paramètres de rentabilité de la mission
-- Le cabinet convient d'honoraires forfaitaires par mission et applique
-- un taux horaire standard pour valoriser le temps passé. Ces deux
-- paramètres, portés par la mission elle-même, permettent le calcul
-- marge = honoraires - (heures saisies x taux horaire).
-- Colonnes nullables : aucune donnée existante impactée. La table
-- mission porte déjà sa politique RLS (003) — rien à ajouter.

ALTER TABLE mission
    ADD COLUMN IF NOT EXISTS honoraires NUMERIC(14,2) NULL
        CHECK (honoraires IS NULL OR honoraires >= 0),
    ADD COLUMN IF NOT EXISTS taux_horaire NUMERIC(12,2) NULL
        CHECK (taux_horaire IS NULL OR taux_horaire >= 0);
