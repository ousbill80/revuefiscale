/** Options d’identité légale — données de saisie, pas des règles de calcul. */

export type FormePersonne = "pm" | "pp";

export const FORMES_PERSONNE: Array<{
  value: FormePersonne;
  label: string;
  hint: string;
}> = [
  {
    value: "pm",
    label: "Personne morale",
    hint: "Entreprise, société, association — RCCM + NCC requis.",
  },
  {
    value: "pp",
    label: "Personne physique",
    hint: "Entrepreneur individuel / particulier — fiche allégée.",
  },
];

/**
 * Formes juridiques usuelles OHADA / pratique CI (listing identité, pas exhaustivité DGI).
 *
 * Confirmé AUSCGIE 2014 (art. 6) : SNC, SCS, SARL, SA, SAS (+ GIE, SEP/SP, succursale).
 * SASU : sigle pratique AUSCGIE pour SAS à associé unique.
 * SUARL : pratique pour SARL à associé unique (AUSCGIE autorise 1 associé ; pas de sigle officiel).
 * SCOOPS / COOP-CA : Acte uniforme sociétés coopératives OHADA.
 * SCI / Association / Fondation / ONG : hors AUSCGIE commercial —
 *   droit civil / ordonnance OSC CI (associations, ONG, fondations, org. cultuelles).
 * SCP : société civile professionnelle (guide RCCM OHADA / professions libérales).
 * SCPA : usage courant Barreau CI = société civile professionnelle d’avocats.
 * SCA : non reprise par AUSCGIE 2014 (forme historique) — dossiers hérités.
 */
export const FORMES_JURIDIQUES_PM: Array<{ value: string; label: string }> = [
  { value: "SA", label: "SA — Société anonyme" },
  { value: "SARL", label: "SARL — À responsabilité limitée" },
  { value: "SAS", label: "SAS — Par actions simplifiée" },
  { value: "SASU", label: "SASU — SAS unipersonnelle" },
  { value: "SUARL", label: "SUARL — SARL unipersonnelle (pratique)" },
  { value: "SNC", label: "SNC — En nom collectif" },
  { value: "SCS", label: "SCS — En commandite simple" },
  {
    value: "SCA",
    label: "SCA — Commandite par actions (historique / hors AUSCGIE 2014)",
  },
  { value: "SEP", label: "SEP — Société en participation" },
  { value: "SCI", label: "SCI — Civile immobilière (droit civil)" },
  { value: "SCP", label: "SCP — Civile professionnelle" },
  {
    value: "SCPA",
    label: "SCPA — Civile professionnelle d’avocats (pratique CI)",
  },
  { value: "GIE", label: "GIE — Groupement d’intérêt économique" },
  { value: "SCOOPS", label: "SCOOPS — Coopérative simplifiée" },
  { value: "COOP-CA", label: "COOP-CA — Coopérative avec conseil d’administration" },
  { value: "Association", label: "Association" },
  { value: "ONG", label: "ONG — Organisation non gouvernementale" },
  { value: "Fondation", label: "Fondation" },
  { value: "Succursale", label: "Succursale / établissement" },
  { value: "Autre", label: "Autre" },
];

/**
 * Secteurs / activités — libellés métier CI pour cadrage revue.
 * Pas de nomenclature NAF française. Valeurs stables ; stockage = libellé (+ précision).
 */
export const SECTEURS_ACTIVITE: Array<{ value: string; label: string }> = [
  { value: "commerce", label: "Commerce" },
  { value: "services", label: "Services" },
  { value: "industrie", label: "Industrie / manufacture" },
  { value: "btp", label: "BTP / construction" },
  { value: "banque_assurance", label: "Banque / assurance / finance" },
  { value: "extractif", label: "Extractif / mines / hydrocarbures" },
  { value: "agriculture", label: "Agriculture / agroalimentaire" },
  { value: "professions_liberales", label: "Professions libérales" },
  { value: "ong_associatif", label: "ONG / associatif / fondation" },
  { value: "transport_logistique", label: "Transport / logistique" },
  { value: "immobilier", label: "Immobilier" },
  { value: "telecom_tic", label: "Télécoms / TIC" },
  { value: "energie", label: "Énergie / utilities" },
  { value: "sante_education", label: "Santé / éducation" },
  { value: "autre", label: "Autre / à préciser" },
];

const SEPARATEUR_ACTIVITE = " — ";

export function libelleSecteur(value: string): string {
  return SECTEURS_ACTIVITE.find((s) => s.value === value)?.label ?? value;
}

/** Décompose `activite_principale` stockée → secteur (value) + précision libre. */
export function decomposerActivite(brut: string | null | undefined): {
  secteur: string;
  precision: string;
} {
  const s = (brut ?? "").trim();
  if (!s) return { secteur: "", precision: "" };
  for (const opt of SECTEURS_ACTIVITE) {
    if (s === opt.label) return { secteur: opt.value, precision: "" };
    const prefix = `${opt.label}${SEPARATEUR_ACTIVITE}`;
    if (s.startsWith(prefix)) {
      return { secteur: opt.value, precision: s.slice(prefix.length).trim() };
    }
  }
  return { secteur: "autre", precision: s };
}

/** Compose secteur + précision → chaîne stockée dans activite_principale. */
export function composerActivite(secteur: string, precision: string): string {
  const prec = precision.trim();
  if (!secteur) return prec;
  const label = libelleSecteur(secteur);
  if (!prec) return label;
  if (secteur === "autre") return prec;
  return `${label}${SEPARATEUR_ACTIVITE}${prec}`;
}

/**
 * Libellés de régime — valeurs stockées ; pas d’article CGI inventé.
 * Sources DGI (millésimes 2025–2026) :
 * - « Le système fiscal ivoirien » : RE / RME / RSI / RNI
 * - « Impôts et taxes en Côte d’Ivoire » (éd. 2025) : IME, TEE, TCE, RME, RSI, RNI
 * - Annexe fiscale 2026 : « impôt des microentreprises », « taxe d’Etat de l’entreprenant »
 * Les seuils de CA ne sont pas figés ici (référentiel / millésime).
 */
export const REGIMES_FISCAUX: Array<{
  value: string;
  label: string;
  hint?: string;
}> = [
  {
    value: "reel",
    label: "RNI — Réel normal d’imposition",
    hint: "Régime du réel normal d’imposition (RNI) — DGI / CGI.",
  },
  {
    value: "reel_simplifie",
    label: "RSI — Réel simplifié d’imposition",
    hint: "Régime du réel simplifié d’imposition (RSI) — DGI / CGI.",
  },
  {
    value: "ime",
    label: "IME — Impôt des microentreprises (RME)",
    hint: "Régime des microentreprises (RME) ; cotisation = impôt des microentreprises (IME) — art. 71 bis CGI.",
  },
  {
    value: "tee",
    label: "TEE — Taxe d’État de l’entreprenant",
    hint: "Branche État du régime de l’entreprenant (RE) — art. 72 et s. CGI.",
  },
  {
    value: "tce",
    label: "TCE — Taxe communale de l’entreprenant",
    hint: "Branche communale du régime de l’entreprenant (RE) — distincte de la TEE.",
  },
  {
    value: "autre",
    label: "Autre / à préciser",
    hint: "Hors listing DGI usuel — préciser hors formulaire si besoin.",
  },
];

/** Alias CI / DGI / OCR → valeur select (pas de seuil inventé). */
const ALIAS_REGIME: Record<string, string> = {
  reel: "reel",
  rni: "reel",
  "reel normal": "reel",
  "regime reel": "reel",
  reel_simplifie: "reel_simplifie",
  "reel simplifie": "reel_simplifie",
  rsi: "reel_simplifie",
  simplifie: "reel_simplifie",
  ime: "ime",
  im: "ime",
  rme: "ime",
  micro: "ime",
  microentreprise: "ime",
  tee: "tee",
  tce: "tce",
  autre: "autre",
  liberatoire: "autre",
};

const ALIAS_FORME_JURIDIQUE: Record<string, string> = {
  sa: "SA",
  "s a": "SA",
  sarl: "SARL",
  sas: "SAS",
  sasu: "SASU",
  suarl: "SUARL",
  eurl: "SUARL",
  snc: "SNC",
  scs: "SCS",
  sca: "SCA",
  sep: "SEP",
  sci: "SCI",
  scp: "SCP",
  scpa: "SCPA",
  gie: "GIE",
  scoops: "SCOOPS",
  "coop ca": "COOP-CA",
  "coop-ca": "COOP-CA",
  association: "Association",
  ong: "ONG",
  fondation: "Fondation",
  succursale: "Succursale",
  autre: "Autre",
  ei: "EI",
};

function pliAlias(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[.\-/_,;:]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function variantesAlias(s: string): string[] {
  const base = pliAlias(s);
  if (!base) return [];
  const compact = base.replace(/\s+/g, "");
  return compact && compact !== base ? [base, compact] : [base];
}

/** Mappe un libellé extrait → value `REGIMES_FISCAUX`, sinon "". */
export function mapperRegimeFiscal(brut: string | null | undefined): string {
  if (brut == null || !String(brut).trim()) return "";
  const raw = String(brut).trim();
  if (REGIMES_FISCAUX.some((r) => r.value === raw)) return raw;
  for (const cle of variantesAlias(raw)) {
    if (ALIAS_REGIME[cle]) return ALIAS_REGIME[cle];
  }
  const cle = pliAlias(raw);
  if (cle.includes("micro")) return "ime";
  if (cle.includes("entreprenant") && cle.includes("communal")) return "tce";
  if (cle.includes("entreprenant")) return "tee";
  if (cle.includes("rsi") || (cle.includes("reel") && cle.includes("simplif")))
    return "reel_simplifie";
  if (cle.includes("rni") || cle.includes("reel")) return "reel";
  return "";
}

/** Mappe un libellé extrait → value `FORMES_JURIDIQUES_PM` / EI, sinon "". */
export function mapperFormeJuridique(brut: string | null | undefined): string {
  if (brut == null || !String(brut).trim()) return "";
  const raw = String(brut).trim();
  if (FORMES_JURIDIQUES_PM.some((f) => f.value === raw) || raw === "EI")
    return raw;
  const exact = FORMES_JURIDIQUES_PM.find(
    (f) => f.value.toLowerCase() === raw.toLowerCase(),
  );
  if (exact) return exact.value;
  for (const cle of variantesAlias(raw)) {
    if (ALIAS_FORME_JURIDIQUE[cle]) return ALIAS_FORME_JURIDIQUE[cle];
  }
  const cle = pliAlias(raw);
  const premier = cle.split(" ", 1)[0] ?? "";
  if (ALIAS_FORME_JURIDIQUE[premier]) return ALIAS_FORME_JURIDIQUE[premier];
  return "";
}

/** Mois de clôture d’exercice (1–12). Année civile = décembre. */
export const MOIS_CLOTURE: Array<{ value: string; label: string }> = [
  { value: "1", label: "Janvier" },
  { value: "2", label: "Février" },
  { value: "3", label: "Mars" },
  { value: "4", label: "Avril" },
  { value: "5", label: "Mai" },
  { value: "6", label: "Juin" },
  { value: "7", label: "Juillet" },
  { value: "8", label: "Août" },
  { value: "9", label: "Septembre" },
  { value: "10", label: "Octobre" },
  { value: "11", label: "Novembre" },
  { value: "12", label: "Décembre (année civile)" },
];

export type IdentiteLegale = {
  denomination: string;
  ncc: string;
  forme: FormePersonne;
  rccm: string;
  dfe: string;
  regime_fiscal: string;
  forme_juridique: string;
  siege_social: string;
  commune: string;
  centre_impots: string;
  /** Montant capital social (chaîne saisie UI) — PM. */
  capital_social: string;
  /** Mois 1–12 en chaîne. */
  mois_cloture: string;
  activite_principale: string;
  /** ISO YYYY-MM-DD ou vide. */
  date_immatriculation: string;
};

export function completudeIdentite(id: IdentiteLegale): {
  ok: number;
  total: number;
  pct: number;
  manquants: string[];
  clesManquantes: Array<keyof IdentiteLegale>;
  complet: boolean;
} {
  const cases: Array<[keyof IdentiteLegale, string]> =
    id.forme === "pm"
      ? [
          ["denomination", "Dénomination"],
          ["ncc", "NCC"],
          ["rccm", "RCCM"],
          ["forme_juridique", "Forme juridique"],
          ["regime_fiscal", "Régime fiscal"],
          ["capital_social", "Capital social"],
          ["mois_cloture", "Clôture d’exercice"],
          ["activite_principale", "Secteur / activité"],
          ["commune", "Commune / ville"],
          ["siege_social", "Adresse du siège"],
          ["centre_impots", "Centre des impôts"],
        ]
      : [
          ["denomination", "Nom / dénomination"],
          ["ncc", "NCC"],
          ["regime_fiscal", "Régime fiscal"],
          ["mois_cloture", "Clôture d’exercice"],
          ["activite_principale", "Secteur / activité"],
          ["commune", "Commune / ville"],
          ["centre_impots", "Centre des impôts"],
        ];
  const manquants: string[] = [];
  const clesManquantes: Array<keyof IdentiteLegale> = [];
  let ok = 0;
  for (const [cle, lib] of cases) {
    const v = id[cle];
    if (String(v ?? "").trim()) ok += 1;
    else {
      manquants.push(lib);
      clesManquantes.push(cle);
    }
  }
  const total = cases.length;
  return {
    ok,
    total,
    pct: total ? Math.round((100 * ok) / total) : 0,
    manquants,
    clesManquantes,
    complet: ok === total,
  };
}

/**
 * Minimum exigé par l’API à la création (strict) — distinct de la jauge UI.
 * Permet d’enregistrer puis compléter les champs absents des pièces.
 */
export function identiteApiMinimale(id: IdentiteLegale): {
  ok: boolean;
  manquants: string[];
} {
  const manquants: string[] = [];
  if (!id.denomination.trim()) manquants.push("Dénomination");
  if (!id.ncc.trim()) manquants.push("NCC");
  if (!id.regime_fiscal.trim()) manquants.push("Régime fiscal");
  if (!id.mois_cloture.trim()) manquants.push("Clôture d’exercice");
  if (id.forme === "pm") {
    if (!id.rccm.trim()) manquants.push("RCCM");
    if (!id.forme_juridique.trim()) manquants.push("Forme juridique");
  }
  return { ok: manquants.length === 0, manquants };
}

/** Abidjan / CI — affichage date+heure traçabilité. */
export function formaterCreationTrace(
  iso: string | null | undefined,
): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const date = d.toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "Africa/Abidjan",
  });
  const heure = d.toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Africa/Abidjan",
  });
  return `le ${date} à ${heure}`;
}

export function libelleMoisCloture(mois: string | number | null | undefined): string {
  if (mois === null || mois === undefined || mois === "") return "—";
  const v = String(mois);
  return MOIS_CLOTURE.find((m) => m.value === v)?.label ?? `Mois ${v}`;
}

/**
 * Formats indicatifs CI — avertissements doux UI uniquement, non bloquants.
 * Le backend (contribuable_identite.py) n'impose aucun format NCC/RCCM :
 * il vérifie seulement la présence. Ces regex signalent une saisie atypique.
 */
/** NCC pratique CI : 7 chiffres + 1 lettre majuscule (ex. 1234567A). */
export const NCC_FORMAT_CI = /^\d{7}[A-Z]$/;
/**
 * RCCM OHADA : CI-<greffe>-<code>-<année>-<lettre+chiffres>-<n° d'ordre>
 * (ex. CI-ABJ-03-2023-B16-00003). Tolère l'ancien format sans code
 * (ex. CI-ABJ-2010-B-12345).
 */
export const RCCM_FORMAT_OHADA =
  /^CI-[A-Z]{2,5}-(?:\d{2}-)?\d{4}-[A-Z]\d{0,2}-\d{3,6}$/;

/** Avertissement non bloquant si le NCC saisi s'écarte du format CI usuel. */
export function avertissementFormatNcc(brut: string): string | null {
  const v = brut.trim().toUpperCase();
  if (!v) return null;
  if (NCC_FORMAT_CI.test(v)) return null;
  return "Format NCC inhabituel — attendu : 7 chiffres + 1 lettre (ex. 1234567A). Vérifiez la DFE.";
}

/** Avertissement non bloquant si le RCCM s'écarte du format OHADA usuel. */
export function avertissementFormatRccm(brut: string): string | null {
  const v = brut.trim().toUpperCase().replace(/\s+/g, "");
  if (!v) return null;
  if (RCCM_FORMAT_OHADA.test(v)) return null;
  return "Format RCCM inhabituel — attendu type OHADA : CI-ABJ-03-2023-B16-00003.";
}
