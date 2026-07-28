-- 047 — Responsable de mission (email d'un utilisateur du tenant).
-- Dans un cabinet à plusieurs collaborateurs, chaque mission porte un
-- responsable identifié ; l'associé lit la répartition de la charge
-- (GET /cabinet/charge — consultatif, l'humain décide).
--
-- PAS DE FK dure vers utilisateur(id) : la table utilisateur est sous
-- RLS forcée par tenant (comme mission) mais l'email est l'identifiant
-- métier utilisé partout ailleurs (journal_audit.acteur, visas
-- vise_par, points convenus…) ; une FK sur id imposerait un ON DELETE
-- et casserait la lisibilité de l'historique si le compte est retiré.
-- La cohérence (utilisateur ACTIF du tenant) est vérifiée à l'écriture
-- par backend/plateforme/responsable_mission.py — écriture sur clic
-- explicite, journalisée.

ALTER TABLE mission
    ADD COLUMN IF NOT EXISTS responsable_email TEXT NULL;

COMMENT ON COLUMN mission.responsable_email IS
    'Email du responsable de la mission — utilisateur actif du tenant, '
    'vérifié à l''écriture (pas de FK dure : identifiant métier email, '
    'historique lisible même si le compte est désactivé).';
