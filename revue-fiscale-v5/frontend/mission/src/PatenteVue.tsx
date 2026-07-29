import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Estimation consultative de la contribution des patentes.
 *
 * Approche le droit sur le chiffre d'affaires (CGI, art. 274) à
 * 0,5 % du CA lu dans les comptes 70x de la balance, borné par le
 * plancher de 300 000 FCFA et un plafond indicatif. Le droit sur la
 * valeur locative (CGI, art. 275 et s.) n'est pas calculable depuis
 * la balance et n'est jamais estimé : l'estimation totale est
 * partielle — lecture seule, l'humain décide.
 */
type CompteCA = {
  compte: string;
  libelle: string;
  solde: string;
};

type ReferencePatente = {
  reference: string;
  portee: string;
};

type PatenteOut = {
  mission_id: number;
  exercice: number;
  disponible: boolean;
  chiffre_affaires: string;
  comptes_ca: CompteCA[];
  taux: string;
  droit_chiffre_affaires: string;
  plancher_applique: boolean;
  plafond_applique: boolean;
  plancher_fcfa: string;
  plafond_indicatif_fcfa: string;
  droit_valeur_locative: {
    calculable: boolean;
    motif: string;
  };
  estimation_totale_partielle: string;
  synthese: {
    statut: string;
    libelle_statut: string;
    nb_comptes_ca: number;
    plancher_applique: boolean;
    plafond_applique: boolean;
  };
  note: string;
  references: ReferencePatente[];
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

export function PatenteVue({ missionId, jeton }: Props) {
  const [etat, setEtat] = useState<PatenteOut | null>(null);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<PatenteOut>(
        `/api/v1/missions/${missionId}/patente`,
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
  const s = etat.synthese;
  return (
    <section
      className="matx panel dense"
      aria-label="Estimation de la contribution des patentes"
    >
      <div className="matx-head">
        <h4 className="matx-titre label-with-tip">
          Contribution des patentes (estimation)
          <InfoTip
            label="Estimation consultative de la patente (CGI, art. 264 et s.) : droit sur le chiffre d'affaires approché à 0,5 % du CA des comptes 70x de la balance, borné par le plancher de 300 000 FCFA et un plafond indicatif. Le droit sur la valeur locative n'est pas calculable depuis la balance : l'estimation est partielle — l'humain décide."
            ariaLabel="Aide : estimation de la contribution des patentes"
          />
        </h4>
        <span className="matx-synthese muted">
          {etat.disponible ? (
            <>
              {s.nb_comptes_ca} compte{s.nb_comptes_ca > 1 ? "s" : ""}{" "}
              70x ·{" "}
              <strong className="matx-badge-cible">
                {fmtMontant(etat.estimation_totale_partielle)} FCFA
                (partiel)
              </strong>
            </>
          ) : (
            s.libelle_statut
          )}
        </span>
      </div>

      {!etat.disponible ? (
        <p className="empty-state">
          Estimation indisponible : importez une balance portant des
          comptes de chiffre d'affaires (70x).
        </p>
      ) : (
        <>
          <table className="matx-table">
            <thead>
              <tr>
                <th scope="col">Élément</th>
                <th scope="col">Montant (FCFA)</th>
                <th scope="col">Précision</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="matx-ref">
                  Chiffre d'affaires (comptes 70x)
                </td>
                <td className="matx-montant">
                  {fmtMontant(etat.chiffre_affaires)}
                </td>
                <td className="muted">
                  {s.nb_comptes_ca} compte
                  {s.nb_comptes_ca > 1 ? "s" : ""} de la balance
                </td>
              </tr>
              <tr>
                <td className="matx-ref">
                  Droit sur le chiffre d'affaires (0,5 %)
                </td>
                <td className="matx-montant">
                  {fmtMontant(etat.droit_chiffre_affaires)}
                </td>
                <td className="muted">
                  {etat.plancher_applique
                    ? `Plancher de ${fmtMontant(etat.plancher_fcfa)} FCFA appliqué`
                    : etat.plafond_applique
                      ? `Plafond indicatif de ${fmtMontant(etat.plafond_indicatif_fcfa)} FCFA appliqué`
                      : "Taux général, entre plancher et plafond"}
                </td>
              </tr>
              <tr>
                <td className="matx-ref">
                  Droit sur la valeur locative
                </td>
                <td className="matx-montant">—</td>
                <td className="muted">
                  Non calculable depuis la balance
                  <InfoTip
                    label={etat.droit_valeur_locative.motif}
                    ariaLabel="Aide : droit sur la valeur locative non calculable"
                  />
                </td>
              </tr>
              <tr>
                <td className="matx-ref">
                  <strong>Estimation totale (partielle)</strong>
                </td>
                <td className="matx-montant">
                  <strong>
                    {fmtMontant(etat.estimation_totale_partielle)}
                  </strong>
                </td>
                <td className="muted">
                  Droit sur le CA seul — la valeur locative reste à
                  apprécier
                </td>
              </tr>
            </tbody>
          </table>

          <details className="matx-detail">
            <summary>
              Comptes 70x retenus ({etat.comptes_ca.length}) et
              références CGI
            </summary>
            <table className="matx-table">
              <thead>
                <tr>
                  <th scope="col">Compte</th>
                  <th scope="col">Libellé</th>
                  <th scope="col">Solde (FCFA)</th>
                </tr>
              </thead>
              <tbody>
                {etat.comptes_ca.map((c) => (
                  <tr key={c.compte}>
                    <td>{c.compte}</td>
                    <td>{c.libelle}</td>
                    <td className="matx-montant">
                      {fmtMontant(c.solde)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul>
              {etat.references.map((r) => (
                <li key={r.reference} className="muted">
                  <strong>{r.reference}</strong> — {r.portee}
                </li>
              ))}
            </ul>
          </details>
        </>
      )}

    </section>
  );
}
