-- Domaine plateforme : file d'emails sortants (invitations, etc.).
-- Pas de tenant_id NOT NULL obligatoire : l'outbox est un journal d'envoi ;
-- le payload ne doit PAS contenir de données missions/balances abonné.

CREATE TABLE IF NOT EXISTS email_outbox (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT REFERENCES tenant(id) ON DELETE SET NULL,
    destinataire    TEXT NOT NULL,
    sujet           TEXT NOT NULL,
    template        TEXT NOT NULL,
    payload         JSONB NOT NULL DEFAULT '{}',
    statut          TEXT NOT NULL DEFAULT 'en_attente'
                    CHECK (statut IN ('en_attente', 'envoye', 'echec', 'simule_dev')),
    tentatives      INT NOT NULL DEFAULT 0,
    dernier_erreur  TEXT,
    cree_le         TIMESTAMPTZ NOT NULL DEFAULT now(),
    envoye_le       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_email_outbox_statut ON email_outbox (statut, cree_le);
CREATE INDEX IF NOT EXISTS idx_email_outbox_tenant ON email_outbox (tenant_id);

COMMENT ON TABLE email_outbox IS
  'File d envoi email (invitations…). En prod sans clé API : statut echec, jamais faux succes silencieux.';
