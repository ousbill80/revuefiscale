-- 023 — Paiements Paystack (abonnement commercial, pas fiscal CGI)
-- Domaine ABONNÉ : tenant_id NOT NULL + FORCE RLS.
-- Webhook charge.success → marquer_payee sous contexte_tenant (SET LOCAL).
-- L'abonné n'appelle jamais marquer_payee directement.

CREATE TABLE IF NOT EXISTS paiement_paystack (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         BIGINT NOT NULL REFERENCES tenant(id),
    facture_id        BIGINT NOT NULL REFERENCES facture(id),
    reference         TEXT NOT NULL,
    statut            TEXT NOT NULL DEFAULT 'initialise'
                      CHECK (statut IN ('initialise', 'succes', 'echec', 'abandonne')),
    amount_xof        INTEGER NOT NULL,
    currency          TEXT NOT NULL DEFAULT 'XOF',
    authorization_url TEXT,
    access_code       TEXT,
    paystack_payload  JSONB,
    cree_le           TIMESTAMPTZ NOT NULL DEFAULT now(),
    maj_le            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT paiement_paystack_reference_unique UNIQUE (reference)
);

CREATE INDEX IF NOT EXISTS idx_paiement_paystack_tenant
    ON paiement_paystack (tenant_id, statut);
CREATE INDEX IF NOT EXISTS idx_paiement_paystack_facture
    ON paiement_paystack (facture_id);

COMMENT ON TABLE paiement_paystack IS
    'Init + suivi checkout Paystack (carte / Mobile Money CI). '
    'Montants commerciaux abonnement (XOF zero-decimal). Domaine cloisonné FORCE RLS.';

-- Intégrité : tenant_id = facture.tenant_id
CREATE OR REPLACE FUNCTION trg_paiement_paystack_tenant_facture()
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
            'paiement_paystack : facture_id % introuvable', NEW.facture_id;
    END IF;

    IF v_tenant <> NEW.tenant_id THEN
        RAISE EXCEPTION
            'paiement_paystack : tenant_id (%) ≠ facture.tenant_id (%)',
            NEW.tenant_id, v_tenant;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_paiement_paystack_tenant_facture ON paiement_paystack;
CREATE TRIGGER trg_paiement_paystack_tenant_facture
    BEFORE INSERT OR UPDATE OF tenant_id, facture_id ON paiement_paystack
    FOR EACH ROW
    EXECUTE FUNCTION trg_paiement_paystack_tenant_facture();

ALTER TABLE paiement_paystack ENABLE ROW LEVEL SECURITY;
ALTER TABLE paiement_paystack FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS paiement_paystack_tenant ON paiement_paystack;
CREATE POLICY paiement_paystack_tenant ON paiement_paystack
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::BIGINT)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::BIGINT);

GRANT SELECT, INSERT, UPDATE ON paiement_paystack TO app_revue;
GRANT USAGE, SELECT ON SEQUENCE paiement_paystack_id_seq TO app_revue;
