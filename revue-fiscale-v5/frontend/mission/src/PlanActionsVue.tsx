import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { InfoTip } from "./Tooltip";

/** Plan d'actions post-revue (GET /missions/{id}/plan-actions).
 *
 * Dérivation déterministe d'une action suggérée par risque non clos du
 * contribuable de la mission : déclaration rectificative, provision à
 * documenter, justificatif à collecter ou point à discuter — avec
 * priorité (haute / moyenne / basse) et motifs traçables.
 * Consultatif — le fiscaliste apprécie, le client décide. Le fiscaliste
 * peut marquer chaque action « retenue », « écartée » ou « faite »
 * (POST /missions/{id}/plan-actions/{cle_action}/decision — décision
 * humaine persistée par-dessus le plan dérivé).
 */
type Decision = "retenue" | "ecartee" | "faite";

type ActionPlan = {
  cle_action: string;
  risque_id: number;
  libelle_risque: string;
  impot: string;
  exercice_origine: number;
  statut_risque: string;
  probabilite: string;
  exposition: string | null;
  date_prescription: string;
  type_action: string;
  action: string;
  priorite: "haute" | "moyenne" | "basse" | string;
  motifs: string[];
  decision: Decision | null;
  decision_note: string | null;
  decision_maj_le: string | null;
};

type PlanActionsOut = {
  mission_id: number;
  contribuable_id: number;
  date_analyse: string;
  plan: ActionPlan[];
  synthese: {
    total_actions: number;
    par_priorite: { haute: number; moyenne: number; basse: number };
    exposition_totale: string;
    decisions: {
      retenues: number;
      ecartees: number;
      faites: number;
      sans_decision: number;
    };
  };
  note: string;
};

/** Montant str Decimal → « 1 234 567 FCFA » (fr-FR, sans décimales). */
function fmtMontant(v: string | null | undefined): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString("fr-FR", { maximumFractionDigits: 0 }) + " FCFA";
}

/** Date ISO (AAAA-MM-JJ) → JJ/MM/AAAA, sans fuseau. */
function fmtDate(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso ?? ""));
  if (!m) return iso || "—";
  return `${m[3]}/${m[2]}/${m[1]}`;
}

const LIBELLES_PRIORITE: Record<string, string> = {
  haute: "Priorité haute",
  moyenne: "Priorité moyenne",
  basse: "Priorité basse",
};

const LIBELLES_DECISION: Record<string, string> = {
  retenue: "Retenue",
  ecartee: "Écartée",
  faite: "Faite",
};

type Props = {
  missionId: number;
  jeton?: string | null;
  estCloturee?: boolean;
  estLecteur?: boolean;
  onFermer: () => void;
};

export function PlanActionsVue({
  missionId,
  jeton,
  estCloturee,
  estLecteur,
  onFermer,
}: Props) {
  const [etat, setEtat] = useState<PlanActionsOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [decisionBusyCle, setDecisionBusyCle] = useState<string | null>(null);
  const [decisionErr, setDecisionErr] = useState<string | null>(null);
  const [decisionOk, setDecisionOk] = useState<string | null>(null);

  const charger = useCallback(async () => {
    const out = await api<PlanActionsOut>(
      `/api/v1/missions/${missionId}/plan-actions`,
      { jeton },
    );
    return out ?? null;
  }, [jeton, missionId]);

  useEffect(() => {
    if (!jeton || !missionId) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await charger();
        if (!annule) setEtat(out);
      } catch (e) {
        if (!annule) {
          setEtat(null);
          setErr(
            e instanceof Error
              ? e.message
              : "plan d'actions indisponible",
          );
        }
      } finally {
        if (!annule) setBusy(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, [jeton, missionId, charger]);

  const decider = async (a: ActionPlan, decision: Decision) => {
    if (!jeton || estLecteur || estCloturee || decisionBusyCle) return;
    setDecisionBusyCle(a.cle_action);
    setDecisionErr(null);
    setDecisionOk(null);
    try {
      await api(
        `/api/v1/missions/${missionId}/plan-actions/${encodeURIComponent(
          a.cle_action,
        )}/decision`,
        { jeton, method: "POST", json: { decision } },
      );
      setDecisionOk(
        `Action « ${LIBELLES_DECISION[decision].toLowerCase()} » enregistrée.`,
      );
      setEtat(await charger());
    } catch (e) {
      setDecisionErr(
        e instanceof Error ? e.message : "décision non enregistrée",
      );
    } finally {
      setDecisionBusyCle(null);
    }
  };

  return (
    <section
      className="rest-suivi rest-prescription rest-planactions"
      aria-label="Plan d'actions post-revue"
    >
      <div className="rest-suivi-head">
        <h3 className="rest-suivi-titre label-with-tip">
          Plan d'actions post-revue
          <InfoTip
            label="Dérivation déterministe d'une action suggérée par risque non clos du client : déclaration rectificative, provision à documenter, justificatif à collecter ou point à discuter — avec priorité et motifs traçables. Consultatif : le fiscaliste apprécie, le client décide."
            ariaLabel="Aide : plan d'actions post-revue"
          />
        </h3>
        <div className="rest-suivi-outils">
          {etat && (
            <span className="muted">
              Analyse au {fmtDate(etat.date_analyse)}
            </span>
          )}
          <button type="button" className="btn btn-ghost btn-sm" onClick={onFermer}>
            Fermer
          </button>
        </div>
      </div>
      {busy && <p className="muted">Dérivation du plan d'actions…</p>}
      {err && (
        <p className="rest-lettre-err" role="alert">
          Plan d'actions indisponible : {err}
        </p>
      )}
      {etat && (
        <>
          <div className="rest-prescription-synthese">
            <div className="rest-prescription-stat">
              <span className="rest-prescription-stat-val">
                {etat.synthese.total_actions}
              </span>
              <span className="rest-prescription-stat-lbl">
                Action{etat.synthese.total_actions > 1 ? "s" : ""} suggérée
                {etat.synthese.total_actions > 1 ? "s" : ""}
              </span>
            </div>
            <div className="rest-prescription-stat planactions-stat--haute">
              <span className="rest-prescription-stat-val">
                {etat.synthese.par_priorite.haute}
              </span>
              <span className="rest-prescription-stat-lbl">
                Priorité haute
              </span>
            </div>
            <div className="rest-prescription-stat planactions-stat--moyenne">
              <span className="rest-prescription-stat-val">
                {etat.synthese.par_priorite.moyenne}
              </span>
              <span className="rest-prescription-stat-lbl">
                Priorité moyenne
              </span>
            </div>
            <div className="rest-prescription-stat">
              <span className="rest-prescription-stat-val">
                {etat.synthese.par_priorite.basse}
              </span>
              <span className="rest-prescription-stat-lbl">
                Priorité basse
              </span>
            </div>
            <div className="rest-prescription-stat">
              <span className="rest-prescription-stat-val">
                {fmtMontant(etat.synthese.exposition_totale)}
              </span>
              <span className="rest-prescription-stat-lbl">
                Exposition totale
              </span>
            </div>
            <div className="rest-prescription-stat planactions-stat--decisions">
              <span className="rest-prescription-stat-val">
                {etat.synthese.decisions.retenues} /{" "}
                {etat.synthese.decisions.ecartees} /{" "}
                {etat.synthese.decisions.faites}
              </span>
              <span className="rest-prescription-stat-lbl">
                Retenues / écartées / faites
                {etat.synthese.decisions.sans_decision > 0 && (
                  <>
                    {" — "}
                    {etat.synthese.decisions.sans_decision} sans décision
                  </>
                )}
              </span>
            </div>
          </div>

          {decisionErr && (
            <p className="rest-lettre-err" role="alert">
              Décision non enregistrée : {decisionErr}
            </p>
          )}
          {decisionOk && !decisionErr && (
            <p className="planactions-decision-ok" role="status">
              {decisionOk}
            </p>
          )}

          {etat.plan.length === 0 ? (
            <p className="muted">
              Aucun risque ouvert — rien à planifier.
            </p>
          ) : (
            <ul className="rest-suivi-items rest-prescription-items">
              {etat.plan.map((a) => (
                <li
                  key={a.cle_action}
                  className={`rest-suivi-item rest-prescription-item planactions-item--${a.priorite}${
                    a.decision ? ` planactions-item--dec-${a.decision}` : ""
                  }`}
                >
                  <div className="rest-suivi-libelle">
                    <span
                      className={`rest-prescription-badge planactions-badge--${a.priorite}`}
                    >
                      {LIBELLES_PRIORITE[a.priorite] ?? a.priorite}
                    </span>
                    <span className="rest-prescription-libelle planactions-action">
                      {a.action || "—"}
                    </span>
                    {a.decision && (
                      <span
                        className={`rest-prescription-badge planactions-decision-badge planactions-decision--${a.decision}`}
                      >
                        {LIBELLES_DECISION[a.decision] ?? a.decision}
                      </span>
                    )}
                    <span className="planactions-decisions">
                      {(
                        ["retenue", "ecartee", "faite"] as Decision[]
                      ).map((d) => (
                        <button
                          key={d}
                          type="button"
                          className={`btn btn-ghost btn-sm planactions-btn-decision${
                            a.decision === d
                              ? " planactions-btn-decision--active"
                              : ""
                          }`}
                          disabled={
                            estLecteur ||
                            estCloturee ||
                            decisionBusyCle !== null ||
                            a.decision === d
                          }
                          onClick={() => void decider(a, d)}
                          title={
                            d === "retenue"
                              ? "Retenir cette action (à mettre en œuvre)"
                              : d === "ecartee"
                                ? "Écarter cette action (non pertinente)"
                                : "Marquer cette action comme faite"
                          }
                        >
                          {d === "retenue"
                            ? "Retenir"
                            : d === "ecartee"
                              ? "Écarter"
                              : "Fait"}
                        </button>
                      ))}
                    </span>
                  </div>
                  <div className="rest-prescription-meta muted">
                    {a.impot && <span className="rest-suivi-cle">{a.impot}</span>}
                    {a.libelle_risque && (
                      <span>Risque : {a.libelle_risque}</span>
                    )}
                    <span>Exercice {a.exercice_origine}</span>
                    {a.exposition != null && a.exposition !== "" && (
                      <span>Exposition : {fmtMontant(a.exposition)}</span>
                    )}
                  </div>
                  {a.motifs.length > 0 && (
                    <div className="rest-prescription-meta muted planactions-motifs">
                      <span>Motifs : {a.motifs.join(" ; ")}</span>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}

          {etat.note && (
            <p className="rest-prescription-hypothese muted">{etat.note}</p>
          )}
        </>
      )}
    </section>
  );
}
