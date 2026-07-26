-- 031 — Validation « 4 yeux » légère des conclusions
-- valide_par / valide_le : second regard sur une conclusion déjà évaluée
-- (amendee_par posé). Auto-validation acceptée (cabinet solo) mais tracée
-- au journal. Barrière de clôture : les anomalies doivent être validées.

ALTER TABLE conclusion
    ADD COLUMN IF NOT EXISTS valide_par TEXT,
    ADD COLUMN IF NOT EXISTS valide_le  TIMESTAMPTZ;

COMMENT ON COLUMN conclusion.valide_par IS
    'Validateur (second regard) — NULL tant que la conclusion n''est pas validée.';
COMMENT ON COLUMN conclusion.valide_le IS
    'Horodatage de la validation — remis à NULL si le statut est ré-amendé.';

CREATE INDEX IF NOT EXISTS idx_conclusion_validation
    ON conclusion (tenant_id, statut)
    WHERE valide_par IS NULL;
