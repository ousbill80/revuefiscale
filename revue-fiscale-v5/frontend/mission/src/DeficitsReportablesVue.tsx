import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Suivi pluriannuel des déficits reportables — vue consultative.
 *
 * Pour le client de la mission, le résultat fiscal THÉORIQUE de
 * chaque exercice revu est repris du tableau de passage (aucun
 * recalcul) : déficits constatés et cumul INDICATIF à imputation
 * théorique maximale. Approximation assumée : les imputations
 * réellement pratiquées dans les liasses déposées ne sont pas
 * connues de l'outil — seules les liasses font foi. Le délai de
 * report n'est jamais chiffré (CGI applicable à vérifier). Lecture
 * seule, l'humain rapproche et décide.
 */
type LigneExercice = {
  exercice: number;
  mission_id: number | null;
  disponible: boolean;
  resultat_fiscal_theorique: string | null;
  deficit_constate: string;
  imputation_theorique: string;
  cumul_indicatif_deficits: string;
  statut: string;
  libelle_statut: string;
};

type DeficitsReportablesOut = {
  mission_id: number;
  exercice: number;
  disponible: boolean;
  exercices: LigneExercice[];
  cumul_indicatif_final: string;
  approximation: boolean;
  regle_report: { principe: string; delai_chiffre: boolean };
  imputation_reelle: { calculable: boolean; motif: string };
  statut: string;
  synthese: {
    statut: string;
    libelle_statut: string;
    nb_exercices: number;
    nb_exercices_chiffrables: number;
    nb_deficits_constates: number;
  };
  note: string;
  references: { reference: string; portee: string }[];
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

export function DeficitsReportablesVue({ missionId, jeton }: Props) {
  const [etat, setEtat] = useState<DeficitsReportablesOut | null>(null);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<DeficitsReportablesOut>(
        `/api/v1/missions/${missionId}/deficits-reportables`,
        { jeton },
      );
      setEtat(out ?? null);
    } catch {
      setEtat(null);
    }
  }, [jeton, missionId]);

  useEffect(() => {
    void charger();
  }, [charger]);

  if (!etat) return null;
  return (
    <section
      className="matx panel dense"
      aria-label="Suivi pluriannuel des déficits reportables"
    >
      <div className="matx-head">
        <h4 className="matx-titre label-with-tip">
          Déficits reportables (suivi pluriannuel)
          <InfoTip
            label="Le résultat fiscal THÉORIQUE de chaque exercice revu du client est repris du tableau de passage (aucun recalcul) et les déficits constatés sont cumulés à imputation théorique maximale. Approximation assumée : les imputations réellement pratiquées dans les liasses déposées ne sont pas connues — seules les liasses font foi. Le délai et les plafonds de report dépendent du CGI applicable : vue consultative, l'humain rapproche et décide."
            ariaLabel="Aide : suivi pluriannuel des déficits reportables"
          />
        </h4>
        <span className="matx-synthese muted">
          {etat.disponible ? (
            <>
              {etat.synthese.nb_deficits_constates > 0
                ? "Déficits à suivre"
                : "Aucun déficit constaté"}{" "}
              ({etat.synthese.nb_exercices_chiffrables} exercice
              {etat.synthese.nb_exercices_chiffrables > 1 ? "s" : ""}{" "}
              chiffrable
              {etat.synthese.nb_exercices_chiffrables > 1 ? "s" : ""})
            </>
          ) : (
            "Indisponible"
          )}
        </span>
      </div>

      {!etat.disponible ? (
        <p className="empty-state">
          Suivi indisponible : aucun exercice du client ne porte de
          résultat fiscal théorique chiffrable — importez les balances
          des missions du client pour suivre les déficits reportables.
        </p>
      ) : (
        <>
          <table className="matx-table">
            <thead>
              <tr>
                <th scope="col">Exercice</th>
                <th scope="col">Résultat fiscal théorique (FCFA)</th>
                <th scope="col">Déficit constaté (FCFA)</th>
                <th scope="col">
                  Imputation théorique (FCFA)
                  <InfoTip
                    label="Imputation théorique MAXIMALE du cumul des déficits antérieurs sur le bénéfice de l'exercice, plafonnée au bénéfice — approximation : l'imputation réellement pratiquée dans la liasse peut différer."
                    ariaLabel="Aide : imputation théorique"
                  />
                </th>
                <th scope="col">
                  Cumul indicatif (FCFA)
                  <InfoTip
                    label="Cumul indicatif des déficits antérieurs non encore imputés après l'exercice — ordre de grandeur à rapprocher des liasses déposées, jamais un solde opposable."
                    ariaLabel="Aide : cumul indicatif des déficits"
                  />
                </th>
              </tr>
            </thead>
            <tbody>
              {etat.exercices.map((l) => (
                <tr key={l.exercice}>
                  <td className="matx-ref">{l.exercice}</td>
                  <td className="matx-montant">
                    {l.disponible && l.resultat_fiscal_theorique != null
                      ? fmtMontant(l.resultat_fiscal_theorique)
                      : "Indisponible"}
                  </td>
                  <td className="matx-montant">
                    {l.disponible ? fmtMontant(l.deficit_constate) : "—"}
                  </td>
                  <td className="matx-montant">
                    {l.disponible
                      ? fmtMontant(l.imputation_theorique)
                      : "—"}
                  </td>
                  <td className="matx-montant">
                    {fmtMontant(l.cumul_indicatif_deficits)}
                  </td>
                </tr>
              ))}
              <tr>
                <td className="matx-ref" colSpan={4}>
                  <strong>
                    Cumul indicatif final des déficits non imputés
                  </strong>
                </td>
                <td className="matx-montant">
                  <strong>{fmtMontant(etat.cumul_indicatif_final)}</strong>
                </td>
              </tr>
            </tbody>
          </table>
          <p className="muted">{etat.synthese.libelle_statut}.</p>
          <p className="muted">{etat.regle_report.principe}</p>
          {!etat.imputation_reelle.calculable && (
            <p className="muted">{etat.imputation_reelle.motif}</p>
          )}
        </>
      )}

      <details className="matx-detail">
        <summary>Références ({etat.references.length})</summary>
        <ul>
          {etat.references.map((r) => (
            <li key={r.reference}>
              <strong>{r.reference}</strong> — {r.portee}
            </li>
          ))}
        </ul>
      </details>

      <p className="matx-note muted">{etat.note}</p>
    </section>
  );
}
