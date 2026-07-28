import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Revue de déductibilité des charges — vue consultative.
 *
 * Balaye les comptes de charges (classe 6 SYSCOHADA) de la balance
 * importée et signale les points de vigilance de réintégration
 * fiscale IS selon un référentiel déterministe (CGI ivoirien,
 * art. 18 notamment) : amendes non déductibles, cadeaux et dons
 * plafonnés, frais de siège, intérêts de comptes courants
 * d'associés, provisions… AUCUN calcul de réintégration automatique :
 * les soldes signalés restent à apprécier par le fiscaliste —
 * lecture seule, l'humain décide.
 */
type CompteConcerne = {
  compte: string;
  libelle: string;
  solde: string;
};

type PointVigilance = {
  code: string;
  libelle: string;
  regle: string;
  gravite: string;
  gravite_libelle: string;
  prefixes: string[];
  nb_comptes: number;
  total_solde: string;
  comptes: CompteConcerne[];
};

type RegleReferentiel = {
  code: string;
  libelle: string;
  regle: string;
  gravite: string;
  gravite_libelle: string;
  prefixes: string[];
};

type DeductibiliteOut = {
  mission_id: number;
  exercice: number;
  disponible: boolean;
  points: PointVigilance[];
  referentiel: RegleReferentiel[];
  synthese: {
    statut: string;
    nb_points: number;
    nb_par_gravite: Record<string, number>;
    total_soldes_concernes: string;
    nb_comptes_charges: number;
    total_charges: string;
  };
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

const GRAVITE_LABELS: Record<string, string> = {
  non_deductible: "Non déductible",
  plafond: "Plafond",
  appreciation: "À apprécier",
};

export function DeductibiliteVue({ missionId, jeton }: Props) {
  const [etat, setEtat] = useState<DeductibiliteOut | null>(null);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<DeductibiliteOut>(
        `/api/v1/missions/${missionId}/deductibilite`,
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
      aria-label="Revue de déductibilité des charges"
    >
      <div className="matx-head">
        <h4 className="matx-titre label-with-tip">
          Revue de déductibilité des charges
          <InfoTip
            label="Points de vigilance de réintégration fiscale IS repérés depuis les comptes de charges (classe 6) de la balance, selon un référentiel déterministe du CGI ivoirien (art. 18 notamment). Aucune réintégration n'est calculée automatiquement : les soldes signalés sont à apprécier par le fiscaliste — vue consultative, l'humain décide."
            ariaLabel="Aide : revue de déductibilité des charges"
          />
        </h4>
        <span className="matx-synthese muted">
          {s.nb_comptes_charges} compte
          {s.nb_comptes_charges > 1 ? "s" : ""} de charges
          {s.nb_points > 0 && (
            <>
              {" "}
              ·{" "}
              <strong className="matx-badge-cible">
                {s.nb_points} point{s.nb_points > 1 ? "s" : ""} de
                vigilance ({fmtMontant(s.total_soldes_concernes)} FCFA
                concernés)
              </strong>
            </>
          )}
        </span>
      </div>

      {!etat.disponible ? (
        <p className="empty-state">
          Revue de déductibilité indisponible : importez une balance
          pour balayer les comptes de charges (classe 6).
        </p>
      ) : s.nb_points === 0 ? (
        <p className="empty-state">
          Aucun point de vigilance repéré sur les comptes de charges
          de la balance — le référentiel appliqué reste consultable
          ci-dessous.
        </p>
      ) : (
        <>
          <p className="muted">
            {s.nb_par_gravite.non_deductible ?? 0} non déductible(s) ·{" "}
            {s.nb_par_gravite.plafond ?? 0} plafonné(s) ·{" "}
            {s.nb_par_gravite.appreciation ?? 0} à apprécier — soldes
            concernés {fmtMontant(s.total_soldes_concernes)} FCFA sur{" "}
            {fmtMontant(s.total_charges)} FCFA de charges.
          </p>
          <table className="matx-table">
            <thead>
              <tr>
                <th scope="col">Point de vigilance</th>
                <th scope="col">Gravité</th>
                <th scope="col">Comptes</th>
                <th scope="col">Solde concerné (FCFA)</th>
              </tr>
            </thead>
            <tbody>
              {etat.points.map((p) => (
                <tr key={p.code}>
                  <td className="matx-ref">
                    {p.libelle}
                    <InfoTip
                      label={p.regle}
                      ariaLabel={`Règle fiscale : ${p.libelle}`}
                    />
                  </td>
                  <td>
                    {GRAVITE_LABELS[p.gravite] ?? p.gravite_libelle}
                  </td>
                  <td className="matx-montant">{p.nb_comptes}</td>
                  <td className="matx-montant">
                    {fmtMontant(p.total_solde)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <details className="matx-detail">
            <summary>
              Comptes concernés et règles fiscales détaillées (
              {etat.points.reduce((n, p) => n + p.nb_comptes, 0)}{" "}
              comptes)
            </summary>
            {etat.points.map((p) => (
              <div key={p.code} className="matx-detail">
                <p>
                  <strong>{p.libelle}</strong> (
                  {GRAVITE_LABELS[p.gravite] ?? p.gravite_libelle},
                  comptes {p.prefixes.join(", ")}) — {p.regle}
                </p>
                <table className="matx-table">
                  <thead>
                    <tr>
                      <th scope="col">Compte</th>
                      <th scope="col">Libellé</th>
                      <th scope="col">Solde (FCFA)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.comptes.map((c) => (
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
              </div>
            ))}
          </details>
        </>
      )}

      {etat.disponible && (
        <details className="matx-detail">
          <summary>
            Référentiel appliqué ({etat.referentiel.length} règles CGI)
          </summary>
          <table className="matx-table">
            <thead>
              <tr>
                <th scope="col">Comptes</th>
                <th scope="col">Point</th>
                <th scope="col">Gravité</th>
                <th scope="col">Règle fiscale</th>
              </tr>
            </thead>
            <tbody>
              {etat.referentiel.map((r) => (
                <tr key={r.code}>
                  <td>{r.prefixes.join(", ")}</td>
                  <td className="matx-ref">{r.libelle}</td>
                  <td>{GRAVITE_LABELS[r.gravite] ?? r.gravite_libelle}</td>
                  <td>{r.regle}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <p className="matx-note muted">{etat.note}</p>
    </section>
  );
}
