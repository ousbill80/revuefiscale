import { useEffect, useMemo, useState } from "react";
import { api, telecharger } from "./api";
import { LIBELLES_IMPOT, type CodeImpotPivot } from "./impotLabels";

/** Agenda fiscal du cabinet (GET /api/v1/cabinet/agenda-fiscal?jours=N). */
type EcheanceAgenda = {
  date_limite: string;
  impot: string;
  obligation: string;
  periode: string;
  mission_id: number;
  client: string;
  statut: "couverte" | "a_preparer";
};

type AgendaFiscalOut = {
  aujourd_hui: string;
  jours: number;
  fenetre_fin: string;
  missions_actives: number;
  echeances: EcheanceAgenda[];
  synthese: {
    total: number;
    a_preparer: number;
    couvertes: number;
    prochaine_echeance: string | null;
  };
  note: string;
};

const FENETRES = [30, 60, 90] as const;

/** Date ISO (aaaa-mm-jj) → jj/mm/aaaa ; valeur inattendue renvoyée telle quelle. */
function fmtDate(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso ?? ""));
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso || "—";
}

/** Groupe les échéances par date limite en conservant l'ordre trié du backend. */
function grouperParDate(
  echeances: EcheanceAgenda[],
): Array<{ date: string; lignes: EcheanceAgenda[] }> {
  const groupes: Array<{ date: string; lignes: EcheanceAgenda[] }> = [];
  const index = new Map<string, number>();
  for (const e of echeances) {
    const i = index.get(e.date_limite);
    if (i === undefined) {
      index.set(e.date_limite, groupes.length);
      groupes.push({ date: e.date_limite, lignes: [e] });
    } else {
      groupes[i].lignes.push(e);
    }
  }
  return groupes;
}

function libelleImpot(code: string): string {
  return (LIBELLES_IMPOT as Record<string, string>)[code as CodeImpotPivot] ?? code;
}

type Props = {
  jeton?: string | null;
  onOuvrirMission: (missionId: number) => void;
};

export function AgendaFiscalVue({ jeton, onOuvrirMission }: Props) {
  const [jours, setJours] = useState<number>(30);
  const [agenda, setAgenda] = useState<AgendaFiscalOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [exportCsvBusy, setExportCsvBusy] = useState(false);

  async function exporterIcs() {
    if (!jeton || exportBusy) return;
    setExportBusy(true);
    setErr(null);
    try {
      await telecharger(
        `/api/v1/cabinet/agenda-fiscal.ics?jours=${jours}`,
        jeton,
        "agenda-fiscal.ics",
      );
    } catch {
      setErr("Export du calendrier impossible pour le moment.");
    } finally {
      setExportBusy(false);
    }
  }

  async function exporterCsv() {
    if (!jeton || exportCsvBusy) return;
    setExportCsvBusy(true);
    setErr(null);
    try {
      await telecharger(
        `/api/v1/cabinet/agenda-fiscal.csv?jours=${jours}`,
        jeton,
        "agenda-fiscal.csv",
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
        const out = await api<AgendaFiscalOut>(
          `/api/v1/cabinet/agenda-fiscal?jours=${jours}`,
          { jeton },
        );
        if (!annule) setAgenda(out ?? null);
      } catch {
        if (!annule) {
          setAgenda(null);
          setErr("Agenda fiscal indisponible pour le moment.");
        }
      } finally {
        if (!annule) setBusy(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, [jeton, jours]);

  const groupes = useMemo(
    () => grouperParDate(agenda?.echeances ?? []),
    [agenda],
  );

  return (
    <section className="agenda2-zone" aria-label="Agenda fiscal du cabinet">
      <div className="agenda2-head">
        <div>
          <h3 className="agenda2-title">Agenda fiscal</h3>
          <p className="agenda2-sub">
            Échéances déclaratives des clients du portefeuille sur la fenêtre
            choisie.
          </p>
        </div>
        <div
          className="agenda2-fenetres"
          role="group"
          aria-label="Fenêtre d'affichage"
        >
          {FENETRES.map((n) => (
            <button
              key={n}
              type="button"
              className={`agenda2-pastille${jours === n ? " active" : ""}`}
              aria-pressed={jours === n}
              onClick={() => setJours(n)}
            >
              {n} j
            </button>
          ))}
          <button
            type="button"
            className="agenda2-pastille"
            title={`Télécharger les échéances (${jours} jours) au format iCalendar`}
            disabled={exportBusy || !agenda?.echeances.length}
            onClick={() => void exporterIcs()}
          >
            {exportBusy ? "Export…" : "Exporter (.ics)"}
          </button>
          <button
            type="button"
            className="agenda2-pastille"
            title={`Télécharger les échéances (${jours} jours) au format CSV (Excel)`}
            disabled={exportCsvBusy || !agenda?.echeances.length}
            onClick={() => void exporterCsv()}
          >
            {exportCsvBusy ? "Export…" : "Exporter (.csv)"}
          </button>
        </div>
      </div>

      <article className="panel dense agenda2-card">
        {busy && !agenda && (
          <p className="agenda2-vide">Chargement de l&apos;agenda…</p>
        )}
        {err && !busy && <p className="agenda2-err">{err}</p>}

        {agenda && (
          <>
            <div className="agenda2-synthese">
              <span className="agenda2-chip">
                <strong>{agenda.synthese.total}</strong> échéance
                {agenda.synthese.total > 1 ? "s" : ""}
              </span>
              <span
                className={`agenda2-chip${
                  agenda.synthese.a_preparer > 0 ? " alerte" : ""
                }`}
              >
                <strong>{agenda.synthese.a_preparer}</strong> à préparer
              </span>
              <span className="agenda2-chip ok">
                <strong>{agenda.synthese.couvertes}</strong> couverte
                {agenda.synthese.couvertes > 1 ? "s" : ""}
              </span>
              {agenda.synthese.prochaine_echeance && (
                <span className="agenda2-chip prochaine">
                  Prochaine : {fmtDate(agenda.synthese.prochaine_echeance)}
                </span>
              )}
            </div>

            {!agenda.echeances.length && (
              <p className="agenda2-vide">
                Aucune échéance dans la fenêtre ({fmtDate(agenda.aujourd_hui)}{" "}
                → {fmtDate(agenda.fenetre_fin)}).
              </p>
            )}

            {groupes.map((g) => (
              <div key={g.date} className="agenda2-groupe">
                <p className="agenda2-date">{fmtDate(g.date)}</p>
                <ul className="agenda2-liste">
                  {g.lignes.map((e, i) => (
                    <li key={`${g.date}-${e.mission_id}-${e.impot}-${i}`}>
                      <button
                        type="button"
                        className="agenda2-row"
                        title={`Ouvrir la mission #${e.mission_id} · ${e.client}`}
                        onClick={() => onOuvrirMission(e.mission_id)}
                      >
                        <span
                          className="agenda2-impot"
                          title={libelleImpot(e.impot)}
                        >
                          {e.impot}
                        </span>
                        <span className="agenda2-obligation">
                          {e.obligation}
                        </span>
                        <span className="agenda2-meta">
                          {e.periode} · {e.client}
                        </span>
                        <span
                          className={`agenda2-badge ${
                            e.statut === "couverte" ? "couverte" : "preparer"
                          }`}
                        >
                          {e.statut === "couverte" ? "Couverte" : "À préparer"}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}

            {agenda.note && <p className="agenda2-note">{agenda.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}
