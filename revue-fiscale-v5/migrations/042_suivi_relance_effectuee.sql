-- 042 — Traçabilité des relances effectuées (suivi de circularisation)
-- Le fiscaliste marque une relance « faite » : on trace la date de la
-- dernière relance et le nombre de relances effectuées, et la date de
-- relance planifiée est effacée (à re-planifier ou reporter).
-- RLS déjà en place via 036 — aucune fiscalité ici.

ALTER TABLE suivi_demande_renseignements
    ADD COLUMN IF NOT EXISTS derniere_relance_le DATE,
    ADD COLUMN IF NOT EXISTS nb_relances INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN suivi_demande_renseignements.derniere_relance_le IS
    'Date de la dernière relance effectuée (marquée par le fiscaliste).';
COMMENT ON COLUMN suivi_demande_renseignements.nb_relances IS
    'Nombre de relances effectuées sur cet item (compteur, défaut 0).';
