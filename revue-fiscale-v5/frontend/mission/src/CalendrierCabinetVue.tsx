import { useEffect, useState } from "react";
import { api, telecharger } from "./api";

/** Calendrier fiscal du cabinet (GET /api/v1/cabinet/calendrier). */
type ElementCalendrier = {
  date: string;
  type: string;
  client: string;
  mission_id: number | null;
  libelle: string;
  depassee: boolean;
};

type MoisCalendrier = {
  mois: string;
  libelle_mois: string;
  elements: ElementCalendrier[];
};

type CalendrierOut = {
  aujourd_hui: string;
  horizon_mois: number;
  fin_horizon: string;
  mois: MoisCalendrier[];
  compteurs: {
    nb_total: number;
    nb_depassees: number;
    nb_a_venir: number;
  };
  sources_en_echec: string[];
  note: string;
};

type Props = {
  jeton?: string | null;
  onOuvrirMission: (missionId: number) => void;
};

const LIBELLES_TYPE: Record<string, string> = {
  echeance_fiscale: "Échéance fiscale",
  point_convenu: "Point convenu",
};

const HORIZONS = [1, 2, 3, 6, 12] as const;

function dateFr(iso: string): string {
  const [a, m, j] = iso.split("-");
  return a && m && j ? `${j}/${m}/${a}` : iso;
}

export function CalendrierCabinetVue({ jeton, onOuvrirMission }: Props) {
  const [vue, setVue] = useState<CalendrierOut | null>(null);
  const [horizon, setHorizon] = useState<number>(3);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [exportErr, setExportErr] = useState<string | null>(null);

  /** Télécharge le calendrier (.txt ou .csv) — diffusion interne. */
  async function telechargerExport(format: "txt" | "csv") {
    if (!jeton || exportBusy) return;
    setExportBusy(true);
    setExportErr(null);
    try {
      const jour = vue?.aujourd_hui ?? new Date().toISOString().slice(0, 10);
      await telecharger(
        `/api/v1/cabinet/calendrier.${format}?horizon_mois=${horizon}`,
        jeton,
        `calendrier-cabinet-${jour}.${format}`,
      );
    } catch (e) {
      setExportErr(
        e instanceof Error ? e.message : "téléchargement impossible",
      );
    } finally {
      setExportBusy(false);
    }
  }

  useEffect(() => {
    if (!jeton) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<CalendrierOut>(
          `/api/v1/cabinet/calendrier?horizon_mois=${horizon}`,
          { jeton },
        );
        if (!annule) setVue(out ?? null);
      } catch {
        if (!annule) {
          setVue(null);
          setErr("Calendrier indisponible pour le moment.");
        }
      } finally {
        if (!annule) setBusy(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, [jeton, horizon]);

  return (
    <section
      className="ctrale-zone"
      aria-label="Calendrier fiscal du cabinet"
    >
      <div className="ctrale-head">
        <div>
          <h3 className="ctrale-title">Calendrier fiscal du cabinet</h3>
          <p className="ctrale-sub">
            Mois par mois, les échéances fiscales des missions en cours et
            les points convenus datés — pour planifier la charge du cabinet,
            sans ouvrir chaque mission.
          </p>
        </div>
        <div className="ctrale-exports">
          <label className="calcab-horizon">
            Horizon{" "}
            <select
              value={horizon}
              onChange={(e) => setHorizon(Number(e.target.value))}
              disabled={busy}
            >
              {HORIZONS.map((h) => (
                <option key={h} value={h}>
                  {h} mois
                </option>
              ))}
            </select>
          </label>
          {vue && (
            <>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => void telechargerExport("txt")}
                disabled={exportBusy}
                title="Version texte lisible pour la réunion du cabinet"
              >
                Télécharger (.txt)
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => void telechargerExport("csv")}
                disabled={exportBusy}
                title="Version tableur (CSV point-virgule, Excel)"
              >
                Télécharger (.csv)
              </button>
              {exportErr && <span className="ctrale-err">{exportErr}</span>}
            </>
          )}
        </div>
      </div>

      <article className="panel dense ctrale-card">
        {busy && !vue && (
          <p className="ctrale-vide">Chargement du calendrier…</p>
        )}
        {err && !busy && <p className="ctrale-err">{err}</p>}

        {vue && (
          <>
            <div className="ctrale-synthese">
              <span className="ctrale-chip">
                <strong>{vue.compteurs.nb_total}</strong> échéance
                {vue.compteurs.nb_total > 1 ? "s" : ""} sur{" "}
                {vue.horizon_mois} mois
              </span>
              <span className="ctrale-chip">
                <strong>{vue.compteurs.nb_a_venir}</strong> à venir
              </span>
              {vue.compteurs.nb_depassees > 0 && (
                <span className="ctrale-chip vigilance">
                  <strong>{vue.compteurs.nb_depassees}</strong> date
                  {vue.compteurs.nb_depassees > 1 ? "s" : ""} déjà passée
                  {vue.compteurs.nb_depassees > 1 ? "s" : ""}
                </span>
              )}
            </div>

            {vue.sources_en_echec.length > 0 && (
              <p className="ctrale-echec">
                Source{vue.sources_en_echec.length > 1 ? "s" : ""}{" "}
                momentanément indisponible
                {vue.sources_en_echec.length > 1 ? "s" : ""} :{" "}
                {vue.sources_en_echec.join(", ")} — le reste du calendrier
                reste affiché.
              </p>
            )}

            {!vue.mois.length && (
              <p className="ctrale-vide">
                Aucune échéance sur l'horizon choisi.
              </p>
            )}

            {vue.mois.map((m) => (
              <div key={m.mois} className="calcab-mois">
                <h4 className="calcab-mois-titre">{m.libelle_mois}</h4>
                <ul className="ctrale-liste">
                  {m.elements.map((e, idx) => (
                    <li key={`${m.mois}-${e.mission_id}-${idx}`}>
                      <button
                        type="button"
                        className="ctrale-row"
                        title={
                          e.mission_id
                            ? `Ouvrir la mission #${e.mission_id} · ${e.client}`
                            : e.client
                        }
                        disabled={!e.mission_id}
                        onClick={() => {
                          if (e.mission_id) onOuvrirMission(e.mission_id);
                        }}
                      >
                        <span className="ctrale-ligne">
                          <span className="ctrale-meta">
                            {dateFr(e.date)}
                          </span>
                          <span className="ctrale-type">
                            {LIBELLES_TYPE[e.type] ?? e.type}
                          </span>
                          <span className="ctrale-libelle">
                            {e.client ? `${e.client} · ` : ""}
                            {e.libelle}
                          </span>
                          {e.depassee && (
                            <span className="calcab-badge-depassee">
                              date passée — à reprogrammer si besoin
                            </span>
                          )}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}

            {vue.note && <p className="ctrale-note">{vue.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}
