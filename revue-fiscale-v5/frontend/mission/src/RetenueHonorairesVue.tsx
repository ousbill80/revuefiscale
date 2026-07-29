import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Retenue à la source sur honoraires — vue consultative (balance).
 *
 * Les rémunérations d'intermédiaires et de conseils (honoraires,
 * commissions, courtages) sont lues dans les comptes 632x de la
 * balance et la retenue théorique MAXIMALE est approchée au taux
 * courant de 7,5 % (prestataires résidents non immatriculés). Limite
 * assumée : le régime du prestataire (résident ou non, immatriculé ou
 * non, conventions) conditionne la retenue réelle et son taux et est
 * absent de la balance — la répartition n'est jamais calculée. Un
 * écart entre retenue théorique et retenue pratiquée est « à
 * expliquer », jamais une conclusion — lecture seule, seul l'humain
 * qualifie et décide.
 */
type RetenueHonorairesOut = {
  mission_id: number;
  exercice: number;
  disponible: boolean;
  honoraires_bruts: string;
  comptes_honoraires: { compte: string; libelle: string; solde: string }[];
  taux_indicatif: string;
  retenue_theorique_max: string;
  repartition_par_prestataire: { calculable: boolean; motif: string };
  statut: string;
  synthese: {
    statut: string;
    libelle_statut: string;
    nb_comptes_honoraires: number;
  };
  note: string;
  references: { reference: string; portee: string }[];
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

export function RetenueHonorairesVue({ missionId, jeton }: Props) {
  const [etat, setEtat] = useState<RetenueHonorairesOut | null>(null);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<RetenueHonorairesOut>(
        `/api/v1/missions/${missionId}/retenue-honoraires`,
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
      aria-label="Retenue à la source sur honoraires"
    >
      <div className="matx-head">
        <h4 className="matx-titre label-with-tip">
          Retenue à la source sur honoraires
          <InfoTip
            label="Les rémunérations d'intermédiaires et de conseils (comptes 632x de la balance : honoraires, commissions, courtages) sont rapprochées de la retenue à la source théorique MAXIMALE au taux courant de 7,5 % — comme si toutes les sommes étaient versées à des prestataires résidents non immatriculés soumis à la retenue. Le régime réel du prestataire (résident ou non, immatriculé ou non, conventions) n'est pas connu de la balance : vue consultative, seul l'humain qualifie les prestataires et décide."
            ariaLabel="Aide : retenue à la source sur honoraires"
          />
        </h4>
        <span className="matx-synthese muted">
          {etat.disponible ? (
            <>
              Maximum théorique indicatif — prestataires à qualifier (
              {etat.synthese.nb_comptes_honoraires} compte
              {etat.synthese.nb_comptes_honoraires > 1 ? "s" : ""} 632x)
            </>
          ) : (
            "Indisponible"
          )}
        </span>
      </div>

      {!etat.disponible ? (
        <p className="empty-state">
          Vue indisponible : importez une balance portant des
          rémunérations d'intermédiaires et de conseils (comptes 632x)
          pour approcher la retenue à la source théorique sur
          honoraires.
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
              {etat.comptes_honoraires.map((c) => (
                <tr key={c.compte}>
                  <td className="matx-ref">
                    {c.compte} —{" "}
                    {c.libelle || "Rémunérations d'intermédiaires"}
                  </td>
                  <td className="matx-montant">{fmtMontant(c.solde)}</td>
                </tr>
              ))}
              <tr>
                <td className="matx-ref">
                  <strong>Honoraires bruts (comptes 632x)</strong>
                </td>
                <td className="matx-montant">
                  <strong>{fmtMontant(etat.honoraires_bruts)}</strong>
                </td>
              </tr>
              <tr>
                <td className="matx-ref">
                  Retenue théorique maximale (7,5 %, indicatif)
                  <InfoTip
                    label="Maximum calculé comme si TOUTES les sommes étaient versées à des prestataires résidents non immatriculés soumis à la retenue de 7,5 % — le régime réel des prestataires peut la réduire jusqu'à zéro ou la majorer (non-résidents) : ordre de grandeur, pas une liquidation."
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
          {!etat.repartition_par_prestataire.calculable && (
            <p className="muted">
              {etat.repartition_par_prestataire.motif}
            </p>
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

    </section>
  );
}
