-- 032 : traçabilité comptable des conclusions (piste d'audit contrôleur).
-- Comptes à l'origine de chaque conclusion : {compte, libelle, solde, sens}[].
-- La table conclusion est déjà sous RLS FORCE + policy tenant (004) et
-- déjà accordée à app_revue (GRANT 004) — un ajout de colonne en hérite.

ALTER TABLE conclusion
    ADD COLUMN IF NOT EXISTS comptes_source JSONB NOT NULL DEFAULT '[]';

COMMENT ON COLUMN conclusion.comptes_source IS
    'Comptes ayant alimenté la règle (références solde() + composition des '
    'agrégats) au moment de l''exécution : liste {compte, libelle, solde, sens}. '
    'Instantané figé — piste d''audit « d''où vient ce montant ? », '
    'jamais recalculé après coup.';
