/**
 * Suivi réviseur = statut serveur `tache` (8 valeurs) — hors calcul fiscal.
 * Pas de localStorage : une seule vérité = API / restitution.
 *
 * Libellé UX « Documenté » (optionnel) = `en_cours`|`bloquee` + `piece_attendue`
 * non vide — ce n’est PAS un statut distinct côté serveur.
 */

export type StatutTache =
  | "a_faire"
  | "en_cours"
  | "bloquee"
  | "conforme"
  | "anomalie"
  | "non_verifiable"
  | "sous_seuil"
  | "hors_perimetre";

/** @deprecated alias — préférer StatutTache */
export type StatutTraitement = StatutTache;

export type TraitementRisque = {
  regle_id: string;
  statut: StatutTache;
  /** Miroir de `tache.piece_attendue` (pas un 2e store). */
  note: string;
  maj_le: string;
  tache_id?: number;
};

export const STATUTS_TACHE: Array<{
  value: StatutTache;
  label: string;
  hint: string;
}> = [
  {
    value: "a_faire",
    label: "À faire",
    hint: "Tâche à instruire par le réviseur.",
  },
  {
    value: "en_cours",
    label: "En cours",
    hint: "Instruction démarrée (pièces, entretiens).",
  },
  {
    value: "bloquee",
    label: "Bloquée",
    hint: "En attente d’une dépendance ou d’une pièce.",
  },
  {
    value: "conforme",
    label: "Conforme",
    hint: "Résultat : position revue conforme.",
  },
  {
    value: "anomalie",
    label: "Anomalie",
    hint: "Résultat : anomalie retenue.",
  },
  {
    value: "non_verifiable",
    label: "Non vérifiable",
    hint: "Résultat : données insuffisantes pour conclure.",
  },
  {
    value: "sous_seuil",
    label: "Sous seuil",
    hint: "Résultat : sous le seuil de signification de la mission.",
  },
  {
    value: "hors_perimetre",
    label: "Hors périmètre",
    hint: "Résultat : écarté du périmètre d’engagement.",
  },
];

/** Alias UI historique — mêmes 8 statuts serveur. */
export const STATUTS_TRAITEMENT = STATUTS_TACHE;

const STATUTS_SET = new Set<string>(STATUTS_TACHE.map((s) => s.value));

const STATUTS_OUVERTS = new Set<StatutTache>([
  "a_faire",
  "en_cours",
  "bloquee",
  "anomalie",
  "non_verifiable",
]);

const STATUTS_CLOTURES = new Set<StatutTache>([
  "conforme",
  "sous_seuil",
  "hors_perimetre",
]);

/** Normalise une valeur API vers un des 8 statuts (défaut `a_faire`). */
export function normaliserStatutTache(
  statut: string | null | undefined,
): StatutTache {
  const s = String(statut || "a_faire").toLowerCase();
  return STATUTS_SET.has(s) ? (s as StatutTache) : "a_faire";
}

/**
 * UX seulement : « documenté » = workflow ouvert + pièce attendue.
 * Persistance = `statut` serveur + `piece_attendue`, jamais un pseudo-statut.
 */
export function estDocumenteUx(
  statut: string | null | undefined,
  pieceAttendue?: string | null,
): boolean {
  const s = normaliserStatutTache(statut);
  if (s !== "en_cours" && s !== "bloquee") return false;
  return Boolean(pieceAttendue && String(pieceAttendue).trim());
}

export function libelleStatutTache(
  statut: string | null | undefined,
  pieceAttendue?: string | null,
): string {
  const s = normaliserStatutTache(statut);
  const base =
    STATUTS_TACHE.find((x) => x.value === s)?.label ?? "À faire";
  // documente (UX) → en_cours|bloquee + piece_attendue
  if (estDocumenteUx(s, pieceAttendue)) {
    return `${base} · documenté`;
  }
  return base;
}

/** Identité : l’UI envoie déjà le statut serveur. */
export function traitementVersStatutTache(st: StatutTache): string {
  return st;
}

/** Lecture API → UI : statut serveur tel quel (plus de collapse vers `documente`). */
export function statutTacheVersTraitement(
  statut: string | null | undefined,
  _pieceAttendue?: string | null,
): StatutTache {
  return normaliserStatutTache(statut);
}

export function synthetiserTraitements(
  regleIds: string[],
  map: Record<string, TraitementRisque>,
): Record<StatutTache, number> {
  const out: Record<StatutTache, number> = {
    a_faire: 0,
    en_cours: 0,
    bloquee: 0,
    conforme: 0,
    anomalie: 0,
    non_verifiable: 0,
    sous_seuil: 0,
    hors_perimetre: 0,
  };
  for (const id of regleIds) {
    const s = map[id]?.statut ?? "a_faire";
    out[s] += 1;
  }
  return out;
}

export function compterOuvertsClotures(
  synth: Record<StatutTache, number>,
): { ouverts: number; clotures: number } {
  let ouverts = 0;
  let clotures = 0;
  for (const s of STATUTS_OUVERTS) ouverts += synth[s];
  for (const s of STATUTS_CLOTURES) clotures += synth[s];
  return { ouverts, clotures };
}

export function classeBadgeTraitement(
  statut: string | null | undefined,
  pieceAttendue?: string | null,
): string {
  const s = normaliserStatutTache(statut);
  const parts = [`badge-traitement`, `badge-traitement--${s}`];
  if (estDocumenteUx(s, pieceAttendue)) {
    parts.push("badge-traitement--documente");
  }
  return parts.join(" ");
}
