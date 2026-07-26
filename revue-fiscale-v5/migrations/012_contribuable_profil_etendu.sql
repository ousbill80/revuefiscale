-- 012 — Profil contribuable étendu (identité / cadrage revue)
-- Domaine abonné : colonnes sur fiche cloisonnée (RLS déjà en place via 003).
-- Pas de taux / seuil / condition fiscale — données d'identité uniquement.

ALTER TABLE contribuable
    ADD COLUMN IF NOT EXISTS capital_social NUMERIC(18, 2),
    ADD COLUMN IF NOT EXISTS mois_cloture SMALLINT,
    ADD COLUMN IF NOT EXISTS activite_principale TEXT,
    ADD COLUMN IF NOT EXISTS date_immatriculation DATE;

ALTER TABLE contribuable
    DROP CONSTRAINT IF EXISTS contribuable_mois_cloture_chk;

ALTER TABLE contribuable
    ADD CONSTRAINT contribuable_mois_cloture_chk
    CHECK (mois_cloture IS NULL OR (mois_cloture >= 1 AND mois_cloture <= 12));

COMMENT ON COLUMN contribuable.capital_social IS
    'Capital social déclaré (XOF) — identité, pas un seuil moteur.';
COMMENT ON COLUMN contribuable.mois_cloture IS
    'Mois de clôture d''exercice (1–12). Année civile = 12.';
COMMENT ON COLUMN contribuable.activite_principale IS
    'Activité / secteur libre (libellé) — défaut profil mission.';
COMMENT ON COLUMN contribuable.date_immatriculation IS
    'Date d''immatriculation DGI (identité).';
