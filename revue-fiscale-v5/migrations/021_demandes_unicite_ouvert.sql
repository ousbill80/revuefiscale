-- 021 — Unicité partielle des demandes « ouvert » (courses concurrentes).
-- Une seule demande ouverte par facture ; une seule demande palier ouverte par tenant.

CREATE UNIQUE INDEX IF NOT EXISTS uq_demande_paiement_ouverte
    ON demande_paiement (facture_id)
    WHERE statut = 'ouvert';

CREATE UNIQUE INDEX IF NOT EXISTS uq_demande_palier_ouverte
    ON demande_palier (tenant_id)
    WHERE statut = 'ouvert';
