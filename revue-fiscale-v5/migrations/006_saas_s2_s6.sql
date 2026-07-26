-- 006 — S2–S6 : invitations, forme contribuable, factures, lien acces client
-- Domaine abonne : invitation, lien_acces_mission → tenant_id + RLS
-- Domaine plateforme : facture → tenant_id sans RLS (billing SECURITY DEFINER)

-- ── Contribuable : forme PM/PP (legere) ───────────────────────────
ALTER TABLE contribuable
    ADD COLUMN IF NOT EXISTS forme TEXT
    CHECK (forme IS NULL OR forme IN ('pm', 'pp'));

-- ── Invitation utilisateurs cabinet ───────────────────────────────
CREATE TABLE IF NOT EXISTS invitation (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenant(id),
    email         TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'reviseur', 'lecteur')),
    token_hash    TEXT NOT NULL UNIQUE,
    statut        TEXT NOT NULL DEFAULT 'en_attente'
                  CHECK (statut IN ('en_attente', 'acceptee', 'annulee', 'expiree')),
    invitee_par   BIGINT REFERENCES utilisateur(id),
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expire_le     TIMESTAMPTZ NOT NULL,
    acceptee_le   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_invitation_tenant ON invitation (tenant_id);
CREATE INDEX IF NOT EXISTS idx_invitation_email ON invitation (tenant_id, email);

-- ── Lien acces mission (portail client lecture seule) ─────────────
CREATE TABLE IF NOT EXISTS lien_acces_mission (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenant(id),
    mission_id    BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    email_contact TEXT,
    token_hash    TEXT NOT NULL UNIQUE,
    statut        TEXT NOT NULL DEFAULT 'actif'
                  CHECK (statut IN ('actif', 'revoque', 'expire')),
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expire_le     TIMESTAMPTZ NOT NULL,
    cree_par      BIGINT REFERENCES utilisateur(id)
);
CREATE INDEX IF NOT EXISTS idx_lien_acces_tenant ON lien_acces_mission (tenant_id);
CREATE INDEX IF NOT EXISTS idx_lien_acces_mission ON lien_acces_mission (mission_id);

-- ── Facture (montants commerciaux abonnement — PAS fiscaux) ───────
CREATE TABLE IF NOT EXISTS facture (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  BIGINT NOT NULL REFERENCES tenant(id),
    numero     TEXT NOT NULL UNIQUE,
    periode    DATE NOT NULL,
    montant    NUMERIC(18,2) NOT NULL CHECK (montant >= 0),
    devise     TEXT NOT NULL DEFAULT 'XOF',
    statut     TEXT NOT NULL DEFAULT 'brouillon'
               CHECK (statut IN ('brouillon', 'emise', 'payee', 'annulee')),
    palier     TEXT,
    note       TEXT,
    emise_at   TIMESTAMPTZ,
    pdf_path   TEXT,
    cree_le    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_facture_tenant ON facture (tenant_id, periode);

-- ── RLS tables abonne ─────────────────────────────────────────────
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['invitation', 'lien_acces_mission']
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

-- Facture : domaine plateforme (billing lit via SECURITY DEFINER, pas de RLS abonne)
-- Pas de FORCE RLS — lecture/ecriture billing sans contexte tenant.

GRANT SELECT, INSERT, UPDATE, DELETE ON invitation, lien_acces_mission, facture TO app_revue;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_revue;

-- Lookup invitation publique (acceptation sans JWT tenant)
CREATE OR REPLACE FUNCTION auth_lookup_invitation(p_token_hash TEXT)
RETURNS TABLE (
    id BIGINT,
    tenant_id BIGINT,
    email TEXT,
    role TEXT,
    statut TEXT,
    expire_le TIMESTAMPTZ
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT i.id, i.tenant_id, i.email, i.role, i.statut, i.expire_le
    FROM invitation i
    WHERE i.token_hash = p_token_hash
    LIMIT 1;
$$;

REVOKE ALL ON FUNCTION auth_lookup_invitation(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_lookup_invitation(TEXT) TO app_revue;

-- Lookup lien client (portail lecture seule)
CREATE OR REPLACE FUNCTION client_lookup_lien(p_token_hash TEXT)
RETURNS TABLE (
    id BIGINT,
    tenant_id BIGINT,
    mission_id BIGINT,
    email_contact TEXT,
    statut TEXT,
    expire_le TIMESTAMPTZ
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT l.id, l.tenant_id, l.mission_id, l.email_contact, l.statut, l.expire_le
    FROM lien_acces_mission l
    WHERE l.token_hash = p_token_hash
    LIMIT 1;
$$;

REVOKE ALL ON FUNCTION client_lookup_lien(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION client_lookup_lien(TEXT) TO app_revue;

-- Contestations pour console editorial (sans balances/conclusions)
CREATE OR REPLACE FUNCTION editorial_lister_contestations()
RETURNS TABLE (
    id BIGINT,
    tenant_id BIGINT,
    tenant_denomination TEXT,
    regle_id TEXT,
    version_ref TEXT,
    motif TEXT,
    statut TEXT,
    reponse TEXT,
    traitee_le TIMESTAMPTZ
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT
        c.id,
        c.tenant_id,
        t.denomination,
        c.regle_id,
        c.version_ref,
        c.motif,
        c.statut,
        c.reponse,
        c.traitee_le
    FROM contestation c
    JOIN tenant t ON t.id = c.tenant_id
    ORDER BY c.id DESC
    LIMIT 500;
$$;

REVOKE ALL ON FUNCTION editorial_lister_contestations() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION editorial_lister_contestations() TO app_revue;

-- Metrage IA agrege pour billing (tokens uniquement, pas de contenu)
CREATE OR REPLACE FUNCTION billing_metrage_tenant(p_tenant_id BIGINT)
RETURNS TABLE (
    modele TEXT,
    usage TEXT,
    n_appels BIGINT,
    tokens_entree BIGINT,
    tokens_sortie BIGINT,
    cout_estime NUMERIC
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT
        m.modele,
        m.usage,
        count(*)::BIGINT,
        coalesce(sum(m.tokens_entree), 0)::BIGINT,
        coalesce(sum(m.tokens_sortie), 0)::BIGINT,
        coalesce(sum(m.cout_estime), 0)
    FROM metrage_ia m
    WHERE m.tenant_id = p_tenant_id
    GROUP BY m.modele, m.usage
    ORDER BY m.modele, m.usage;
$$;

REVOKE ALL ON FUNCTION billing_metrage_tenant(BIGINT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION billing_metrage_tenant(BIGINT) TO app_revue;

-- Factures : lecture/ecriture billing sans RLS
CREATE OR REPLACE FUNCTION billing_lister_factures(p_tenant_id BIGINT DEFAULT NULL)
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
    WHERE p_tenant_id IS NULL OR f.tenant_id = p_tenant_id
    ORDER BY f.id DESC;
$$;

REVOKE ALL ON FUNCTION billing_lister_factures(BIGINT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION billing_lister_factures(BIGINT) TO app_revue;

-- Seeds staff editorial + ops (mdp documentes docs/11)
INSERT INTO staff_2aaz (email, password_hash, role, actif)
VALUES
    (
        'editorial@2aaz.ci',
        'scrypt$f28d540ad6ab9bd3336eac2a80d9f0db$e243a3bec6c36adf16358fb7c30554215ab7f8c8f8c6ffc453e4c896b008a1c5',
        'editorial',
        TRUE
    ),
    (
        'ops@2aaz.ci',
        'scrypt$19359ab0e547ff4f00bc921b45345011$3b6294d81946d98dd35e9ef50a9f8986557f4e9e2071b81594ab5ddd424843a2',
        'ops',
        TRUE
    )
ON CONFLICT (email) DO NOTHING;
