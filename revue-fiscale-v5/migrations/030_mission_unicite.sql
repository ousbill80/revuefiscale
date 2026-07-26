-- 030 — Unicité mission active par (tenant, contribuable, exercice)
-- Constat dev : doublons réels avec statuts mixtes (cadrage / en_cours).
-- Choix : index unique PARTIEL excluant les missions clôturées — une mission
-- clôturée ne bloque pas une reprise de revue sur le même exercice, et le
-- cycle de vie (réouverture) reste possible sous garde applicative.
-- Déduplication préalable : on garde la mission active la plus récente,
-- les plus anciennes sont clôturées (aucune suppression — FK et dossier
-- de preuve préservés).

WITH actives AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY tenant_id, contribuable_id, exercice
               ORDER BY id DESC
           ) AS rang
    FROM mission
    WHERE statut <> 'cloturee'
)
UPDATE mission m
SET statut = 'cloturee'
FROM actives a
WHERE m.id = a.id
  AND a.rang > 1;

CREATE UNIQUE INDEX IF NOT EXISTS mission_client_exercice_uq
    ON mission (tenant_id, contribuable_id, exercice)
    WHERE statut <> 'cloturee';

COMMENT ON INDEX mission_client_exercice_uq IS
    'Une seule mission active (cadrage / en_cours) par client et par exercice.';
