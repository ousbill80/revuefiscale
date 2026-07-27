import { useEffect, useState } from "react";
import { api } from "./api";
import { InfoTip } from "./Tooltip";

/** Chronologie de la mission (GET /missions/{id}/chronologie).
 *
 * Restitution consultative du journal d'audit de la mission : qui a
 * fait quoi et quand (dépôts de pièces, changements de statut,
 * décisions du plan d'actions, relances, exports…), en libellés
 * français, ordre antichronologique. Les consultations de la
 * chronologie elle-même n'y figurent pas.
 */
type EvenementChronologie = {
  id: number;
  horodatage: string;
  acteur: string;
  action: string;
  libelle: string;
};

type ChronologieOut = {
  mission_id: number;
  evenements: EvenementChronologie[];
  total_affiche: number;
  plafond: number;
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
  onFermer: () => void;
};

/** ISO 8601 → « JJ/MM/AAAA HH:MM » (heure locale) — fallback brut. */
function formatDateHeure(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const jj = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${jj}/${mm}/${d.getFullYear()} ${hh}:${mi}`;
}

export function ChronologieMissionVue({ missionId, jeton, onFermer }: Props) {
  const [etat, setEtat] = useState<ChronologieOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!jeton || !missionId) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<ChronologieOut>(
          `/api/v1/missions/${missionId}/chronologie`,
          { jeton },
        );
        if (!annule) setEtat(out ?? null);
      } catch (e) {
        if (!annule) {
          setEtat(null);
          setErr(
            e instanceof Error ? e.message : "chronologie indisponible",
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
      className="rest-suivi chronomission"
      aria-label="Chronologie de la mission"
    >
      <div className="rest-suivi-head">
        <h3 className="rest-suivi-titre label-with-tip">
          Chronologie de la mission
          <InfoTip
            label="Traçabilité consultative issue du journal d'audit : qui a fait quoi et quand sur la mission (dépôts de pièces, changements de statut, décisions, relances, exports…). Les événements les plus récents d'abord."
            ariaLabel="Aide : chronologie de la mission"
          />
        </h3>
        <div className="rest-suivi-outils">
          {etat && (
            <span className="muted">
              {etat.total_affiche} événement
              {etat.total_affiche > 1 ? "s" : ""}
              {etat.total_affiche >= etat.plafond
                ? ` (les ${etat.plafond} plus récents)`
                : ""}
            </span>
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
      {busy && <p className="muted">Chronologie…</p>}
      {err && (
        <p className="rest-lettre-err" role="alert">
          Chronologie indisponible : {err}
        </p>
      )}
      {etat && !busy && etat.evenements.length === 0 && (
        <p className="muted">Aucun événement journalisé sur cette mission.</p>
      )}
      {etat && etat.evenements.length > 0 && (
        <ul className="chronomission-liste">
          {etat.evenements.map((e) => (
            <li key={e.id} className="chronomission-item">
              <span className="chronomission-date">
                {formatDateHeure(e.horodatage)}
              </span>
              <span className="chronomission-acteur">{e.acteur}</span>
              <span className="chronomission-libelle">{e.libelle}</span>
            </li>
          ))}
        </ul>
      )}
      {etat?.note && <p className="chronomission-note muted">{etat.note}</p>}
    </section>
  );
}
