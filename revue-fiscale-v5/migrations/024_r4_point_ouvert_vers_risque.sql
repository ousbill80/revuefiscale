-- 024 — R4 : bascule point_ouvert → risque (docs/25)
-- Backfill des points ouverts liés à une conclusion (impôt issu du référentiel).
-- Idempotent (skip si origine_conclusion déjà liée à un risque).
-- point_ouvert reste en lecture legacy ; plus de création à la clôture (code).
-- Pas de code impôt inventé : lignes sans règle liée sont laissées en legacy.

COMMENT ON TABLE point_ouvert IS
    'LEGACY R4 — pont N→N+1 déprécié. Source N+1 = risque (020). Lecture seule.';

INSERT INTO risque (
    tenant_id,
    contribuable_id,
    origine_conclusion_id,
    origine_mission_id,
    impot,
    reference_legale,
    libelle,
    montant_estime,
    probabilite,
    statut,
    exercice_origine
)
SELECT
    po.tenant_id,
    po.contribuable_id,
    po.conclusion_id,
    po.mission_source_id,
    reg.impot,
    NULLIF(trim(rv.reference_article), ''),
    LEFT(trim(po.texte), 2000),
    c.montant,
    'possible',
    CASE po.statut
        WHEN 'clos' THEN 'resolu'
        WHEN 'repris' THEN 'en_traitement'
        ELSE 'ouvert'
    END,
    COALESCE(
        m.exercice,
        EXTRACT(YEAR FROM po.cree_le)::SMALLINT
    )
FROM point_ouvert po
JOIN conclusion c ON c.id = po.conclusion_id
JOIN regle_version rv ON rv.id = c.regle_version_id
JOIN regle reg ON reg.identifiant = rv.regle_id
LEFT JOIN mission m ON m.id = po.mission_source_id
WHERE length(trim(po.texte)) > 0
  AND length(trim(reg.impot)) > 0
  AND NOT EXISTS (
      SELECT 1 FROM risque r
      WHERE r.tenant_id = po.tenant_id
        AND r.origine_conclusion_id = po.conclusion_id
  );
