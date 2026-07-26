-- 009 — Identité légale contribuable (PM / entreprise)
-- Domaine abonné : colonnes additionnelles sur fiche cloisonnée.
-- Pas de taux / seuil fiscal — données d'identité uniquement.

ALTER TABLE contribuable
    ADD COLUMN IF NOT EXISTS dfe TEXT,
    ADD COLUMN IF NOT EXISTS regime_fiscal TEXT,
    ADD COLUMN IF NOT EXISTS forme_juridique TEXT,
    ADD COLUMN IF NOT EXISTS siege_social TEXT;

COMMENT ON COLUMN contribuable.dfe IS
    'N° DFE (déclaration fiscale d''existence) — identité, pas un calcul.';
COMMENT ON COLUMN contribuable.regime_fiscal IS
    'Régime fiscal déclaré du contribuable (défaut profil mission).';
COMMENT ON COLUMN contribuable.forme_juridique IS
    'Forme juridique (SA, SARL…) — distinct de forme pm|pp.';
COMMENT ON COLUMN contribuable.siege_social IS
    'Adresse du siège social (optionnel).';
