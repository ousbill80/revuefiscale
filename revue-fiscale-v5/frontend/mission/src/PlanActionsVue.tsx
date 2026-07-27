import { useEffect, useState } from "react";
import { api } from "./api";
import { InfoTip } from "./Tooltip";

/** Plan d'actions post-revue (GET /missions/{id}/plan-actions).
 *
 * Dérivation déterministe d'une action suggérée par risque non clos du
 * contribuable de la mission : déclaration rectificative, provision à
 * documenter, justificatif à collecter ou point à discuter — avec
 * priorité (haute / moyenne / basse) et motifs traçables.
 * Consultatif — le fiscaliste apprécie, le client décide.
 */
type ActionPlan = {
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

type Props = {
  missionId: number;
  jeton?: string | null;
  onFermer: () => void;
};

export function PlanActionsVue({ missionId, jeton, onFermer }: Props) {
  const [etat, setEtat] = useState<PlanActionsOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!jeton || !missionId) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<PlanActionsOut>(
          `/api/v1/missions/${missionId}/plan-actions`,
          { jeton },
        );
        if (!annule) setEtat(out ?? null);
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
  }, [jeton, missionId]);

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
          </div>

          {etat.plan.length === 0 ? (
            <p className="muted">
              Aucun risque ouvert — rien à planifier.
            </p>
          ) : (
            <ul className="rest-suivi-items rest-prescription-items">
              {etat.plan.map((a) => (
                <li
                  key={a.risque_id}
                  className={`rest-suivi-item rest-prescription-item planactions-item--${a.priorite}`}
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
