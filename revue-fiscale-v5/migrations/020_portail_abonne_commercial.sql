-- 020 — Portail abonné commercial : demandes paiement / palier
-- Domaine ABONNE : tenant_id NOT NULL + RLS (FORCE).
-- Facture reste domaine plateforme (sans RLS) — lecture abonné filtrée
-- applicativement + SET LOCAL sur les demandes cloisonnées.
-- Staff lit via SECURITY DEFINER (pas de SET app.tenant_id global).
-- Numéro : 018/019 déjà utilisés (mission_objectif / objectif_tache).

-- ── Demande de rapprochement paiement (≠ marquer payée) ───────────
CREATE TABLE IF NOT EXISTS demande_paiement (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenant(id),
    facture_id  BIGINT NOT NULL REFERENCES facture(id),
    statut      TEXT NOT NULL DEFAULT 'ouvert'
                CHECK (statut IN ('ouvert', 'traite', 'refuse')),
    note        TEXT,
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par    BIGINT REFERENCES utilisateur(id),
    traite_le   TIMESTAMPTZ,
    note_staff  TEXT
);
CREATE INDEX IF NOT EXISTS idx_demande_paiement_tenant
    ON demande_paiement (tenant_id, statut);
CREATE INDEX IF NOT EXISTS idx_demande_paiement_facture
    ON demande_paiement (facture_id);

COMMENT ON TABLE demande_paiement IS
    'Signalement virement abonné — rapprochement staff. N''écrit PAS facture.payee.';

-- ── Demande de changement de palier ───────────────────────────────
CREATE TABLE IF NOT EXISTS demande_palier (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenant(id),
    palier_actuel TEXT NOT NULL
                  CHECK (palier_actuel IN ('essentiel','standard','premium','souverain')),
    palier_cible  TEXT NOT NULL
                  CHECK (palier_cible IN ('essentiel','standard','premium','souverain')),
    motif         TEXT,
    statut        TEXT NOT NULL DEFAULT 'ouvert'
                  CHECK (statut IN ('ouvert', 'traite', 'refuse')),
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par      BIGINT REFERENCES utilisateur(id),
    traite_le     TIMESTAMPTZ,
    note_staff    TEXT,
    CHECK (palier_cible <> palier_actuel)
);
CREATE INDEX IF NOT EXISTS idx_demande_palier_tenant
    ON demande_palier (tenant_id, statut);

COMMENT ON TABLE demande_palier IS
    'Demande abonné de changement de palier — acceptation staff via patcher_tenant.';

-- ── RLS ───────────────────────────────────────────────────────────
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['demande_paiement', 'demande_palier']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE  ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS %1$I_tenant ON %1$I', t);
        EXECUTE format($f$
            CREATE POLICY %1$I_tenant ON %1$I
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::BIGINT)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::BIGINT)
        $f$, t);
    END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON demande_paiement, demande_palier TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE demande_paiement_id_seq, demande_palier_id_seq TO app_revue;

-- ── Staff : lister / lire hors contexte tenant ────────────────────
CREATE OR REPLACE FUNCTION billing_lister_demandes_paiement(
    p_statut TEXT DEFAULT NULL
)
RETURNS TABLE (
    id BIGINT,
    tenant_id BIGINT,
    denomination TEXT,
    facture_id BIGINT,
    facture_numero TEXT,
    facture_montant NUMERIC,
    facture_statut TEXT,
    statut TEXT,
    note TEXT,
    cree_le TIMESTAMPTZ,
    cree_par BIGINT,
    traite_le TIMESTAMPTZ,
    note_staff TEXT
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT
        d.id,
        d.tenant_id,
        t.denomination,
        d.facture_id,
        f.numero,
        f.montant,
        f.statut,
        d.statut,
        d.note,
        d.cree_le,
        d.cree_par,
        d.traite_le,
        d.note_staff
    FROM demande_paiement d
    JOIN tenant t ON t.id = d.tenant_id
    JOIN facture f ON f.id = d.facture_id
    WHERE p_statut IS NULL OR d.statut = p_statut
    ORDER BY d.id DESC;
$$;

REVOKE ALL ON FUNCTION billing_lister_demandes_paiement(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION billing_lister_demandes_paiement(TEXT) TO app_revue;

CREATE OR REPLACE FUNCTION billing_lister_demandes_palier(
    p_statut TEXT DEFAULT NULL
)
RETURNS TABLE (
    id BIGINT,
    tenant_id BIGINT,
    denomination TEXT,
    palier_actuel TEXT,
    palier_cible TEXT,
    motif TEXT,
    statut TEXT,
    cree_le TIMESTAMPTZ,
    cree_par BIGINT,
    traite_le TIMESTAMPTZ,
    note_staff TEXT,
    tenant_palier TEXT
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT
        d.id,
        d.tenant_id,
        t.denomination,
        d.palier_actuel,
        d.palier_cible,
        d.motif,
        d.statut,
        d.cree_le,
        d.cree_par,
        d.traite_le,
        d.note_staff,
        t.palier
    FROM demande_palier d
    JOIN tenant t ON t.id = d.tenant_id
    WHERE p_statut IS NULL OR d.statut = p_statut
    ORDER BY d.id DESC;
$$;

REVOKE ALL ON FUNCTION billing_lister_demandes_palier(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION billing_lister_demandes_palier(TEXT) TO app_revue;
