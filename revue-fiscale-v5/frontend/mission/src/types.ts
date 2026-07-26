export type ProfilMission = {
  regime: string;
  forme_juridique: string;
  secteur?: string;
  type_entite?: string;
  cross_border?: boolean;
};

export type SessionAuth = {
  jeton: string;
  tenant_id: number;
  email: string;
  tenant_denomination: string;
  role: string;
};

export type Passage = {
  lignes: Array<Record<string, unknown>>;
  total_reintegration: string | number;
  total_deduction: string | number;
  solde_net: string | number;
};

export type ScoreRisque = {
  score: number;
  comptages: Record<string, number>;
  avertissement: string;
};

export type ConclusionRestitution = {
  id?: number;
  regle_id: string;
  montant?: string | number | null;
  sens?: string | null;
  niveau_risque?: string | null;
  commentaire?: string | null;
  statut?: string | null;
  piece_mission_id?: number | null;
  amendee_par?: string | null;
  valide_par?: string | null;
  valide_le?: string | null;
};

export type IdentificationRestitution = {
  contribuable_id?: number | null;
  contribuable_denomination?: string | null;
  contribuable_ncc?: string | null;
  contribuable_rccm?: string | null;
  contribuable_dfe?: string | null;
  contribuable_forme?: string | null;
  contribuable_forme_juridique?: string | null;
  contribuable_regime_fiscal?: string | null;
  contribuable_siege?: string | null;
  contribuable_commune?: string | null;
  contribuable_centre_impots?: string | null;
  exercice?: number | null;
  statut?: string | null;
  profil?: Record<string, unknown>;
  type_engagement?: string | null;
  type_engagement_libelle?: string | null;
  perimetre_impots?: string[] | null;
  revue_partielle?: boolean;
  exclusions_declarees?: string | null;
  seuil_signification?: string | null;
  objectifs?: Array<{ id?: number; libelle: string; ordre?: number }> | null;
  objectifs_fiscaux?: Array<{
    id: number;
    impot: string;
    exercices: number[];
    dans_perimetre: boolean;
    motif_exclusion?: string | null;
  }> | null;
  taches?: Array<{
    id: number;
    objectif_id: number;
    impot?: string | null;
    regle_id?: string | null;
    /** 8 statuts serveur : a_faire|en_cours|bloquee|conforme|anomalie|non_verifiable|sous_seuil|hors_perimetre */
    statut: string;
    assignee_a?: number | null;
    bloquee_par?: number[];
    /** Avec en_cours|bloquee : libellé UX « documenté » (pas un 9e statut). */
    piece_attendue?: string | null;
    conclusion_id?: number | null;
  }> | null;
  relances_client?: Array<{
    id: number;
    regle_id?: string | null;
    piece_attendue?: string | null;
    statut: string;
  }> | null;
};

export type Restitution = {
  mission_id: number;
  execution_id: number | null;
  version_referentiel_id?: number | null;
  version_referentiel_libelle?: string | null;
  a_confirmer_total?: number;
  a_confirmer_regles?: Array<{
    regle_id: string;
    nb: number;
    mentions: string[];
  }>;
  avertissement_a_confirmer?: string | null;
  passage: Passage;
  score_risque: ScoreRisque;
  conclusions: ConclusionRestitution[];
  rapport_markdown: string;
  identification?: IdentificationRestitution;
};

export type AuditEntree = {
  id?: number | null;
  horodatage?: string | null;
  acteur: string;
  action: string;
  charge_utile?: Record<string, unknown>;
  hash?: string | null;
  hash_court?: string | null;
  hash_prec?: string | null;
};

export type AuditSynthese = {
  total: number;
  par_action: Record<string, number>;
  ecriture_seule?: boolean;
  chaine_hash?: boolean;
  note?: string;
};

export type AuditJournal = {
  mission_id: number;
  limite?: number;
  entrees: AuditEntree[];
  synthese?: AuditSynthese;
};
