import { useEffect, useState } from "react";
import { api } from "./api";

/** Centre d'alertes du cabinet (GET /api/v1/cabinet/alertes). */
type Gravite = "critique" | "vigilance" | "info";

type Alerte = {
  type: string;
  gravite: Gravite;
  client: string;
  mission_id: number | null;
  libelle: string;
  echeance: string | null;
  lien: string;
};

type CentreAlertesOut = {
  aujourd_hui: string;
  alertes: Alerte[];
  synthese: {
    total: number;
    par_gravite: Record<string, number>;
    par_type: Record<string, number>;
    clients: number;
  };
  sources_en_echec: string[];
  note: string;
};

type Props = {
  jeton?: string | null;
  onOuvrirMission: (missionId: number) => void;
};

const LIBELLES_TYPE: Record<string, string> = {
  point_convenu: "Point convenu",
  echeance_fiscale: "Échéance fiscale",
  budget_temps: "Budget temps",
  delai_lpf: "Délai LPF",
  completude_declarative: "Complétude déclarative",
  coherence_ca: "Cohérence du chiffre d'affaires",
  deficits_reportables: "Déficits reportables",
  rapprochement_acomptes: "Rapprochement des acomptes IS",
  qualite_balance: "Qualité de balance",
};

const LIBELLES_GRAVITE: Record<Gravite, string> = {
  critique: "Critique",
  vigilance: "Vigilance",
  info: "Info",
};

function dateFr(iso: string): string {
  const [a, m, j] = iso.split("-");
  return a && m && j ? `${j}/${m}/${a}` : iso;
}

export function CentreAlertesVue({ jeton, onOuvrirMission }: Props) {
  const [vue, setVue] = useState<CentreAlertesOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!jeton) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<CentreAlertesOut>("/api/v1/cabinet/alertes", {
          jeton,
        });
        if (!annule) setVue(out ?? null);
      } catch {
        if (!annule) {
          setVue(null);
          setErr("Centre d'alertes indisponible pour le moment.");
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
    <section className="ctrale-zone" aria-label="Centre d'alertes du cabinet">
      <div className="ctrale-head">
        <div>
          <h3 className="ctrale-title">Centre d'alertes</h3>
          <p className="ctrale-sub">
            Tous les signaux du cabinet en une liste : points convenus en
            retard, échéances fiscales proches, budget temps sous tension,
            délais LPF — rien ne part par email, tout reste ici.
          </p>
        </div>
      </div>

      <article className="panel dense ctrale-card">
        {busy && !vue && (
          <p className="ctrale-vide">Chargement des alertes…</p>
        )}
        {err && !busy && <p className="ctrale-err">{err}</p>}

        {vue && (
          <>
            <div className="ctrale-synthese">
              <span className="ctrale-chip critique">
                <strong>{vue.synthese.par_gravite.critique ?? 0}</strong>{" "}
                critique{(vue.synthese.par_gravite.critique ?? 0) > 1 ? "s" : ""}
              </span>
              <span className="ctrale-chip vigilance">
                <strong>{vue.synthese.par_gravite.vigilance ?? 0}</strong>{" "}
                vigilance
              </span>
              <span className="ctrale-chip">
                <strong>{vue.synthese.par_gravite.info ?? 0}</strong> info
              </span>
              <span className="ctrale-chip">
                <strong>{vue.synthese.clients}</strong> client
                {vue.synthese.clients > 1 ? "s" : ""} concerné
                {vue.synthese.clients > 1 ? "s" : ""}
              </span>
              {Object.entries(vue.synthese.par_type)
                .filter(([, n]) => n > 0)
                .map(([t, n]) => (
                  <span key={t} className="ctrale-chip type">
                    {LIBELLES_TYPE[t] ?? t} : <strong>{n}</strong>
                  </span>
                ))}
            </div>

            {vue.sources_en_echec.length > 0 && (
              <p className="ctrale-echec">
                Source{vue.sources_en_echec.length > 1 ? "s" : ""} momentanément
                indisponible{vue.sources_en_echec.length > 1 ? "s" : ""} :{" "}
                {vue.sources_en_echec.join(", ")} — les autres alertes restent
                affichées.
              </p>
            )}

            {!vue.alertes.length && (
              <p className="ctrale-vide">
                Aucune alerte : rien ne réclame votre attention aujourd'hui.
              </p>
            )}

            {vue.alertes.length > 0 && (
              <ul className="ctrale-liste">
                {vue.alertes.map((a, idx) => (
                  <li key={`${a.type}-${a.mission_id}-${idx}`}>
                    <button
                      type="button"
                      className="ctrale-row"
                      title={
                        a.mission_id
                          ? `Ouvrir la mission #${a.mission_id} · ${a.client}`
                          : a.client
                      }
                      disabled={!a.mission_id}
                      onClick={() => {
                        if (a.mission_id) onOuvrirMission(a.mission_id);
                      }}
                    >
                      <span className="ctrale-ligne">
                        <span className={`ctrale-badge ${a.gravite}`}>
                          {LIBELLES_GRAVITE[a.gravite] ?? a.gravite}
                        </span>
                        <span className="ctrale-type">
                          {LIBELLES_TYPE[a.type] ?? a.type}
                        </span>
                        <span className="ctrale-libelle">
                          {a.client ? `${a.client} · ` : ""}
                          {a.libelle}
                        </span>
                        {a.echeance && (
                          <span className="ctrale-meta">
                            échéance {dateFr(a.echeance)}
                          </span>
                        )}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {vue.note && <p className="ctrale-note">{vue.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}
