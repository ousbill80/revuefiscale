/** Mapping volet panorama → thème du registre fiscal (front uniquement). */
export type ThemeRevueId =
  | "tva"
  | "is"
  | "social"
  | "taxes_locales"
  | "contentieux";

export const VOLET_VERS_THEME: Record<string, ThemeRevueId> = {
  completude_declarative: "tva",
  coherence_ca: "tva",
  rapprochement_acomptes: "is",
  deficits_reportables: "is",
  retenue_loyers: "social",
  retenue_honoraires: "social",
  patente: "taxes_locales",
  charge_fiscale: "taxes_locales",
};

export type CompteursPanorama = Record<string, number>;

/** Compte les volets « à examiner » + « à qualifier » pour un thème. */
export function compterAttentionTheme(
  compteursParVolet: Map<string, string>,
  theme: ThemeRevueId,
): number {
  let n = 0;
  for (const [volet, niveau] of compteursParVolet) {
    if (VOLET_VERS_THEME[volet] !== theme) continue;
    if (niveau === "a_examiner" || niveau === "a_qualifier") n += 1;
  }
  return n;
}

export function themePourVolet(volet: string): ThemeRevueId | null {
  return VOLET_VERS_THEME[volet] ?? null;
}
