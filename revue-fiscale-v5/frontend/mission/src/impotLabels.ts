/**
 * Libellés UI des codes pivot `impot` — taxonomie format pivot.
 * Sources : docs/08-glossaire.md + intitulés des fiches référentiel.
 * Aucun taux, plafond ni condition fiscale ici.
 */

export const CODES_IMPOT_PIVOT = [
  "BIC",
  "TVA",
  "RAS",
  "ITS",
  "CE",
  "IRC",
  "IRVM",
  "PAT",
  "FONC",
  "ENR",
  "TIMBRE",
  "OBL",
  "OBNL",
  "RA",
] as const;

export type CodeImpotPivot = (typeof CODES_IMPOT_PIVOT)[number];

/** Tooltip abréviation — libellé courant, sans barème. */
export const LIBELLES_IMPOT: Record<CodeImpotPivot, string> = {
  BIC: "Bénéfices industriels et commerciaux",
  TVA: "Taxe sur la valeur ajoutée",
  RAS: "Retenue à la source (notamment non-résidents)",
  ITS: "Impôt sur les traitements et salaires",
  CE: "Contribution employeur",
  IRC: "Impôt sur le revenu des créances",
  IRVM: "Impôt sur le revenu des valeurs mobilières",
  PAT: "Contribution des patentes",
  FONC: "Impôt foncier",
  ENR: "Droits d'enregistrement",
  TIMBRE: "Droit de timbre",
  OBL: "Obligations déclaratives (ETII, registres…)",
  OBNL: "Organismes à but non lucratif",
  RA: "Revue analytique (contrôles de cohérence)",
};

/**
 * Hint cadrage — exonérations / allègements.
 * Pas de liste CGI inventée : le millésime épinglé porte les règles.
 */
export const PERIMETRE_EXONERATIONS_HINT =
  "Exonérations et allègements applicables = ceux du référentiel épinglé (règles du millésime, y compris mentions « à confirmer »). Aucune liste CGI n’est figée dans cet écran.";

/**
 * Hint cadrage — dons / libéralités.
 * La fiche produit connue est BIC-CHG-18G-DONS ; plafonds/taux restent dans le YAML.
 */
export const PERIMETRE_DONS_HINT =
  "Dons et libéralités : contrôles éventuels via le référentiel (famille BIC, ex. règle dons / art. 18 G). Les plafonds et taux ne s’affichent pas ici — uniquement à l’exécution du millésime épinglé.";

/** Identifiants de règles déjà présents dans une restitution / a_confirmer. */
export function extraireReglesDonsEtAllegements(regleIds: Iterable<string>): {
  dons: string[];
  allegements: string[];
} {
  const dons: string[] = [];
  const allegements: string[] = [];
  const vus = new Set<string>();
  for (const brut of regleIds) {
    const id = String(brut || "").trim().toUpperCase();
    if (!id || vus.has(id)) continue;
    vus.add(id);
    if (/DONS|LIBERAL|MECENAT/.test(id)) {
      dons.push(id);
      continue;
    }
    // Régimes de faveur / niches nommées dans l’identifiant pivot — pas un inventaire CGI.
    if (/STARTUP|EXONER|ALLEGE/.test(id)) {
      allegements.push(id);
    }
  }
  return { dons, allegements };
}

export function tipImpot(code: string): string {
  const k = code.toUpperCase() as CodeImpotPivot;
  return LIBELLES_IMPOT[k] ?? code;
}
