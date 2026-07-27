import { useEffect, useState } from "react";
import { api } from "./api";
import { InfoTip } from "./Tooltip";

/** Bilan de pré-clôture (GET /missions/{id}/bilan-cloture).
 *
 * Agrégation consultative des signaux existants de la mission — visas,
 * temps saisis, demande de renseignements, note de synthèse, data room,
 * risques ouverts — en points « ok » / « attention ». Jamais bloquant :
 * la clôture reste à l'appréciation du fiscaliste.
 */
type PointBilan = {
  code: string;
  libelle: string;
  statut: "ok" | "attention" | string;
};

type BilanClotureOut = {
  mission_id: number;
  statut_mission: string;
  points: PointBilan[];
  synthese: {
    points_ok: number;
    points_attention: number;
    pret: boolean;
  };
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
  onFermer: () => void;
};

export function BilanClotureVue({ missionId, jeton, onFermer }: Props) {
  const [etat, setEtat] = useState<BilanClotureOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!jeton || !missionId) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<BilanClotureOut>(
          `/api/v1/missions/${missionId}/bilan-cloture`,
          { jeton },
        );
        if (!annule) setEtat(out ?? null);
      } catch (e) {
        if (!annule) {
          setEtat(null);
          setErr(
            e instanceof Error ? e.message : "bilan de clôture indisponible",
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
      className="rest-suivi bilancloture"
      aria-label="Bilan de clôture"
    >
      <div className="rest-suivi-head">
        <h3 className="rest-suivi-titre label-with-tip">
          Bilan de clôture
          <InfoTip
            label="Vue d'ensemble consultative avant clôture : visas, temps saisis, demande de renseignements, note de synthèse, data room et risques ouverts. Jamais bloquant — la clôture reste possible telle quelle."
            ariaLabel="Aide : bilan de clôture"
          />
        </h3>
        <div className="rest-suivi-outils">
          {etat && etat.statut_mission === "cloturee" && (
            <span className="muted">Mission déjà clôturée</span>
          )}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onFermer}
          >
            Fermer
          </button>
        </div>
      </div>
      {busy && <p className="muted">Bilan de pré-clôture…</p>}
      {err && (
        <p className="rest-lettre-err" role="alert">
          Bilan de clôture indisponible : {err}
        </p>
      )}
      {etat && (
        <>
          <div
            className={`bilancloture-synthese ${
              etat.synthese.pret
                ? "bilancloture-synthese--pret"
                : "bilancloture-synthese--attention"
            }`}
          >
            <span className="bilancloture-verdict">
              {etat.synthese.pret ? "Prêt à clôturer" : "Points d'attention"}
            </span>
            <span className="bilancloture-compteurs">
              {etat.synthese.points_ok} point
              {etat.synthese.points_ok > 1 ? "s" : ""} ok ·{" "}
              {etat.synthese.points_attention} point
              {etat.synthese.points_attention > 1 ? "s" : ""} d'attention
            </span>
          </div>

          <ul className="bilancloture-points">
            {etat.points.map((p) => (
              <li
                key={p.code}
                className={`bilancloture-point bilancloture-point--${p.statut}`}
              >
                <span
                  className={`bilancloture-pastille bilancloture-pastille--${p.statut}`}
                  aria-hidden="true"
                />
                <span className="bilancloture-libelle">{p.libelle}</span>
              </li>
            ))}
          </ul>

          {etat.note && <p className="bilancloture-note muted">{etat.note}</p>}
        </>
      )}
    </section>
  );
}
