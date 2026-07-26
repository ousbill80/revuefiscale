-- 011 — Config éditeur 2AàZ (paliers commerciaux + mentions facture)
-- Domaine éditorial / plateforme éditeur — PAS de tenant_id, PAS de RLS.
-- Les montants saisis ici écrasent les bornes techniques provisoires (paliers.py).
-- Vides = À CONFIRMER. Jamais inventer RCCM / grille « officielle » en seed.

CREATE TABLE IF NOT EXISTS config_editeur (
    cle            TEXT PRIMARY KEY,
    valeur         JSONB NOT NULL DEFAULT '{}',
    mis_a_jour_le  TIMESTAMPTZ NOT NULL DEFAULT now(),
    mis_a_jour_par TEXT
);

COMMENT ON TABLE config_editeur IS
  'Paramètres éditeur 2AàZ (paliers, mentions facture). Saisie humaine — responsabilité 2AàZ.';

-- Pas de seed de montants / RCCM : laisser vide jusqu'à saisie UI ou env.

GRANT SELECT, INSERT, UPDATE, DELETE ON config_editeur TO app_revue;
