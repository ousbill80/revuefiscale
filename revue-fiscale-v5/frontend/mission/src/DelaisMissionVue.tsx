import { useEffect, useState } from "react";
import { api } from "./api";
import { InfoTip } from "./Tooltip";

/** Délais de traitement par étape (GET /missions/{id}/delais).
 *
 * Vue consultative déduite du journal d'audit de la mission : jalons
 * datés (création, premier dépôt de pièce, demande de renseignements,
 * premières constatations, premier visa, restitution) et durées en
 * jours entre jalons consécutifs — pour voir où le temps se perd.
 */
type JalonDelais = {
  code: string;
  libelle: string;
  date: string | null;
};

type DureeDelais = {
  de: string;
  a: string;
  jours: string | null;
};

type DelaisOut = {
  mission_id: number;
  jalons: JalonDelais[];
  durees: DureeDelais[];
  duree_totale_jours: string | null;
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

export function DelaisMissionVue({ missionId, jeton, onFermer }: Props) {
  const [etat, setEtat] = useState<DelaisOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!jeton || !missionId) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<DelaisOut>(
          `/api/v1/missions/${missionId}/delais`,
          { jeton },
        );
        if (!annule) setEtat(out ?? null);
      } catch (e) {
        if (!annule) {
          setEtat(null);
          setErr(e instanceof Error ? e.message : "délais indisponibles");
        }
      } finally {
        if (!annule) setBusy(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, [jeton, missionId]);

  const dureeVers = (codeJalon: string): string | null | undefined =>
    etat?.durees.find((d) => d.a === codeJalon)?.jours;

  return (
    <section
      className="rest-suivi delais-mission"
      aria-label="Délais de traitement par étape"
    >
      <div className="rest-suivi-head">
        <h3 className="rest-suivi-titre label-with-tip">
          Délais de traitement
          <InfoTip
            label="Jalons datés de la mission déduits du journal d'audit (première occurrence de chaque étape) et durées en jours entre étapes consécutives — pour identifier où le temps se perd. Consultatif : l'humain interprète."
            ariaLabel="Aide : délais de traitement"
          />
        </h3>
        <div className="rest-suivi-outils">
          {etat?.duree_totale_jours != null && (
            <span className="muted">
              {etat.duree_totale_jours} jours au total
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
      {busy && <p className="muted">Délais…</p>}
      {err && (
        <p className="rest-lettre-err" role="alert">
          Délais indisponibles : {err}
        </p>
      )}
      {etat && !busy && (
        <ul className="delais-liste">
          {etat.jalons.map((j, idx) => {
            const jours = idx > 0 ? dureeVers(j.code) : undefined;
            return (
              <li key={j.code} className="delais-item">
                {idx > 0 && jours != null && (
                  <span className="delais-duree muted">
                    {jours.startsWith("-")
                      ? `− ${jours.slice(1)} j (avant l'étape précédente)`
                      : `+ ${jours} j`}
                  </span>
                )}
                <span className="delais-ligne">
                  <span className="delais-date">
                    {j.date ? formatDateHeure(j.date) : "—"}
                  </span>
                  <span
                    className={`delais-libelle${
                      j.date ? "" : " delais-absent"
                    }`}
                  >
                    {j.libelle}
                    {!j.date && " (étape non journalisée)"}
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {etat?.note && <p className="delais-note muted">{etat.note}</p>}
    </section>
  );
}
