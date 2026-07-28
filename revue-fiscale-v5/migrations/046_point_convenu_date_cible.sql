-- 046 — Date cible optionnelle sur les points convenus (045).
-- Lors de la restitution, le fiscaliste convient souvent d'une échéance
-- avec le client (« régulariser avant le 15 »). Cette colonne DATE
-- NULLABLE porte cette échéance ; le retard (statut 'a_faire' ET
-- date_cible dépassée) est calculé à la lecture, jamais stocké —
-- signalement consultatif, l'humain décide.

ALTER TABLE point_convenu
    ADD COLUMN IF NOT EXISTS date_cible DATE NULL;

COMMENT ON COLUMN point_convenu.date_cible IS
    'Échéance convenue avec le client (optionnelle) — le retard est '
    'calculé à la lecture (a_faire + date dépassée), jamais stocké.';
