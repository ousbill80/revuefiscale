-- 013 — Siège effectif + centre des impôts (rattachement DGI)
-- Domaine abonné : colonnes sur fiche cloisonnée (RLS déjà en place via 003).
-- Pas de taux / seuil / condition fiscale — données d'identité uniquement.
--
-- Métier CI : le lieu effectif du siège (domicile fiscal) détermine le centre
-- des impôts de rattachement. Liste exhaustive des centres : non figée ici
-- (document DGI « Liste des centres… » sur dgi.gouv.ci — saisie libre).

ALTER TABLE contribuable
    ADD COLUMN IF NOT EXISTS commune TEXT,
    ADD COLUMN IF NOT EXISTS centre_impots TEXT;

COMMENT ON COLUMN contribuable.commune IS
    'Ville / commune du siège effectif (domicile fiscal).';
COMMENT ON COLUMN contribuable.centre_impots IS
    'Centre des impôts de rattachement (libellé libre — figurant sur DFE / avis).';
COMMENT ON COLUMN contribuable.siege_social IS
    'Adresse / quartier du siège effectif (preuve usuelle : bail, CIE, SODECI).';
COMMENT ON COLUMN contribuable.dfe IS
    'Référence documentaire DFE optionnelle. Le n° porté sur la DFE est en pratique le NCC.';
