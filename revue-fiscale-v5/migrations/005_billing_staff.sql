-- 005 — Admin billing : staff 2AàZ + historique abonnement (domaine plateforme)
-- Domaine PLATEFORME : pas de RLS abonne. Quota reste cloisonne ;
-- lecture billing via fonctions SECURITY DEFINER (colonnes metrage uniquement).

CREATE TABLE IF NOT EXISTS staff_2aaz (
    id            BIGSERIAL PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('billing', 'editorial', 'ops')),
    actif         BOOLEAN NOT NULL DEFAULT TRUE,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS abonnement (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenant(id),
    palier        TEXT NOT NULL CHECK (palier IN ('essentiel', 'standard', 'premium', 'souverain')),
    periode_debut DATE NOT NULL,
    periode_fin   DATE,
    statut        TEXT NOT NULL CHECK (statut IN ('actif', 'suspendu', 'resilie')),
    note          TEXT,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (periode_fin IS NULL OR periode_fin >= periode_debut)
);
CREATE INDEX IF NOT EXISTS idx_abonnement_tenant ON abonnement (tenant_id);

-- Contrainte statut tenant (idempotente)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'tenant_statut_check'
    ) THEN
        ALTER TABLE tenant
            ADD CONSTRAINT tenant_statut_check
            CHECK (statut IN ('actif', 'suspendu', 'resilie'));
    END IF;
EXCEPTION
    WHEN check_violation THEN
        RAISE NOTICE 'tenant.statut contient des valeurs hors enum — contrainte non ajoutee';
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON staff_2aaz, abonnement TO app_revue;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_revue;

-- Lookup staff : SECURITY DEFINER (meme modele que auth_lookup_utilisateur)
CREATE OR REPLACE FUNCTION auth_lookup_staff(p_email TEXT)
RETURNS TABLE (
    id BIGINT,
    email TEXT,
    role TEXT,
    actif BOOLEAN,
    password_hash TEXT
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT s.id, s.email, s.role, s.actif, s.password_hash
    FROM staff_2aaz s
    WHERE s.email = lower(trim(p_email))
    LIMIT 1;
$$;

REVOKE ALL ON FUNCTION auth_lookup_staff(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_lookup_staff(TEXT) TO app_revue;

-- Liste abonnes + dernier abonnement + dernier quota (sans balances/conclusions)
CREATE OR REPLACE FUNCTION billing_lister_tenants()
RETURNS TABLE (
    tenant_id BIGINT,
    denomination TEXT,
    type TEXT,
    palier TEXT,
    statut TEXT,
    cree_le TIMESTAMPTZ,
    abonnement_id BIGINT,
    abonnement_statut TEXT,
    abonnement_palier TEXT,
    abonnement_debut DATE,
    abonnement_fin DATE,
    quota_periode DATE,
    missions_incluses INT,
    missions_utilisees INT,
    appels_modele INT,
    tokens_entree BIGINT,
    tokens_sortie BIGINT,
    cout_estime NUMERIC
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT
        t.id,
        t.denomination,
        t.type,
        t.palier,
        t.statut,
        t.cree_le,
        a.id,
        a.statut,
        a.palier,
        a.periode_debut,
        a.periode_fin,
        q.periode,
        q.missions_incluses,
        q.missions_utilisees,
        q.appels_modele,
        q.tokens_entree,
        q.tokens_sortie,
        q.cout_estime
    FROM tenant t
    LEFT JOIN LATERAL (
        SELECT ab.*
        FROM abonnement ab
        WHERE ab.tenant_id = t.id
        ORDER BY ab.cree_le DESC, ab.id DESC
        LIMIT 1
    ) a ON TRUE
    LEFT JOIN LATERAL (
        SELECT qu.*
        FROM quota qu
        WHERE qu.tenant_id = t.id
        ORDER BY qu.periode DESC
        LIMIT 1
    ) q ON TRUE
    ORDER BY t.id;
$$;

REVOKE ALL ON FUNCTION billing_lister_tenants() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION billing_lister_tenants() TO app_revue;

CREATE OR REPLACE FUNCTION billing_quotas_tenant(p_tenant_id BIGINT)
RETURNS TABLE (
    periode DATE,
    missions_incluses INT,
    missions_utilisees INT,
    appels_modele INT,
    tokens_entree BIGINT,
    tokens_sortie BIGINT,
    cout_estime NUMERIC
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT
        q.periode,
        q.missions_incluses,
        q.missions_utilisees,
        q.appels_modele,
        q.tokens_entree,
        q.tokens_sortie,
        q.cout_estime
    FROM quota q
    WHERE q.tenant_id = p_tenant_id
    ORDER BY q.periode DESC;
$$;

REVOKE ALL ON FUNCTION billing_quotas_tenant(BIGINT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION billing_quotas_tenant(BIGINT) TO app_revue;

-- Seed staff demo locale — mdp documente dans .env.example (BILLING_DEMO_PASSWORD)
-- Hash scrypt (meme format que hasher_mot_de_passe), pas de secret en clair ici.
INSERT INTO staff_2aaz (email, password_hash, role, actif)
VALUES (
    'billing@2aaz.ci',
    'scrypt$798580a4dfc63626346dcaade094e80b$f7c4a15588701d7b40a90d8d9159d597c31497087b3aaa7444562df47e48929e',
    'billing',
    TRUE
)
ON CONFLICT (email) DO NOTHING;
