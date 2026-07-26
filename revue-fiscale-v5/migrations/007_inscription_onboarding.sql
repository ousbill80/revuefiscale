-- 007 — Inscription OTP (plateforme) + téléphone utilisateur + onboarding (abonné RLS)

-- ── Domaine plateforme : pending pré-tenant (PAS de tenant_id, PAS de RLS) ──
CREATE TABLE IF NOT EXISTS inscription_pending (
    id                   BIGSERIAL PRIMARY KEY,
    email                TEXT NOT NULL UNIQUE,
    otp_hash             TEXT NOT NULL,
    expire_le            TIMESTAMPTZ NOT NULL,
    essais               INT NOT NULL DEFAULT 0,
    verifie_le           TIMESTAMPTZ,
    jeton_hash           TEXT,
    jeton_expire_le      TIMESTAMPTZ,
    cree_le              TIMESTAMPTZ NOT NULL DEFAULT now(),
    derniere_demande_le  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_inscription_pending_jeton
    ON inscription_pending (jeton_hash)
    WHERE jeton_hash IS NOT NULL;

-- ── Domaine abonné : téléphone E.164 ───────────────────────────────────────
ALTER TABLE utilisateur
    ADD COLUMN IF NOT EXISTS telephone TEXT;

-- ── Domaine abonné : état d'onboarding ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS onboarding_etat (
    tenant_id    BIGINT PRIMARY KEY REFERENCES tenant(id),
    etapes       JSONB NOT NULL DEFAULT '{}'::jsonb,
    complete_le  TIMESTAMPTZ,
    cree_le      TIMESTAMPTZ NOT NULL DEFAULT now(),
    maj_le       TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['onboarding_etat']
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

GRANT SELECT, INSERT, UPDATE, DELETE ON inscription_pending, onboarding_etat TO app_revue;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_revue;
