import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Contrôle qualité de la balance importée — vue consultative.
 *
 * Fiabilité de la matière première avant toute revue fiscale : trois
 * contrôles déterministes — équilibre global (total débits / total
 * crédits, écart en montant), soldes de sens inhabituel sur les
 * classes sensibles SYSCOHADA (caisse 57x, banques 52x, fournisseurs
 * 401x, clients 411x, amortissements 28x, capital 101x) et numéros de
 * compte hors plan. Chaque observation ORIENTE la revue et peut être
 * justifiée (découvert bancaire, avoirs, acomptes…) — lecture seule,
 * seul l'humain examine et conclut.
 */
type ObservationQualite = {
  compte: string;
  libelle_compte: string;
  solde: string;
  observation: string;
};

type ControleQualite = {
  observations: ObservationQualite[];
  nb_total: number;
  plafonne: boolean;
};

type QualiteBalanceOut = {
  mission_id: number;
  exercice: number;
  disponible: boolean;
  equilibre: {
    total_debits: string;
    total_credits: string;
    ecart: string;
    equilibree: boolean;
  };
  sens_inhabituels: ControleQualite;
  comptes_hors_plan: ControleQualite;
  statut: string;
  synthese: {
    statut: string;
    libelle_statut: string;
    nb_controles: number;
    nb_observations: number;
  };
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

function TableObservations({
  controle,
  titre,
}: {
  controle: ControleQualite;
  titre: string;
}) {
  if (controle.nb_total === 0) return null;
  return (
    <>
      <table className="matx-table">
        <thead>
          <tr>
            <th scope="col">{titre}</th>
            <th scope="col">Solde net (FCFA)</th>
            <th scope="col">Observation</th>
          </tr>
        </thead>
        <tbody>
          {controle.observations.map((o) => (
            <tr key={o.compte}>
              <td className="matx-ref">
                {o.compte}
                {o.libelle_compte ? <> — {o.libelle_compte}</> : null}
              </td>
              <td className="matx-montant">{fmtMontant(o.solde)}</td>
              <td>{o.observation}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {controle.plafonne && (
        <p className="muted">
          Restitution plafonnée : {controle.observations.length}{" "}
          observations affichées sur {controle.nb_total} détectées —
          l'export de la balance permet l'examen exhaustif.
        </p>
      )}
    </>
  );
}

export function QualiteBalanceVue({ missionId, jeton }: Props) {
  const [etat, setEtat] = useState<QualiteBalanceOut | null>(null);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<QualiteBalanceOut>(
        `/api/v1/missions/${missionId}/qualite-balance`,
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
      aria-label="Contrôle qualité de la balance importée"
    >
      <div className="matx-head">
        <h4 className="matx-titre label-with-tip">
          Contrôle qualité de la balance importée
          <InfoTip
            label="Fiabilité de la matière première avant la revue : équilibre global (total débits / total crédits), soldes de sens inhabituel sur les classes sensibles SYSCOHADA (caisse 57x, banques 52x, fournisseurs 401x, clients 411x, amortissements 28x, capital 101x) et numéros de compte hors plan. Chaque observation oriente la revue et peut être justifiée (découvert bancaire, avoirs, acomptes fournisseurs…) — seul l'humain examine et conclut."
            ariaLabel="Aide : contrôle qualité de la balance importée"
          />
        </h4>
        <span className="matx-synthese muted">
          {etat.disponible ? (
            <>
              {etat.synthese.nb_observations === 0
                ? "Équilibrée, sans observation"
                : `${etat.synthese.nb_observations} observation${
                    etat.synthese.nb_observations > 1 ? "s" : ""
                  } à examiner`}
            </>
          ) : (
            "Indisponible"
          )}
        </span>
      </div>

      {!etat.disponible ? (
        <p className="empty-state">
          Vue indisponible : importez la balance pour contrôler sa
          qualité (équilibre, sens des soldes, plan de comptes) avant
          la revue fiscale.
        </p>
      ) : (
        <>
          <table className="matx-table">
            <thead>
              <tr>
                <th scope="col">Équilibre global</th>
                <th scope="col">Montant (FCFA)</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="matx-ref">Total des débits</td>
                <td className="matx-montant">
                  {fmtMontant(etat.equilibre.total_debits)}
                </td>
              </tr>
              <tr>
                <td className="matx-ref">Total des crédits</td>
                <td className="matx-montant">
                  {fmtMontant(etat.equilibre.total_credits)}
                </td>
              </tr>
              <tr>
                <td className="matx-ref">
                  <strong>
                    {etat.equilibre.equilibree
                      ? "Écart (balance équilibrée)"
                      : "Écart — à examiner"}
                  </strong>
                  <InfoTip
                    label="Écart entre total des débits et total des crédits de la balance importée — un écart peut provenir d'arrondis ou du paramétrage d'import : simple constat, à examiner avec le client, jamais une conclusion."
                    ariaLabel="Aide : écart d'équilibre"
                  />
                </td>
                <td className="matx-montant">
                  <strong>{fmtMontant(etat.equilibre.ecart)}</strong>
                </td>
              </tr>
            </tbody>
          </table>

          <TableObservations
            controle={etat.sens_inhabituels}
            titre="Soldes de sens inhabituel"
          />
          <TableObservations
            controle={etat.comptes_hors_plan}
            titre="Comptes hors plan"
          />

          <p className="muted">{etat.synthese.libelle_statut}.</p>
        </>
      )}

      <p className="matx-note muted">{etat.note}</p>
    </section>
  );
}
