/**
 * Statuts mission — source unique frontend, alignée sur le backend
 * (backend/plateforme/missions.py : STATUTS_MISSION).
 *
 * Le backend n'accepte que 3 statuts canoniques. Les variantes historiques
 * (cloture, clôturée, terminee…) sont tolérées en lecture seule ici pour
 * d'éventuelles données anciennes, mais ne doivent plus être produites.
 */

export const STATUT_CADRAGE = "cadrage" as const;
export const STATUT_EN_COURS = "en_cours" as const;
export const STATUT_CLOTUREE = "cloturee" as const;

export const STATUTS_MISSION = [
  STATUT_CADRAGE,
  STATUT_EN_COURS,
  STATUT_CLOTUREE,
] as const;

export type StatutMission = (typeof STATUTS_MISSION)[number];

/** Variantes legacy considérées comme « clôturée » en lecture. */
const VARIANTES_CLOTURE = new Set([
  STATUT_CLOTUREE,
  "cloture",
  "clôturée",
  "terminee",
  "terminée",
]);

const LIBELLES: Record<string, string> = {
  [STATUT_CADRAGE]: "Cadrage",
  [STATUT_EN_COURS]: "En cours",
  [STATUT_CLOTUREE]: "Clôturée",
  cloture: "Clôturée",
  "clôturée": "Clôturée",
  terminee: "Terminée",
  "terminée": "Terminée",
};

export function libelleStatut(statut: string): string {
  return LIBELLES[statut.toLowerCase()] ?? statut;
}

export function estStatutCloture(statut: string): boolean {
  return VARIANTES_CLOTURE.has(statut.toLowerCase());
}

/** Mission active = non clôturée (cadrage OU en_cours). */
export function estMissionActive(statut: string): boolean {
  return !estStatutCloture(statut);
}

export function estStatutEnCours(statut: string): boolean {
  return statut.toLowerCase() === STATUT_EN_COURS;
}

export function estStatutCadrage(statut: string): boolean {
  return statut.toLowerCase() === STATUT_CADRAGE;
}
