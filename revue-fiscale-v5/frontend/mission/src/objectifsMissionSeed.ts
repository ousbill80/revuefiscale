/**
 * Modèles d'objectifs de lettre de mission — libellés narratifs cabinet,
 * hors moteur fiscal. Complétés par l'historique du portefeuille (API).
 */
export const OBJECTIFS_MISSION_SEED: readonly string[] = [
  "Identifier et chiffrer les principaux risques fiscaux sur l'exercice",
  "Sécuriser la position fiscale avant tout contrôle de l'administration",
  "Vérifier la cohérence des déclarations avec la comptabilité",
  "Quantifier les expositions potentielles (IS, TVA, retenues à la source)",
  "Établir un plan de régularisation des anomalies identifiées",
  "Contrôler la déductibilité des charges significatives",
  "Rapprocher les soldes fiscaux et les paiements effectués",
  "Analyser le respect des obligations déclaratives périodiques",
  "Documenter les points nécessitant une décision du client",
  "Appuyer le commissariat aux comptes sur le volet fiscal",
  "Évaluer le passif fiscal latent dans le cadre d'une due diligence",
  "Préparer la réponse aux observations notifiées par l'administration",
  "Revue ciblée TVA — cohérence déclarations et comptabilité",
  "Revue ciblée retenues à la source — honoraires et loyers",
  "Contrôle de la cohérence du résultat fiscal avec les comptes annuels",
  "Cartographier les positions nécessitant une confirmation écrite du client",
] as const;

export type ObjectifSuggestionSource = "modele" | "cabinet";

export type ObjectifSuggestion = {
  libelle: string;
  source: ObjectifSuggestionSource;
  usage?: number;
};

function normaliseLibelle(s: string): string {
  return s.trim().toLowerCase();
}

/** Filtre le seed local selon la saisie. */
export function filtrerObjectifsSeed(q: string, limit = 8): string[] {
  const nq = normaliseLibelle(q);
  const pool = nq
    ? OBJECTIFS_MISSION_SEED.filter((s) => normaliseLibelle(s).includes(nq))
    : [...OBJECTIFS_MISSION_SEED];
  return pool.slice(0, limit);
}

/** Fusionne modèles + historique cabinet, sans doublons ni objectifs déjà posés. */
export function fusionnerSuggestionsObjectifs(
  opts: {
    q: string;
    cabinet: Array<{ libelle: string; usage?: number }>;
    dejaUtilises: readonly string[];
    limit?: number;
  },
): ObjectifSuggestion[] {
  const limit = opts.limit ?? 8;
  const utilises = new Set(opts.dejaUtilises.map(normaliseLibelle));
  const vus = new Set<string>();
  const out: ObjectifSuggestion[] = [];

  const pousser = (libelle: string, source: ObjectifSuggestionSource, usage?: number) => {
    const cle = normaliseLibelle(libelle);
    if (!cle || utilises.has(cle) || vus.has(cle)) return;
    vus.add(cle);
    out.push({ libelle: libelle.trim(), source, usage });
  };

  for (const row of opts.cabinet) {
    if (out.length >= limit) break;
    pousser(row.libelle, "cabinet", row.usage);
  }

  for (const lib of filtrerObjectifsSeed(opts.q, limit * 2)) {
    if (out.length >= limit) break;
    pousser(lib, "modele");
  }

  return out.slice(0, limit);
}
