import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Rapprochement acomptes IS versés / IS théorique — vue consultative.
 *
 * L'IS THÉORIQUE du tableau de passage (aucun recalcul) est rapproché
 * du total des acomptes SAISIS dans l'outil pour l'exercice : solde
 * indicatif de liquidation (reste à payer ou crédit d'impôt indicatif
 * / excédent à faire valoir). Approximation assumée : l'outil ne
 * connaît que les acomptes saisis — les quittances font foi. Le
 * minimum de perception n'est jamais calculé. Lecture seule, l'humain
 * liquide et décide.
 */
type LigneAcompte = {
  id: number | null;
  nature: string;
  libelle_nature: string;
  date_versement: string;
  montant: string;
  reference_quittance: string | null;
};

type RapprochementAcomptesOut = {
  mission_id: number;
  exercice: number;
  disponible: boolean;
  is_theorique: string | null;
  is_source: string;
  acomptes: LigneAcompte[];
  totaux_saisis: Record<string, string>;
  solde_indicatif: {
    statut: string;
    libelle: string;
    montant: string;
    solde_signe: string;
  };
  approximation: boolean;
  minimum_perception: {
    calculable: boolean;
    motif: string;
    imf_possible_signale: boolean;
  };
  statut: string;
  synthese: {
    statut: string;
    libelle_statut: string;
    nb_versements: number;
    total_acomptes_saisis: string;
  };
  note: string;
  references: { reference: string; portee: string }[];
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

export function RapprochementAcomptesVue({ missionId, jeton }: Props) {
  const [etat, setEtat] = useState<RapprochementAcomptesOut | null>(null);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<RapprochementAcomptesOut>(
        `/api/v1/missions/${missionId}/rapprochement-acomptes`,
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
      aria-label="Rapprochement acomptes IS versés / IS théorique"
    >
      <div className="matx-head">
        <h4 className="matx-titre label-with-tip">
          Rapprochement acomptes / IS théorique
          <InfoTip
            label="L'IS THÉORIQUE du tableau de passage (aucun recalcul) est rapproché du total des acomptes SAISIS dans l'outil pour l'exercice : le solde indicatif de liquidation (reste à payer ou crédit d'impôt indicatif / excédent à faire valoir) est un ordre de grandeur. Approximation assumée : l'outil ne connaît que les acomptes saisis — les quittances font foi. Le minimum de perception n'est pas calculé : vue consultative, l'humain liquide et décide."
            ariaLabel="Aide : rapprochement acomptes / IS théorique"
          />
        </h4>
        <span className="matx-synthese muted">
          {etat.disponible ? etat.synthese.libelle_statut : "Indisponible"}
        </span>
      </div>

      {!etat.disponible ? (
        <p className="empty-state">
          Rapprochement indisponible : l'IS théorique du tableau de
          passage ne se chiffre pas — importez la balance (classes 6 et
          7) pour projeter le solde indicatif de liquidation. Les
          acomptes saisis restent conservés.
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
                  IS théorique de l'exercice (tableau de passage)
                  <InfoTip
                    label="IS théorique au taux normal repris du tableau de passage — aucun recalcul ici. Le minimum de perception (IMF) n'est pas calculé par l'outil."
                    ariaLabel="Aide : IS théorique repris"
                  />
                </td>
                <td className="matx-montant">
                  {etat.is_theorique != null
                    ? fmtMontant(etat.is_theorique)
                    : "Indisponible"}
                </td>
              </tr>
              <tr>
                <td className="matx-ref">
                  Acomptes saisis dans l'outil ({etat.synthese.nb_versements}{" "}
                  versement{etat.synthese.nb_versements > 1 ? "s" : ""})
                  <InfoTip
                    label="Total des acomptes IS, retenues à la source et crédits reportés SAISIS depuis les quittances du client — les quittances font foi des versements réellement effectués."
                    ariaLabel="Aide : acomptes saisis"
                  />
                </td>
                <td className="matx-montant">
                  {fmtMontant(etat.synthese.total_acomptes_saisis)}
                </td>
              </tr>
              <tr>
                <td className="matx-ref">
                  <strong>
                    {etat.statut === "excedent_indicatif"
                      ? "Crédit d'impôt indicatif / excédent à faire valoir"
                      : etat.statut === "equilibre_indicatif"
                        ? "Solde indicatif de liquidation"
                        : "Reste à payer indicatif"}
                  </strong>
                </td>
                <td className="matx-montant">
                  <strong>{fmtMontant(etat.solde_indicatif.montant)}</strong>
                </td>
              </tr>
            </tbody>
          </table>
          <p className="muted">{etat.solde_indicatif.libelle}.</p>
          {etat.minimum_perception.imf_possible_signale && (
            <p className="muted">
              Le tableau de passage signale qu'un impôt minimum
              forfaitaire pourrait s'appliquer — non calculé ici, à
              vérifier par le fiscaliste.
            </p>
          )}
          {!etat.minimum_perception.calculable && (
            <p className="muted">{etat.minimum_perception.motif}</p>
          )}
        </>
      )}

      {etat.acomptes.length > 0 && (
        <details className="matx-detail">
          <summary>
            Acomptes saisis ({etat.acomptes.length})
          </summary>
          <table className="matx-table">
            <thead>
              <tr>
                <th scope="col">Nature</th>
                <th scope="col">Date</th>
                <th scope="col">Montant (FCFA)</th>
                <th scope="col">Quittance</th>
              </tr>
            </thead>
            <tbody>
              {etat.acomptes.map((a) => (
                <tr key={`${a.nature}-${a.date_versement}-${a.id ?? ""}`}>
                  <td className="matx-ref">{a.libelle_nature}</td>
                  <td>{a.date_versement || "—"}</td>
                  <td className="matx-montant">{fmtMontant(a.montant)}</td>
                  <td>{a.reference_quittance ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
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
