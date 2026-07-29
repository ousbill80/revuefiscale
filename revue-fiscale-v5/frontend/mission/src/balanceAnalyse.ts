/** Analyse locale d’une balance SYSCOHADA — structure, pas de calcul fiscal. */

export type LigneBalancePreview = {
  compte: string;
  libelle: string;
  debit: number;
  credit: number;
};

export type CouvertureClasse = {
  classe: string;
  label: string;
  presente: boolean;
  n: number;
};

export type ChecklistItem = {
  id: string;
  label: string;
  statut: "ok" | "warn" | "ko" | "info";
  detail?: string;
};

export type BalanceAnalyse = {
  ok: boolean;
  erreurs: string[];
  avertissements: string[];
  nbLignes: number;
  totalDebit: number;
  totalCredit: number;
  ecart: number;
  equilibre: boolean;
  classes: Array<{ classe: string; n: number; label: string }>;
  /** Couverture pédagogique des classes 1–7 (structure SYSCOHADA). */
  couverture: CouvertureClasse[];
  classesManquantes: string[];
  /** Points de contrôle structurels avant lancement — aucun seuil fiscal. */
  checklistStructurelle: ChecklistItem[];
  doublons: string[];
  lignes: LigneBalancePreview[];
  fictif: boolean;
  avertissementSource: string | null;
};

const CLASSE_LABELS: Record<string, string> = {
  "1": "Financement permanent",
  "2": "Actif immobilisé",
  "3": "Stocks",
  "4": "Tiers",
  "5": "Trésorerie",
  "6": "Charges",
  "7": "Produits",
  "8": "Autres / spéciaux",
};

/** Classes usuelles d’une balance de revue (hors classe 8). */
const CLASSES_REVUE = ["1", "2", "3", "4", "5", "6", "7"] as const;

const ANALYSE_VIDE: Omit<
  BalanceAnalyse,
  "ok" | "erreurs" | "avertissements" | "fictif" | "avertissementSource"
> = {
  nbLignes: 0,
  totalDebit: 0,
  totalCredit: 0,
  ecart: 0,
  equilibre: false,
  classes: [],
  couverture: CLASSES_REVUE.map((classe) => ({
    classe,
    label: CLASSE_LABELS[classe] ?? "",
    presente: false,
    n: 0,
  })),
  classesManquantes: [...CLASSES_REVUE],
  checklistStructurelle: [],
  doublons: [],
  lignes: [],
};

function toNum(v: unknown): number {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  const s = String(v ?? "0")
    .trim()
    .replace(/\s/g, "")
    .replace(",", ".");
  if (!s) return 0;
  const n = Number(s);
  return Number.isFinite(n) ? n : NaN;
}

function construireCouverture(
  classCount: Map<string, number>,
): { couverture: CouvertureClasse[]; classesManquantes: string[] } {
  const couverture = CLASSES_REVUE.map((classe) => {
    const n = classCount.get(classe) ?? 0;
    return {
      classe,
      label: CLASSE_LABELS[classe] ?? "",
      presente: n > 0,
      n,
    };
  });
  const classesManquantes = couverture
    .filter((c) => !c.presente)
    .map((c) => c.classe);
  return { couverture, classesManquantes };
}

function construireChecklistStructurelle(params: {
  nbLignes: number;
  equilibre: boolean;
  ecart: number;
  erreurs: string[];
  doublons: string[];
  fictif: boolean;
  classesManquantes: string[];
  couverture: CouvertureClasse[];
}): ChecklistItem[] {
  const items: ChecklistItem[] = [];

  items.push({
    id: "lignes",
    label: "Lignes de comptes présentes",
    statut: params.nbLignes > 0 ? "ok" : "ko",
    detail:
      params.nbLignes > 0
        ? `${params.nbLignes} ligne${params.nbLignes > 1 ? "s" : ""} lue${params.nbLignes > 1 ? "s" : ""}`
        : "Aucune ligne exploitable",
  });

  items.push({
    id: "equilibre",
    label: "Équilibre débit / crédit",
    statut: params.nbLignes === 0 ? "ko" : params.equilibre ? "ok" : "ko",
    detail: params.equilibre
      ? "Totaux alignés (contrôle structurel)"
      : `Écart ${params.ecart.toLocaleString("fr-FR")} (débit − crédit)`,
  });

  const cl67 = params.couverture.filter(
    (c) => (c.classe === "6" || c.classe === "7") && c.presente,
  );
  items.push({
    id: "charges-produits",
    label: "Charges (6) et produits (7)",
    statut:
      cl67.length === 2 ? "ok" : cl67.length === 1 ? "warn" : "warn",
    detail:
      cl67.length === 2
        ? "Classes 6 et 7 présentes"
        : cl67.length === 1
          ? `Classe ${cl67[0].classe} seule — vérifier la couverture du compte de résultat`
          : "Classes 6/7 absentes — revue du résultat potentiellement limitée",
  });

  items.push({
    id: "couverture",
    label: "Couverture classes 1–7",
    statut:
      params.classesManquantes.length === 0
        ? "ok"
        : params.classesManquantes.length <= 2
          ? "warn"
          : "warn",
    detail:
      params.classesManquantes.length === 0
        ? "Toutes les classes usuelles sont représentées"
        : `Manquantes : ${params.classesManquantes.join(", ")} (informationnel — pas un refus automatique)`,
  });

  items.push({
    id: "doublons",
    label: "Comptes uniques",
    statut: params.doublons.length === 0 ? "ok" : "warn",
    detail:
      params.doublons.length === 0
        ? "Pas de doublon de numéro de compte"
        : `${params.doublons.length} compte(s) en double — à consolider côté source`,
  });

  items.push({
    id: "format",
    label: "Format lisible",
    statut: params.erreurs.length === 0 && params.nbLignes > 0 ? "ok" : "ko",
    detail:
      params.erreurs.length === 0
        ? "Structure JSON/CSV cohérente"
        : `${params.erreurs.length} erreur(s) de structure`,
  });

  if (params.fictif) {
    items.push({
      id: "fictif",
      label: "Jeu FICTIF",
      statut: "warn",
      detail:
        "Montants de démonstration — non opposables, usage calage / formation uniquement",
    });
  }

  return items;
}

function analyserLignes(
  rawLignes: unknown[],
  meta?: { avertissement?: string | null },
): BalanceAnalyse {
  const erreurs: string[] = [];
  const avertissements: string[] = [];
  const lignes: LigneBalancePreview[] = [];
  const vus = new Map<string, number>();

  rawLignes.forEach((raw, i) => {
    if (!raw || typeof raw !== "object") {
      erreurs.push(`Ligne ${i + 1} : objet attendu`);
      return;
    }
    const o = raw as Record<string, unknown>;
    const compte = String(o.compte ?? "").trim();
    if (!compte) {
      erreurs.push(`Ligne ${i + 1} : compte vide`);
      return;
    }
    const debit = toNum(o.debit);
    const credit = toNum(o.credit);
    if (Number.isNaN(debit)) {
      erreurs.push(`Ligne ${i + 1} (${compte}) : débit non numérique`);
      return;
    }
    if (Number.isNaN(credit)) {
      erreurs.push(`Ligne ${i + 1} (${compte}) : crédit non numérique`);
      return;
    }
    if (debit < 0 || credit < 0) {
      avertissements.push(
        `Ligne ${compte} : montant négatif — vérifier le sens de saisie SYSCOHADA`,
      );
    }
    if (debit > 0 && credit > 0) {
      avertissements.push(
        `Ligne ${compte} : débit et crédit tous deux renseignés — soldes nets attendus en revue`,
      );
    }
    vus.set(compte, (vus.get(compte) ?? 0) + 1);
    lignes.push({
      compte,
      libelle: String(o.libelle ?? "").trim() || "—",
      debit,
      credit,
    });
  });

  if (!lignes.length && !erreurs.length) {
    erreurs.push("Aucune ligne de compte");
  }

  const doublons = [...vus.entries()]
    .filter(([, n]) => n > 1)
    .map(([c]) => c);
  if (doublons.length) {
    avertissements.push(
      `Comptes en double : ${doublons.slice(0, 5).join(", ")}${doublons.length > 5 ? "…" : ""} — consolider avant import si le logiciel exporte des sous-périodes`,
    );
  }

  const totalDebit = lignes.reduce((s, l) => s + l.debit, 0);
  const totalCredit = lignes.reduce((s, l) => s + l.credit, 0);
  const ecart = Math.round((totalDebit - totalCredit) * 100) / 100;
  const equilibre = Math.abs(ecart) < 0.005;
  if (lignes.length && !equilibre) {
    erreurs.push(
      `Balance déséquilibrée : écart ${ecart.toLocaleString("fr-FR")} (débit − crédit). Le moteur refusera l’import tant que les totaux ne s’alignent pas.`,
    );
  }

  const classCount = new Map<string, number>();
  for (const l of lignes) {
    const c = l.compte.replace(/\D/g, "")[0] || "?";
    classCount.set(c, (classCount.get(c) ?? 0) + 1);
  }
  const classes = [...classCount.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([classe, n]) => ({
      classe,
      n,
      label: CLASSE_LABELS[classe] ?? "Classe non reconnue",
    }));

  const { couverture, classesManquantes } = construireCouverture(classCount);
  if (classesManquantes.length && lignes.length) {
    avertissements.push(
      `Classes SYSCOHADA absentes : ${classesManquantes.join(", ")} — informationnel (secteur, extrait partiel ou export filtré).`,
    );
  }

  const avertissementSource = meta?.avertissement?.trim() || null;
  const fictif =
    !!avertissementSource?.toUpperCase().includes("FICTIF") ||
    lignes.some((l) => l.libelle.toUpperCase().includes("[FICTIF]"));

  if (fictif) {
    avertissements.unshift(
      "Jeu FICTIF détecté — montants non opposables, usage démo / calage uniquement.",
    );
  }

  const checklistStructurelle = construireChecklistStructurelle({
    nbLignes: lignes.length,
    equilibre,
    ecart,
    erreurs,
    doublons,
    fictif,
    classesManquantes,
    couverture,
  });

  return {
    ok: erreurs.length === 0 && lignes.length > 0,
    erreurs,
    avertissements,
    nbLignes: lignes.length,
    totalDebit,
    totalCredit,
    ecart,
    equilibre,
    classes,
    couverture,
    classesManquantes,
    checklistStructurelle,
    doublons,
    lignes,
    fictif,
    avertissementSource,
  };
}

function analyseErreur(erreurs: string[]): BalanceAnalyse {
  return {
    ok: false,
    erreurs,
    avertissements: [],
    ...ANALYSE_VIDE,
    fictif: false,
    avertissementSource: null,
    checklistStructurelle: construireChecklistStructurelle({
      nbLignes: 0,
      equilibre: false,
      ecart: 0,
      erreurs,
      doublons: [],
      fictif: false,
      classesManquantes: [...CLASSES_REVUE],
      couverture: ANALYSE_VIDE.couverture,
    }),
  };
}

export function analyserBalanceJson(texte: string): BalanceAnalyse {
  try {
    const data = JSON.parse(texte) as unknown;
    if (Array.isArray(data)) {
      return analyserLignes(data);
    }
    if (data && typeof data === "object") {
      const o = data as Record<string, unknown>;
      const lignes = o.lignes;
      if (!Array.isArray(lignes)) {
        return analyseErreur(['JSON : clé "lignes" (tableau) attendue']);
      }
      return analyserLignes(lignes, {
        avertissement: typeof o.avertissement === "string" ? o.avertissement : null,
      });
    }
    return analyseErreur([
      "JSON : objet { lignes: [...] } ou tableau de lignes attendu",
    ]);
  } catch (e) {
    return analyseErreur([
      `JSON invalide : ${e instanceof Error ? e.message : String(e)}`,
    ]);
  }
}

/** Parse CSV/TSV minimal (compte,libelle,debit,credit) pour aperçu local. */
export function analyserBalanceCsv(texte: string): BalanceAnalyse {
  const lines = texte.replace(/^\uFEFF/, "").trim().split(/\r?\n/);
  if (!lines.length) {
    return analyserLignes([]);
  }
  const delim = lines[0].includes("\t") ? "\t" : ",";
  const split = (row: string) => {
    // CSV simple sans guillemets imbriqués complexes
    return row.split(delim).map((c) => c.trim().replace(/^"|"$/g, ""));
  };
  let debut = 0;
  let iCompte = 0;
  let iLibelle = 1;
  let iDebit = 2;
  let iCredit = 3;
  const entete = split(lines[0]).map((c) => c.toLowerCase());
  if (entete.includes("compte")) {
    debut = 1;
    iCompte = entete.indexOf("compte");
    iLibelle = entete.indexOf("libelle");
    iDebit = entete.indexOf("debit");
    iCredit = entete.indexOf("credit");
    if (iCompte < 0 || iDebit < 0 || iCredit < 0) {
      return analyseErreur([
        "CSV : en-tête attendu compte,libelle,debit,credit",
      ]);
    }
  }
  const raw: Array<Record<string, string>> = [];
  for (const row of lines.slice(debut)) {
    if (!row.trim()) continue;
    const cols = split(row);
    raw.push({
      compte: cols[iCompte] ?? "",
      libelle: iLibelle >= 0 ? (cols[iLibelle] ?? "") : "",
      debit: cols[iDebit] ?? "0",
      credit: cols[iCredit] ?? "0",
    });
  }
  return analyserLignes(raw);
}

export type ChecklistControleurInput = {
  identiteComplet: boolean;
  identiteDetail: string;
  exercice: number;
  balancePret: boolean;
  balanceDetail: string;
  balanceFictif: boolean;
  quotaBloque: boolean;
  quotaDetail: string;
  sourceLabel: string;
};

/**
 * Checklist contrôleur avant « Lancer la revue ».
 * Points de cadrage / fiabilisation — aucun article, taux ou seuil fiscal.
 */
export function checklistControleurAvantLancement(
  input: ChecklistControleurInput,
): ChecklistItem[] {
  return [
    {
      id: "identite",
      label: "Identité légale",
      statut: input.identiteComplet ? "ok" : "warn",
      detail: input.identiteDetail,
    },
    {
      id: "exercice",
      label: "Exercice contrôlé",
      statut: Number.isFinite(input.exercice) && input.exercice >= 2000 ? "ok" : "ko",
      detail: `Exercice ${input.exercice} — le moteur appliquera le millésime en vigueur pour cette année`,
    },
    {
      id: "source",
      label: "Source comptable",
      statut: input.balancePret ? "ok" : "ko",
      detail: input.balanceDetail,
    },
    {
      id: "equilibre-source",
      label: "Fiabilisation (équilibre / format)",
      statut: input.balancePret ? "ok" : "ko",
      detail: input.balancePret
        ? `${input.sourceLabel} prête pour import serveur`
        : "Corriger avant lancement — le moteur ne calcule pas sur une source refusée",
    },
    {
      id: "quota",
      label: "Quota missions",
      statut: input.quotaBloque ? "ko" : "ok",
      detail: input.quotaDetail,
    },
    {
      id: "epinglage",
      label: "Épinglage du référentiel",
      statut: "info",
      detail:
        "À la création de la mission, la version courante du référentiel sera épinglée (résultat stable jusqu’à clôture)",
    },
    ...(input.balanceFictif
      ? [
          {
            id: "fictif-ctrl",
            label: "Données FICTIF",
            statut: "warn" as const,
            detail:
              "Montants de démonstration — restitution non opposable au contribuable",
          },
        ]
      : []),
  ];
}

export function fmtXof(n: number): string {
  return (
    n.toLocaleString("fr-FR", {
      maximumFractionDigits: 0,
      minimumFractionDigits: 0,
    }) + " XOF"
  );
}

export { CLASSE_LABELS, CLASSES_REVUE };
