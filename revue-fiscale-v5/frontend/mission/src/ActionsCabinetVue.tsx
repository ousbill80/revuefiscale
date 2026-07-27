import { useEffect, useState } from "react";
import { api, fmtMontant, telecharger } from "./api";

/** Actions à mettre en œuvre du cabinet (GET /api/v1/cabinet/actions-retenues). */
type ItemAction = {
  mission_id: number;
  client: string;
  exercice: number;
  cle_action: string;
  libelle_risque: string;
  impot: string;
  exposition: string | null;
  risque_clos: boolean;
  decision_note: string | null;
  maj_le: string | null;
};

type ActionsCabinetOut = {
  total: number;
  synthese: {
    total: number;
    clients: number;
    exposition_totale: string;
  };
  items: ItemAction[];
  note: string;
};

type Props = {
  jeton?: string | null;
  estLecteur?: boolean;
  onOuvrirMission: (missionId: number) => void;
};

export function ActionsCabinetVue({ jeton, estLecteur, onOuvrirMission }: Props) {
  const [actions, setActions] = useState<ActionsCabinetOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Rechargement après « Marquer faite » (clic explicite du fiscaliste).
  const [version, setVersion] = useState(0);
  const [faiteBusy, setFaiteBusy] = useState<string | null>(null);
  const [faiteErr, setFaiteErr] = useState<string | null>(null);
  const [exportCsvBusy, setExportCsvBusy] = useState(false);

  async function exporterCsv() {
    if (!jeton || exportCsvBusy) return;
    setExportCsvBusy(true);
    setErr(null);
    try {
      await telecharger(
        "/api/v1/cabinet/actions-retenues.csv",
        jeton,
        "actions-retenues.csv",
      );
    } catch {
      setErr("Export du tableur impossible pour le moment.");
    } finally {
      setExportCsvBusy(false);
    }
  }

  useEffect(() => {
    if (!jeton) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<ActionsCabinetOut>(
          "/api/v1/cabinet/actions-retenues",
          { jeton },
        );
        if (!annule) setActions(out ?? null);
      } catch {
        if (!annule) {
          setActions(null);
          setErr("Actions indisponibles pour le moment.");
        }
      } finally {
        if (!annule) setBusy(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, [jeton, version]);

  /** Marque l'action « faite » (POST explicite) puis recharge le bloc. */
  async function marquerFaite(it: ItemAction) {
    if (!jeton) return;
    const cle = `${it.mission_id}:${it.cle_action}`;
    setFaiteBusy(cle);
    setFaiteErr(null);
    try {
      await api(
        `/api/v1/missions/${it.mission_id}/plan-actions/` +
          `${encodeURIComponent(it.cle_action)}/decision`,
        {
          method: "POST",
          jeton,
          json: { decision: "faite", note: it.decision_note ?? "" },
        },
      );
      setVersion((v) => v + 1);
    } catch (e) {
      setFaiteErr(
        e instanceof Error
          ? e.message
          : "Impossible de marquer l'action faite.",
      );
    } finally {
      setFaiteBusy(null);
    }
  }

  return (
    <section className="actionscab-zone" aria-label="Actions à mettre en œuvre">
      <div className="actionscab-head">
        <div>
          <h3 className="actionscab-title">Actions à mettre en œuvre</h3>
          <p className="actionscab-sub">
            Actions du plan d'actions retenues et non encore faites, tous
            clients confondus.
          </p>
        </div>
        <button
          type="button"
          className="agenda2-pastille"
          title="Télécharger les actions retenues au format CSV (Excel)"
          disabled={exportCsvBusy || !actions?.total}
          onClick={() => void exporterCsv()}
        >
          {exportCsvBusy ? "Export…" : "Exporter (.csv)"}
        </button>
      </div>

      <article className="panel dense actionscab-card">
        {busy && !actions && (
          <p className="actionscab-vide">Chargement des actions…</p>
        )}
        {err && !busy && <p className="actionscab-err">{err}</p>}

        {actions && (
          <>
            <div className="actionscab-synthese">
              <span
                className={`actionscab-chip${
                  actions.synthese.total > 0 ? " alerte" : ""
                }`}
              >
                <strong>{actions.synthese.total}</strong> action
                {actions.synthese.total > 1 ? "s" : ""}
              </span>
              <span className="actionscab-chip">
                <strong>{actions.synthese.clients}</strong> client
                {actions.synthese.clients > 1 ? "s" : ""}
              </span>
              {actions.synthese.total > 0 && (
                <span className="actionscab-chip exposition">
                  Exposition totale :{" "}
                  {fmtMontant(actions.synthese.exposition_totale)} FCFA
                </span>
              )}
            </div>

            {!actions.items.length && (
              <p className="actionscab-vide">
                Aucune action retenue en attente de mise en œuvre.
              </p>
            )}

            {actions.items.length > 0 && (
              <ul className="actionscab-liste">
                {actions.items.map((it, i) => (
                  <li key={`${it.mission_id}-${it.cle_action}-${i}`}>
                    <button
                      type="button"
                      className="actionscab-row"
                      title={`Ouvrir la mission #${it.mission_id} · ${it.client}`}
                      onClick={() => onOuvrirMission(it.mission_id)}
                    >
                      <span className="actionscab-libelle">
                        {it.libelle_risque || it.cle_action}
                        {it.impot ? ` (${it.impot})` : ""}
                      </span>
                      <span className="actionscab-meta">
                        {it.client} · exercice {it.exercice}
                        {it.exposition != null
                          ? ` · ${fmtMontant(it.exposition)} FCFA`
                          : ""}
                        {it.risque_clos ? " · risque clos depuis" : ""}
                        {it.decision_note ? ` · ${it.decision_note}` : ""}
                      </span>
                      <span className="actionscab-badge">Retenue</span>
                    </button>
                    {!estLecteur && (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm actionscab-faite"
                        title="Marquer cette action comme faite — la décision est enregistrée et la ligne quitte la liste"
                        disabled={
                          !jeton ||
                          busy ||
                          faiteBusy === `${it.mission_id}:${it.cle_action}`
                        }
                        onClick={() => void marquerFaite(it)}
                      >
                        Marquer faite
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}

            {faiteErr && (
              <p className="actionscab-err" role="alert">
                {faiteErr}
              </p>
            )}

            {actions.note && <p className="actionscab-note">{actions.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}
