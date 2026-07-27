import { useEffect, useState } from "react";
import { api, fmtMontant } from "./api";

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
  onOuvrirMission: (missionId: number) => void;
};

export function ActionsCabinetVue({ jeton, onOuvrirMission }: Props) {
  const [actions, setActions] = useState<ActionsCabinetOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

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
  }, [jeton]);

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
                  </li>
                ))}
              </ul>
            )}

            {actions.note && <p className="actionscab-note">{actions.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}
