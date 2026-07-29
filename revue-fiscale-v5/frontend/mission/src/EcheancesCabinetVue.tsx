import { useEffect, useState } from "react";
import { api, telecharger } from "./api";

/** Échéances fiscales à venir (GET /api/v1/cabinet/echeances). */
type ItemEcheance = {
  client: string;
  mission_id: number;
  exercice: number;
  impot: string;
  obligation: string;
  periode: string;
  date_limite: string;
  jours_restants: number;
};

type EcheancesCabinetOut = {
  aujourd_hui: string;
  items: ItemEcheance[];
  synthese: {
    total: number;
    cette_semaine: number;
    clients: number;
  };
  note: string;
};

type Props = {
  jeton?: string | null;
  onOuvrirMission: (missionId: number) => void;
};

function dateFr(iso: string): string {
  const [a, m, j] = iso.split("-");
  return a && m && j ? `${j}/${m}/${a}` : iso;
}

export function EcheancesCabinetVue({ jeton, onOuvrirMission }: Props) {
  const [vue, setVue] = useState<EcheancesCabinetOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [exportCsvBusy, setExportCsvBusy] = useState(false);

  async function exporterCsv() {
    if (!jeton || exportCsvBusy) return;
    setExportCsvBusy(true);
    setErr(null);
    try {
      await telecharger(
        "/api/v1/cabinet/echeances.csv",
        jeton,
        "echeances-fiscales.csv",
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
        const out = await api<EcheancesCabinetOut>(
          "/api/v1/cabinet/echeances",
          { jeton },
        );
        if (!annule) setVue(out ?? null);
      } catch {
        if (!annule) {
          setVue(null);
          setErr("Échéances fiscales indisponibles pour le moment.");
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
    <section
      className="echcab-zone"
      aria-label="Échéances fiscales à venir"
    >
      <div className="echcab-head">
        <div>
          <h3 className="echcab-title">
            Échéances fiscales à venir (30 jours)
          </h3>
          <p className="echcab-sub">
            Dates limites indicatives des 30 prochains jours pour les
            clients en mission — pour anticiper les déclarations.
          </p>
        </div>
        <button
          type="button"
          className="agenda2-pastille"
          title="Télécharger les échéances fiscales au format CSV (Excel)"
          disabled={exportCsvBusy || !vue?.synthese.total}
          onClick={() => void exporterCsv()}
        >
          {exportCsvBusy ? "Export…" : "Exporter (.csv)"}
        </button>
      </div>

      <article className="panel dense echcab-card">
        {busy && !vue && (
          <p className="echcab-vide">Chargement des échéances fiscales…</p>
        )}
        {err && !busy && <p className="echcab-err">{err}</p>}

        {vue && (
          <>
            <div className="echcab-synthese">
              <span className="echcab-chip">
                <strong>{vue.synthese.total}</strong> échéance
                {vue.synthese.total > 1 ? "s" : ""} à venir
              </span>
              <span
                className={`echcab-chip${
                  vue.synthese.cette_semaine > 0 ? " urgente" : ""
                }`}
              >
                <strong>{vue.synthese.cette_semaine}</strong> cette
                semaine
              </span>
              <span className="echcab-chip">
                <strong>{vue.synthese.clients}</strong> client
                {vue.synthese.clients > 1 ? "s" : ""} concerné
                {vue.synthese.clients > 1 ? "s" : ""}
              </span>
            </div>

            {!vue.items.length && (
              <p className="echcab-vide">
                Aucune échéance. Rien à préparer dans les 30 prochains
                jours pour les missions en cours.
              </p>
            )}

            {vue.items.length > 0 && (
              <ul className="echcab-liste">
                {vue.items.map((it, idx) => (
                  <li key={`${it.mission_id}-${it.date_limite}-${idx}`}>
                    <button
                      type="button"
                      className="echcab-row"
                      title={`Ouvrir la mission #${it.mission_id} · ${it.client}`}
                      onClick={() => onOuvrirMission(it.mission_id)}
                    >
                      <span className="echcab-ligne">
                        <span
                          className={`echcab-badge${
                            it.jours_restants <= 7 ? " urgente" : ""
                          }`}
                        >
                          {dateFr(it.date_limite)} ·{" "}
                          {it.jours_restants === 0
                            ? "aujourd'hui"
                            : `dans ${it.jours_restants} j`}
                        </span>
                        <span className="echcab-libelle">
                          {it.client} · {it.impot}
                        </span>
                        <span className="echcab-meta">
                          {it.obligation} — {it.periode}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {vue.note && <p className="echcab-note">{vue.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}
