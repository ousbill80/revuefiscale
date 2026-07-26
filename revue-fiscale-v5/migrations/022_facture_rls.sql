-- 022 — FORCE RLS sur facture + intégrité demande_paiement + clôture DEFINER
-- Alignement règle 6 AGENTS : isolation par la base, pas seulement filtre app.
-- Lecture staff cross-tenant : billing_lire_facture / billing_lister_factures (DEFINER).
-- Mutation facture : SET LOCAL via contexte_tenant côté Python.
-- Clôture demandes : SECURITY DEFINER (REVOKE UPDATE/DELETE sur demande_*).

-- ── RLS facture ───────────────────────────────────────────────────
ALTER TABLE facture ENABLE ROW LEVEL SECURITY;
ALTER TABLE facture FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS facture_tenant ON facture;
CREATE POLICY facture_tenant ON facture
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::BIGINT)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::BIGINT);

COMMENT ON TABLE facture IS
    'Facture commerciale abonnement (pas fiscale). Domaine cloisonné : FORCE RLS. '
    'Staff lit via billing_lire_facture / billing_lister_factures (SECURITY DEFINER).';

-- ── Lecture facture hors contexte (staff + résolution tenant) ─────
CREATE OR REPLACE FUNCTION billing_lire_facture(p_id BIGINT)
RETURNS TABLE (
    id BIGINT,
    tenant_id BIGINT,
    denomination TEXT,
    numero TEXT,
    periode DATE,
    montant NUMERIC,
    devise TEXT,
    statut TEXT,
    palier TEXT,
    note TEXT,
    emise_at TIMESTAMPTZ,
    cree_le TIMESTAMPTZ
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT
        f.id,
        f.tenant_id,
        t.denomination,
        f.numero,
        f.periode,
        f.montant,
        f.devise,
        f.statut,
        f.palier,
        f.note,
        f.emise_at,
        f.cree_le
    FROM facture f
    JOIN tenant t ON t.id = f.tenant_id
    WHERE f.id = p_id;
$$;

REVOKE ALL ON FUNCTION billing_lire_facture(BIGINT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION billing_lire_facture(BIGINT) TO app_revue;

-- ── Intégrité : demande_paiement.tenant_id = facture.tenant_id ────
CREATE OR REPLACE FUNCTION trg_demande_paiement_tenant_facture()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_tenant BIGINT;
BEGIN
    SELECT f.tenant_id INTO v_tenant
    FROM facture f
    WHERE f.id = NEW.facture_id;

    IF v_tenant IS NULL THEN
        RAISE EXCEPTION
            'demande_paiement : facture_id % introuvable', NEW.facture_id;
    END IF;

    IF v_tenant <> NEW.tenant_id THEN
        RAISE EXCEPTION
            'demande_paiement : tenant_id (%) ≠ facture.tenant_id (%)',
            NEW.tenant_id, v_tenant;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_demande_paiement_tenant_facture ON demande_paiement;
CREATE TRIGGER trg_demande_paiement_tenant_facture
    BEFORE INSERT OR UPDATE OF tenant_id, facture_id ON demande_paiement
    FOR EACH ROW
    EXECUTE FUNCTION trg_demande_paiement_tenant_facture();

-- ── Clôture staff (REVOKE UPDATE — seul chemin de mutation statut) ─
CREATE OR REPLACE FUNCTION billing_clore_demande_paiement(
    p_id BIGINT,
    p_statut TEXT,
    p_note TEXT DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    n INT;
BEGIN
    IF p_statut IS NULL OR p_statut NOT IN ('traite', 'refuse') THEN
        RAISE EXCEPTION 'billing_clore_demande_paiement : statut invalide %', p_statut;
    END IF;

    UPDATE demande_paiement
    SET
        statut = p_statut,
        traite_le = now(),
        note_staff = NULLIF(btrim(p_note), '')
    WHERE id = p_id
      AND statut = 'ouvert';

    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n > 0;
END;
$$;

CREATE OR REPLACE FUNCTION billing_clore_demande_palier(
    p_id BIGINT,
    p_statut TEXT,
    p_note TEXT DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    n INT;
BEGIN
    IF p_statut IS NULL OR p_statut NOT IN ('traite', 'refuse') THEN
        RAISE EXCEPTION 'billing_clore_demande_palier : statut invalide %', p_statut;
    END IF;

    UPDATE demande_palier
    SET
        statut = p_statut,
        traite_le = now(),
        note_staff = NULLIF(btrim(p_note), '')
    WHERE id = p_id
      AND statut = 'ouvert';

    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n > 0;
END;
$$;

REVOKE ALL ON FUNCTION billing_clore_demande_paiement(BIGINT, TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION billing_clore_demande_palier(BIGINT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION billing_clore_demande_paiement(BIGINT, TEXT, TEXT) TO app_revue;
GRANT EXECUTE ON FUNCTION billing_clore_demande_palier(BIGINT, TEXT, TEXT) TO app_revue;

-- Abonné : INSERT + SELECT seulement (pas d'auto-clôture / suppression file)
REVOKE UPDATE, DELETE ON demande_paiement, demande_palier FROM app_revue;
GRANT SELECT, INSERT ON demande_paiement, demande_palier TO app_revue;
