import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Retenue à la source sur loyers — vue consultative depuis la balance.
 *
 * Les charges locatives sont lues dans les comptes 622x de la balance
 * et la retenue théorique MAXIMALE est approchée au taux courant de
 * 15 % (loyers versés à des bailleurs personnes physiques). Limite
 * assumée : la qualité du bailleur (personne physique ou morale,
 * régime) conditionne la retenue réelle et est absente de la balance —
 * la répartition n'est jamais calculée. Un écart entre retenue
 * théorique et retenue pratiquée est « à expliquer », jamais une
 * conclusion — lecture seule, seul l'humain qualifie et décide.
 */
type RetenueLoyersOut = {
  mission_id: number;
  exercice: number;
  disponible: boolean;
  loyers_bruts: string;
  comptes_loyers: { compte: string; libelle: string; solde: string }[];
  taux_indicatif: string;
  retenue_theorique_max: string;
  repartition_par_bailleur: { calculable: boolean; motif: string };
  statut: string;
  synthese: {
    statut: string;
    libelle_statut: string;
    nb_comptes_loyers: number;
  };
  note: string;
  references: { reference: string; portee: string }[];
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

export function RetenueLoyersVue({ missionId, jeton }: Props) {
  const [etat, setEtat] = useState<RetenueLoyersOut | null>(null);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<RetenueLoyersOut>(
        `/api/v1/missions/${missionId}/retenue-loyers`,
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
      aria-label="Retenue à la source sur loyers"
    >
      <div className="matx-head">
        <h4 className="matx-titre label-with-tip">
          Retenue à la source sur loyers
          <InfoTip
            label="Les charges locatives (comptes 622x de la balance) sont rapprochées de la retenue à la source théorique MAXIMALE au taux courant de 15 % — comme si tous les loyers étaient versés à des bailleurs personnes physiques soumis à la retenue. La qualité réelle du bailleur (personne physique ou morale, régime, exonérations) n'est pas connue de la balance : vue consultative, seul l'humain qualifie les bailleurs et décide."
            ariaLabel="Aide : retenue à la source sur loyers"
          />
        </h4>
        <span className="matx-synthese muted">
          {etat.disponible ? (
            <>
              Maximum théorique indicatif — bailleurs à qualifier (
              {etat.synthese.nb_comptes_loyers} compte
              {etat.synthese.nb_comptes_loyers > 1 ? "s" : ""} 622x)
            </>
          ) : (
            "Indisponible"
          )}
        </span>
      </div>

      {!etat.disponible ? (
        <p className="empty-state">
          Vue indisponible : importez une balance portant des charges
          locatives (comptes 622x) pour approcher la retenue à la source
          théorique sur loyers.
        </p>
      ) : (
        <>
          <table className="matx-table">
            <thead>
              <tr>
                <th scope="col">Élément</th>
                <th scope="col">Montant (FCFA)</th>
              </tr>
            </thead>
            <tbody>
              {etat.comptes_loyers.map((c) => (
                <tr key={c.compte}>
                  <td className="matx-ref">
                    {c.compte} — {c.libelle || "Charges locatives"}
                  </td>
                  <td className="matx-montant">{fmtMontant(c.solde)}</td>
                </tr>
              ))}
              <tr>
                <td className="matx-ref">
                  <strong>Loyers bruts (comptes 622x)</strong>
                </td>
                <td className="matx-montant">
                  <strong>{fmtMontant(etat.loyers_bruts)}</strong>
                </td>
              </tr>
              <tr>
                <td className="matx-ref">
                  Retenue théorique maximale (15 %, indicatif)
                  <InfoTip
                    label="Maximum calculé comme si TOUS les loyers étaient versés à des bailleurs personnes physiques soumis à la retenue de 15 % — la qualité réelle des bailleurs peut la réduire jusqu'à zéro : ordre de grandeur, pas une liquidation."
                    ariaLabel="Aide : retenue théorique maximale"
                  />
                </td>
                <td className="matx-montant">
                  {fmtMontant(etat.retenue_theorique_max)}
                </td>
              </tr>
            </tbody>
          </table>
          <p className="muted">{etat.synthese.libelle_statut}.</p>
          {!etat.repartition_par_bailleur.calculable && (
            <p className="muted">{etat.repartition_par_bailleur.motif}</p>
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
