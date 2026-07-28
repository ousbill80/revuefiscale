import { useEffect, useState } from "react";
import { api, telecharger } from "./api";

/** Points convenus en attente (GET /api/v1/cabinet/points-convenus). */
type ItemPointConvenu = {
  client: string;
  mission_id: number;
  exercice: number;
  statut_mission: string;
  point_id: number;
  libelle: string;
  date_cible: string | null;
  en_retard: boolean;
  anciennete_jours: number;
  cree_le: string | null;
};

type PointsConvenusCabinetOut = {
  aujourd_hui: string;
  items: ItemPointConvenu[];
  synthese: {
    total: number;
    anciens_30j: number;
    clients: number;
    en_retard?: number;
  };
  note: string;
};

type Props = {
  jeton?: string | null;
  onOuvrirMission: (missionId: number) => void;
};

function anciennete(jours: number): string {
  if (jours === 0) return "aujourd'hui";
  return jours === 1 ? "depuis 1 j" : `depuis ${jours} j`;
}

export function PointsConvenusCabinetVue({ jeton, onOuvrirMission }: Props) {
  const [vue, setVue] = useState<PointsConvenusCabinetOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [exportCsvBusy, setExportCsvBusy] = useState(false);

  async function exporterCsv() {
    if (!jeton || exportCsvBusy) return;
    setExportCsvBusy(true);
    setErr(null);
    try {
      await telecharger(
        "/api/v1/cabinet/points-convenus.csv",
        jeton,
        "points-convenus.csv",
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
        const out = await api<PointsConvenusCabinetOut>(
          "/api/v1/cabinet/points-convenus",
          { jeton },
        );
        if (!annule) setVue(out ?? null);
      } catch {
        if (!annule) {
          setVue(null);
          setErr("Points convenus indisponibles pour le moment.");
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
      className="pconvcab-zone"
      aria-label="Points convenus en attente"
    >
      <div className="pconvcab-head">
        <div>
          <h3 className="pconvcab-title">Points convenus en attente</h3>
          <p className="pconvcab-sub">
            Points encore « à faire » de tous les clients (missions en
            cours ou clôturées), du plus ancien au plus récent — pour
            relancer sans ouvrir chaque mission.
          </p>
        </div>
        <button
          type="button"
          className="agenda2-pastille"
          title="Télécharger les points convenus en attente au format CSV (Excel)"
          disabled={exportCsvBusy || !vue?.synthese.total}
          onClick={() => void exporterCsv()}
        >
          {exportCsvBusy ? "Export…" : "Exporter (.csv)"}
        </button>
      </div>

      <article className="panel dense pconvcab-card">
        {busy && !vue && (
          <p className="pconvcab-vide">Chargement des points convenus…</p>
        )}
        {err && !busy && <p className="pconvcab-err">{err}</p>}

        {vue && (
          <>
            <div className="pconvcab-synthese">
              <span className="pconvcab-chip">
                <strong>{vue.synthese.total}</strong> point
                {vue.synthese.total > 1 ? "s" : ""} à faire
              </span>
              <span
                className={`pconvcab-chip${
                  vue.synthese.anciens_30j > 0 ? " ancienne" : ""
                }`}
              >
                <strong>{vue.synthese.anciens_30j}</strong> depuis plus
                de 30 j
              </span>
              <span className="pconvcab-chip">
                <strong>{vue.synthese.clients}</strong> client
                {vue.synthese.clients > 1 ? "s" : ""} concerné
                {vue.synthese.clients > 1 ? "s" : ""}
              </span>
              {(vue.synthese.en_retard ?? 0) > 0 && (
                <span className="pconvcab-chip ancienne">
                  <strong>{vue.synthese.en_retard}</strong> date
                  {(vue.synthese.en_retard ?? 0) > 1 ? "s" : ""} cible
                  {(vue.synthese.en_retard ?? 0) > 1 ? "s" : ""} dépassée
                  {(vue.synthese.en_retard ?? 0) > 1 ? "s" : ""}
                </span>
              )}
            </div>

            {!vue.items.length && (
              <p className="pconvcab-vide">
                Aucun point convenu en attente : tous les points suivis
                sont traités ou abandonnés.
              </p>
            )}

            {vue.items.length > 0 && (
              <ul className="pconvcab-liste">
                {vue.items.map((it) => (
                  <li key={it.point_id}>
                    <button
                      type="button"
                      className="pconvcab-row"
                      title={`Ouvrir la mission #${it.mission_id} · ${it.client}`}
                      onClick={() => onOuvrirMission(it.mission_id)}
                    >
                      <span className="pconvcab-ligne">
                        <span
                          className={`pconvcab-badge${
                            it.anciennete_jours > 30 ? " ancienne" : ""
                          }`}
                        >
                          {anciennete(it.anciennete_jours)}
                        </span>
                        <span className="pconvcab-libelle">
                          {it.client} · exercice {it.exercice}
                        </span>
                        <span className="pconvcab-meta">{it.libelle}</span>
                        {it.date_cible && (
                          <span className="pconvcab-cible">
                            cible {it.date_cible}
                          </span>
                        )}
                        {it.en_retard && (
                          <span className="pconvcab-badge pconvcab-badge-retard">
                            En retard
                          </span>
                        )}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {vue.note && <p className="pconvcab-note">{vue.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}
