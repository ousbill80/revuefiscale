/** Historique pluriannuel du contribuable — récurrence et prescription.
 *
 * Tableau exercice par exercice (statut mission, anomalies + tendance,
 * non vérifiables, montant) + rappel des risques ouverts. La mention de
 * prescription (3 ans en principe en Côte d'Ivoire) aide l'associé à
 * prioriser : les exercices anciens sont en principe prescrits.
 */
import { useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { libelleStatut } from "./MissionsVue";

type ConclusionsExercice = {
  anomalie: number;
  non_verifiable: number;
  conforme: number;
  autres: number;
};

type ExerciceHistorique = {
  exercice: number;
  mission_id: number;
  statut_mission: string;
  nb_executions: number;
  derniere_execution_id: number | null;
  conclusions: ConclusionsExercice;
  montant_anomalies: string;
  score_risque: number | null;
  tendance_anomalies: "hausse" | "baisse" | "stable" | null;
};

type RisqueOuvert = {
  id: number;
  libelle: string;
  impot: string;
  exercice_origine: number;
  statut: string;
  montant_estime: string | null;
};

export type HistoriqueContribuable = {
  contribuable: { id: number; denomination: string; ncc: string | null };
  exercices: ExerciceHistorique[];
  risques_ouverts: RisqueOuvert[];
  synthese: {
    nb_exercices: number;
    total_anomalies_dernier_exercice: number;
    exercices_avec_anomalies: number;
  };
};

const TENDANCES: Record<
  NonNullable<ExerciceHistorique["tendance_anomalies"]>,
  { fleche: string; label: string }
> = {
  hausse: { fleche: "↑", label: "en hausse vs exercice précédent" },
  baisse: { fleche: "↓", label: "en baisse vs exercice précédent" },
  stable: { fleche: "→", label: "stable vs exercice précédent" },
};

type Props = {
  jeton: string;
  contribuableId: number;
  onOuvrirMission?: (id: number) => void;
};

export function HistoriqueContribuablePanel({
  jeton,
  contribuableId,
  onOuvrirMission,
}: Props) {
  const [historique, setHistorique] =
    useState<HistoriqueContribuable | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [chargement, setChargement] = useState(true);

  useEffect(() => {
    let annule = false;
    setChargement(true);
    setErreur(null);
    void (async () => {
      try {
        const h = await api<HistoriqueContribuable>(
          `/api/v1/contribuables/${contribuableId}/historique`,
          { jeton },
        );
        if (!annule) setHistorique(h);
      } catch (e) {
        if (!annule) {
          setHistorique(null);
          setErreur(
            e instanceof Error ? e.message : "historique indisponible",
          );
        }
      } finally {
        if (!annule) setChargement(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, [contribuableId, jeton]);

  const anneePrescription = new Date().getFullYear() - 3;

  if (chargement) {
    return (
      <div className="panel dense clients-panel">
        <p className="clients-panel-hint">Chargement de l’historique…</p>
      </div>
    );
  }
  if (erreur || !historique) {
    return (
      <div className="panel dense clients-panel">
        <p className="clients-panel-hint">
          Historique indisponible{erreur ? ` — ${erreur}` : ""}.
        </p>
      </div>
    );
  }

  const { exercices, risques_ouverts: risquesOuverts, synthese } = historique;

  return (
    <div className="clients-historique">
      <div className="panel dense clients-panel">
        <div className="clients-panel-head">
          <div>
            <p className="picker-kicker">Vision pluriannuelle</p>
            <p className="clients-panel-hint">
              {synthese.nb_exercices} exercice
              {synthese.nb_exercices !== 1 ? "s" : ""} suivi
              {synthese.nb_exercices !== 1 ? "s" : ""}
              {synthese.nb_exercices > 0
                ? ` · ${synthese.exercices_avec_anomalies} avec anomalies · ${synthese.total_anomalies_dernier_exercice} anomalie${synthese.total_anomalies_dernier_exercice !== 1 ? "s" : ""} sur le dernier exercice`
                : ""}
            </p>
          </div>
        </div>

        {exercices.length === 0 ? (
          <p className="clients-panel-hint">
            Aucune mission pour ce contribuable — l’historique se
            construira au fil des exercices.
          </p>
        ) : (
          <div className="balance-table-wrap">
            <table className="balance-table" aria-label="Historique par exercice">
              <thead>
                <tr>
                  <th scope="col">Exercice</th>
                  <th scope="col">Mission</th>
                  <th scope="col">Statut</th>
                  <th scope="col" className="num">
                    Exécutions
                  </th>
                  <th scope="col" className="num">
                    Anomalies
                  </th>
                  <th scope="col" className="num">
                    Non vérifiables
                  </th>
                  <th scope="col" className="num">
                    Montant anomalies (FCFA)
                  </th>
                </tr>
              </thead>
              <tbody>
                {exercices.map((e) => {
                  const tendance = e.tendance_anomalies
                    ? TENDANCES[e.tendance_anomalies]
                    : null;
                  return (
                    <tr key={e.mission_id}>
                      <td>
                        <strong>{e.exercice}</strong>
                        {e.exercice < anneePrescription ? (
                          <span
                            className="clients-panel-hint"
                            title="Exercice en principe prescrit (3 ans) sauf exceptions"
                          >
                            {" "}
                            · prescrit ?
                          </span>
                        ) : null}
                      </td>
                      <td>
                        {onOuvrirMission ? (
                          <button
                            type="button"
                            className="linkish"
                            onClick={() => onOuvrirMission(e.mission_id)}
                          >
                            #{e.mission_id}
                          </button>
                        ) : (
                          <>#{e.mission_id}</>
                        )}
                      </td>
                      <td>
                        <span className={`badge statut-${e.statut_mission}`}>
                          {libelleStatut(e.statut_mission)}
                        </span>
                      </td>
                      <td className="num">{e.nb_executions}</td>
                      <td className="num">
                        {e.conclusions.anomalie}
                        {tendance ? (
                          <span
                            aria-label={tendance.label}
                            title={tendance.label}
                          >
                            {" "}
                            {tendance.fleche}
                          </span>
                        ) : null}
                      </td>
                      <td className="num">{e.conclusions.non_verifiable}</td>
                      <td className="num">
                        {e.conclusions.anomalie > 0
                          ? fmtMontant(e.montant_anomalies)
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel dense clients-panel">
        <div className="clients-panel-head">
          <div>
            <p className="picker-kicker">Risques ouverts</p>
            <p className="clients-panel-hint">
              {risquesOuverts.length === 0
                ? "Aucun risque ouvert au registre."
                : `${risquesOuverts.length} risque${risquesOuverts.length !== 1 ? "s" : ""} non clos — tous exercices confondus.`}
            </p>
          </div>
        </div>
        {risquesOuverts.length > 0 && (
          <div className="balance-table-wrap">
            <table
              className="balance-table"
              aria-label="Risques ouverts du contribuable"
            >
              <thead>
                <tr>
                  <th scope="col">Impôt</th>
                  <th scope="col">Libellé</th>
                  <th scope="col" className="num">
                    Exercice
                  </th>
                  <th scope="col">Statut</th>
                  <th scope="col" className="num">
                    Montant estimé (FCFA)
                  </th>
                </tr>
              </thead>
              <tbody>
                {risquesOuverts.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <code>{r.impot}</code>
                    </td>
                    <td>{r.libelle}</td>
                    <td className="num">{r.exercice_origine}</td>
                    <td>
                      {r.statut === "en_traitement"
                        ? "En traitement"
                        : "Ouvert"}
                    </td>
                    <td className="num">
                      {r.montant_estime != null
                        ? fmtMontant(r.montant_estime)
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p className="echeancier-note" role="note">
        Prescription générale de 3 ans — exercices antérieurs à{" "}
        {anneePrescription} en principe prescrits sauf exceptions.
      </p>
    </div>
  );
}
