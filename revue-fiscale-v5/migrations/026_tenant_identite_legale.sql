-- 026 — Identité légale de l'abonné (cabinet / entreprise) sur tenant
-- Domaine plateforme (table tenant) : colonnes d'identité, pas de calcul fiscal.
-- Mutables uniquement via /api/v1/compte (JWT → WHERE id = tenant_id).
-- Tous optionnels : complétion progressive dans le portail Compte.
-- Aligné sur les champs d'identité contribuable (009/012/013) — hors régime
-- fiscal / mois clôture (propres au contribuable contrôlé, pas à l'abonné).

ALTER TABLE tenant
    ADD COLUMN IF NOT EXISTS ncc TEXT,
    ADD COLUMN IF NOT EXISTS rccm TEXT,
    ADD COLUMN IF NOT EXISTS dfe TEXT,
    ADD COLUMN IF NOT EXISTS forme_juridique TEXT,
    ADD COLUMN IF NOT EXISTS siege_social TEXT,
    ADD COLUMN IF NOT EXISTS commune TEXT,
    ADD COLUMN IF NOT EXISTS centre_impots TEXT,
    ADD COLUMN IF NOT EXISTS capital_social NUMERIC(18, 2);

COMMENT ON COLUMN tenant.ncc IS
    'N° de compte contribuable DGI du cabinet abonné (figurant sur la DFE). Optionnel.';
COMMENT ON COLUMN tenant.rccm IS
    'RCCM du cabinet abonné — identité OHADA, pas un seuil moteur.';
COMMENT ON COLUMN tenant.dfe IS
    'Référence documentaire DFE optionnelle. Le n° porté sur la DFE est en pratique le NCC.';
COMMENT ON COLUMN tenant.forme_juridique IS
    'Forme juridique (SA, SARL, SCP…) — listing identité, pas une règle fiscale.';
COMMENT ON COLUMN tenant.siege_social IS
    'Adresse / quartier du siège social du cabinet.';
COMMENT ON COLUMN tenant.commune IS
    'Ville / commune du siège du cabinet.';
COMMENT ON COLUMN tenant.centre_impots IS
    'Centre des impôts de rattachement (libellé libre).';
COMMENT ON COLUMN tenant.capital_social IS
    'Capital social déclaré (XOF) — identité, pas un seuil moteur.';
