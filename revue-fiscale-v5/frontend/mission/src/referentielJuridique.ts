/** Référentiel juridique interne — fiches synthétiques pour tooltips.
 * Contenu indicatif : toujours vérifier la version en vigueur du texte.
 */

export type FicheJuridique = {
  reference: string;
  intitule: string;
  resume: string;
  interpretation: string;
};

export const REFERENTIEL_JURIDIQUE: Record<string, FicheJuridique> = {
  "L171 LPF": {
    reference: "Art. L171 et s. du Livre de procédures fiscales (CI)",
    intitule: "Délai de reprise de l’administration fiscale (prescription)",
    resume:
      "L’administration fiscale ivoirienne dispose d’un délai de reprise de " +
      "trois ans pour réparer les omissions, insuffisances ou erreurs " +
      "d’imposition : les exercices antérieurs à N-3 sont en principe " +
      "prescrits. La notification d’un redressement interrompt la " +
      "prescription et ouvre un nouveau délai.",
    interpretation:
      "En revue fiscale, distinguer les risques portant sur des exercices " +
      "encore repris (N-3 à N) de ceux couverts par la prescription. Un " +
      "risque sur exercice ≤ N-3 peut souvent être requalifié « prescrit », " +
      "sauf interruption (notification de redressement, procédure en cours) " +
      "ou cas particuliers allongeant le délai.",
  },
  "18 CGI": {
    reference: "Art. 18 du Code général des impôts (CI)",
    intitule: "Charges déductibles du résultat imposable (BIC/IS)",
    resume:
      "Conditions générales de déductibilité des charges : engagées dans " +
      "l’intérêt de l’entreprise, régulièrement comptabilisées, appuyées de " +
      "justificatifs et se traduisant par une diminution de l’actif net. " +
      "L’article encadre aussi des charges spécifiques (rémunérations, " +
      "loyers, assurances, intérêts de comptes courants d’associés…) avec " +
      "des plafonds propres.",
    interpretation:
      "Pour chaque charge significative, vérifier la réalité de la " +
      "prestation, la pièce justificative et le respect des limites " +
      "spécifiques (personnel expatrié, comptes courants, dons…). Une charge " +
      "non conforme est réintégrable au résultat imposable.",
  },
  "108 CGI": {
    reference: "Art. 108 du Code général des impôts (CI)",
    intitule: "Retenue à la source sur honoraires et rémunérations non commerciales",
    resume:
      "Les sommes versées à des prestataires relevant des bénéfices non " +
      "commerciaux (honoraires, commissions, vacations…) supportent une " +
      "retenue à la source opérée par la partie versante, à reverser à " +
      "l’administration fiscale.",
    interpretation:
      "Rapprocher les comptes d’honoraires et de prestataires des " +
      "déclarations de retenues : toute rémunération versée sans retenue " +
      "expose l’entreprise au rappel de la retenue, majoré des pénalités. " +
      "Vérifier aussi l’état récapitulatif annuel des honoraires.",
  },
  "134 CGI": {
    reference: "Art. 134 et s. du Code général des impôts (CI)",
    intitule: "Impôts sur traitements et salaires — contribution employeur",
    resume:
      "Les traitements, salaires et avantages en nature supportent des " +
      "impôts retenus à la source (ITS) et des contributions à la charge de " +
      "l’employeur, assis sur la masse salariale, avec des règles propres au " +
      "personnel local et expatrié.",
    interpretation:
      "Rapprocher la masse salariale comptable (comptes 66) des bases " +
      "déclarées sur les états de salaires : les écarts (avantages en " +
      "nature non déclarés, personnel expatrié) sont une source fréquente " +
      "de rappels d’ITS et de contribution employeur.",
  },
  "171 CGI": {
    reference: "Art. 171 du Code général des impôts (CI)",
    intitule: "Acompte d’impôt sur les revenus locatifs (retenue sur loyers)",
    resume:
      "Les loyers d’immeubles pris à bail par des entreprises donnent lieu " +
      "à un prélèvement opéré par le locataire sur les loyers versés, à " +
      "titre d’acompte sur l’impôt foncier / revenus locatifs du bailleur.",
    interpretation:
      "Vérifier que l’entreprise locataire a bien opéré et reversé la " +
      "retenue sur ses loyers (compte 622 / charges locatives). L’absence " +
      "de retenue expose le locataire au paiement de l’acompte en ses lieu " +
      "et place, avec pénalités.",
  },
  "272 CGI": {
    reference: "Art. 272 et s. du Code général des impôts (CI)",
    intitule: "Contribution des patentes",
    resume:
      "Toute personne exerçant en Côte d’Ivoire un commerce, une industrie " +
      "ou une profession non expressément exonérée est assujettie à la " +
      "contribution des patentes, composée d’un droit sur le chiffre " +
      "d’affaires et d’un droit sur la valeur locative des locaux " +
      "professionnels.",
    interpretation:
      "Contrôler la cohérence entre le chiffre d’affaires déclaré à la " +
      "patente et celui des états financiers, ainsi que l’exhaustivité des " +
      "établissements et valeurs locatives déclarés. Les écarts génèrent " +
      "des rappels de droits.",
  },
  "338 CGI": {
    reference: "Art. 338 du Code général des impôts (CI)",
    intitule: "Réévaluation des immobilisations",
    resume:
      "Encadre le traitement fiscal des opérations de réévaluation des " +
      "bilans : constatation de l’écart de réévaluation et régime fiscal " +
      "des amortissements et plus-values calculés sur les valeurs " +
      "réévaluées.",
    interpretation:
      "En présence d’un écart de réévaluation au bilan, vérifier que le " +
      "régime appliqué (imposition ou sursis de l’écart, amortissements sur " +
      "valeurs réévaluées) est conforme au dispositif en vigueur et " +
      "correctement documenté.",
  },
  "339 CGI": {
    reference: "Art. 339 du Code général des impôts (CI)",
    intitule: "Organismes sans but lucratif — régime fiscal",
    resume:
      "Définit le traitement fiscal des associations et organismes sans but " +
      "lucratif : exonération liée à la gestion désintéressée et au " +
      "caractère non lucratif de l’activité, avec imposition des activités " +
      "lucratives accessoires.",
    interpretation:
      "Pour un OBNL, vérifier que les conditions de non-lucrativité sont " +
      "réunies (gestion désintéressée, absence de distribution). Des " +
      "activités commerciales significatives peuvent faire basculer tout ou " +
      "partie des résultats dans le champ de l’impôt.",
  },
};

/** Recherche tolérante : clé exacte, puis sans subdivision (« 18 A CGI » → « 18 CGI »). */
export function chercherFiche(cle: string): FicheJuridique | null {
  const exacte = REFERENTIEL_JURIDIQUE[cle];
  if (exacte) return exacte;
  const morceaux = cle.split(" ");
  if (morceaux.length > 2) {
    const reduite = `${morceaux[0]} ${morceaux[morceaux.length - 1]}`;
    if (REFERENTIEL_JURIDIQUE[reduite]) return REFERENTIEL_JURIDIQUE[reduite];
  }
  return null;
}

export const MENTION_PRUDENCE = "Vérifier la version en vigueur du texte.";
