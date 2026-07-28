import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Cohérence CA comptable / CA reconstitué depuis la TVA — consultatif.
 *
 * Croisement classique de la DGI offert au réviseur avant
 * l'administration : le chiffre d'affaires des comptes 70x de la
 * balance est comparé au chiffre d'affaires reconstitué depuis la TVA
 * collectée déclarée divisée par le seul taux normal de 18 %
 * (approximation assumée : exonérations, taux réduits et opérations
 * hors champ ignorés). Un écart au-delà du seuil est « à expliquer »
 * (exonérations, décalages de facturation…), jamais une conclusion —
 * lecture seule, l'humain apprécie et décide.
 */
type CoherenceCaOut = {
  mission_id: number;
  exercice: number;
  disponible: boolean;
  ca_comptable: string;
  nb_declarations: number;
  tva_collectee_totale: string;
  taux_normal: string;
  ca_reconstitue: string;
  approximation: boolean;
  ecart: string;
  ecart_relatif_pct: string | null;
  seuil_pct: string;
  statut: string;
  synthese: {
    statut: string;
    libelle_statut: string;
    nb_comptes_ca: number;
    nb_declarations: number;
  };
  note: string;
  references: { reference: string; portee: string }[];
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

const STATUT_LABELS: Record<string, string> = {
  indisponible: "Indisponible",
  coherent: "Cohérent",
  ecart_a_expliquer: "Écart à expliquer",
};

export function CoherenceCaVue({ missionId, jeton }: Props) {
  const [etat, setEtat] = useState<CoherenceCaOut | null>(null);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<CoherenceCaOut>(
        `/api/v1/missions/${missionId}/coherence-ca`,
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
      aria-label="Cohérence du chiffre d'affaires avec la TVA déclarée"
    >
      <div className="matx-head">
        <h4 className="matx-titre label-with-tip">
          Cohérence CA / TVA déclarée
          <InfoTip
            label="Croisement classique de la DGI : le CA comptable (comptes 70x de la balance) est comparé au CA reconstitué depuis la TVA collectée déclarée divisée par le seul taux normal de 18 %. Approximation assumée (exonérations, taux réduits et opérations hors champ ignorés) : un écart au-delà du seuil est « à expliquer », jamais une conclusion — vue consultative, l'humain apprécie et décide."
            ariaLabel="Aide : cohérence CA / TVA déclarée"
          />
        </h4>
        <span className="matx-synthese muted">
          {etat.disponible ? (
            etat.statut === "ecart_a_expliquer" ? (
              <strong className="matx-badge-cible">
                Écart à expliquer
                {etat.ecart_relatif_pct !== null &&
                  ` (${etat.ecart_relatif_pct} %)`}
              </strong>
            ) : (
              <>
                Cohérent
                {etat.ecart_relatif_pct !== null &&
                  ` (écart ${etat.ecart_relatif_pct} %)`}
              </>
            )
          ) : (
            "Indisponible"
          )}
        </span>
      </div>

      {!etat.disponible ? (
        <p className="empty-state">
          Croisement indisponible : importez une balance (comptes 70x)
          et saisissez au moins une déclaration de TVA pour reconstituer
          le chiffre d'affaires.
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
              <tr>
                <td className="matx-ref">
                  CA comptable (comptes 70x, {etat.synthese.nb_comptes_ca}{" "}
                  compte{etat.synthese.nb_comptes_ca > 1 ? "s" : ""})
                </td>
                <td className="matx-montant">
                  {fmtMontant(etat.ca_comptable)}
                </td>
              </tr>
              <tr>
                <td className="matx-ref">
                  TVA collectée déclarée ({etat.nb_declarations} période
                  {etat.nb_declarations > 1 ? "s" : ""})
                </td>
                <td className="matx-montant">
                  {fmtMontant(etat.tva_collectee_totale)}
                </td>
              </tr>
              <tr>
                <td className="matx-ref">
                  CA reconstitué (TVA ÷ 18 %, approximation)
                  <InfoTip
                    label="Reconstitution au seul taux normal de 18 % : les exonérations, taux réduits et opérations hors champ de TVA sont ignorés — ordre de grandeur, pas une liquidation."
                    ariaLabel="Aide : CA reconstitué"
                  />
                </td>
                <td className="matx-montant">
                  {fmtMontant(etat.ca_reconstitue)}
                </td>
              </tr>
              <tr>
                <td className="matx-ref">
                  <strong>
                    Écart (comptable − reconstitué)
                    {etat.ecart_relatif_pct !== null &&
                      ` : ${etat.ecart_relatif_pct} %`}{" "}
                    — {STATUT_LABELS[etat.statut] ?? etat.statut}
                  </strong>
                </td>
                <td className="matx-montant">
                  <strong>{fmtMontant(etat.ecart)}</strong>
                </td>
              </tr>
            </tbody>
          </table>
          <p className="muted">
            {etat.synthese.libelle_statut} — seuil indicatif{" "}
            {etat.seuil_pct} %.
          </p>
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
