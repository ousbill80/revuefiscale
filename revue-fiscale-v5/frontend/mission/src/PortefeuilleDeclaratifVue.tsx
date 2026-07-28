import { useEffect, useState } from "react";
import { api } from "./api";

/** Suivi déclaratif du portefeuille (GET /api/v1/cabinet/portefeuille-declaratif). */
type BlocImpot = {
  disponible: boolean;
  saisies: number;
  attendues: number;
  manquantes: string[];
};

type MissionPortefeuille = {
  client: string;
  mission_id: number | null;
  exercice: number | null;
  tva: BlocImpot;
  salaires: BlocImpot;
  statut: string;
};

type PortefeuilleOut = {
  aujourd_hui: string;
  missions: MissionPortefeuille[];
  synthese: {
    nb_missions: number;
    nb_a_jour: number;
    nb_a_completer: number;
    nb_indisponibles: number;
  };
  note: string;
};

type Props = {
  jeton?: string | null;
  onOuvrirMission: (missionId: number) => void;
};

const LIBELLES_STATUT: Record<string, string> = {
  a_completer: "périodes à saisir",
  a_jour: "à jour",
  indisponible: "indisponible",
};

const MOIS_ABREGES = [
  "janv.", "févr.", "mars", "avr.", "mai", "juin",
  "juil.", "août", "sept.", "oct.", "nov.", "déc.",
] as const;

/** « 2025-01 » → « janv. » ; valeur illisible → inchangée. */
function moisAbrege(periode: string): string {
  const numero = Number(periode.slice(5, 7));
  return MOIS_ABREGES[numero - 1] ?? periode;
}

/** Périodes manquantes compactes : « janv., févr. + 3 autres ». */
function periodesCompactes(manquantes: string[]): string {
  if (!manquantes.length) return "—";
  const tetes = manquantes.slice(0, 2).map(moisAbrege).join(", ");
  const reste = manquantes.length - 2;
  return reste > 0
    ? `${tetes} + ${reste} autre${reste > 1 ? "s" : ""}`
    : tetes;
}

/** Cellule d'un impôt : « 2/12 · janv., févr. + 3 autres ». */
function celluleBloc(bloc: BlocImpot): string {
  if (!bloc.disponible) return "indisponible";
  if (!bloc.attendues) return "aucune période échue";
  return `${bloc.attendues - bloc.manquantes.length}/${bloc.attendues}${
    bloc.manquantes.length
      ? ` · à saisir : ${periodesCompactes(bloc.manquantes)}`
      : ""
  }`;
}

export function PortefeuilleDeclaratifVue({ jeton, onOuvrirMission }: Props) {
  const [vue, setVue] = useState<PortefeuilleOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!jeton) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<PortefeuilleOut>(
          "/api/v1/cabinet/portefeuille-declaratif",
          { jeton },
        );
        if (!annule) setVue(out ?? null);
      } catch {
        if (!annule) {
          setVue(null);
          setErr("Suivi déclaratif indisponible pour le moment.");
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
      className="ctrale-zone"
      aria-label="Suivi déclaratif du portefeuille"
    >
      <div className="ctrale-head">
        <div>
          <h3 className="ctrale-title">Suivi déclaratif du portefeuille</h3>
          <p className="ctrale-sub">
            Pour chaque mission en cours, les périodes déclaratives saisies
            et celles restant à saisir (TVA, impôts sur salaires) — pour
            prioriser la collecte des pièces avec chaque client.
          </p>
        </div>
      </div>

      <article className="panel dense ctrale-card">
        {busy && !vue && (
          <p className="ctrale-vide">Chargement du suivi déclaratif…</p>
        )}
        {err && !busy && <p className="ctrale-err">{err}</p>}

        {vue && (
          <>
            <div className="ctrale-synthese">
              <span className="ctrale-chip">
                <strong>{vue.synthese.nb_missions}</strong> mission
                {vue.synthese.nb_missions > 1 ? "s" : ""} suivie
                {vue.synthese.nb_missions > 1 ? "s" : ""}
              </span>
              {vue.synthese.nb_a_completer > 0 && (
                <span className="ctrale-chip vigilance">
                  <strong>{vue.synthese.nb_a_completer}</strong> avec des
                  périodes à saisir
                </span>
              )}
              <span className="ctrale-chip">
                <strong>{vue.synthese.nb_a_jour}</strong> à jour
              </span>
              {vue.synthese.nb_indisponibles > 0 && (
                <span className="ctrale-chip">
                  <strong>{vue.synthese.nb_indisponibles}</strong>{" "}
                  momentanément indisponible
                  {vue.synthese.nb_indisponibles > 1 ? "s" : ""}
                </span>
              )}
            </div>

            {!vue.missions.length && (
              <p className="ctrale-vide">
                Aucune mission ouverte à suivre pour le moment.
              </p>
            )}

            {vue.missions.length > 0 && (
              <table className="tbl dense">
                <thead>
                  <tr>
                    <th>Client</th>
                    <th>Exercice</th>
                    <th>TVA (saisies/attendues)</th>
                    <th>Salaires (saisies/attendues)</th>
                    <th>État</th>
                  </tr>
                </thead>
                <tbody>
                  {vue.missions.map((m, idx) => (
                    <tr key={`${m.mission_id}-${idx}`}>
                      <td>
                        <button
                          type="button"
                          className="ctrale-row"
                          title={
                            m.mission_id
                              ? `Ouvrir la mission #${m.mission_id} · ${m.client}`
                              : m.client
                          }
                          disabled={!m.mission_id}
                          onClick={() => {
                            if (m.mission_id) onOuvrirMission(m.mission_id);
                          }}
                        >
                          {m.client || "—"}
                        </button>
                      </td>
                      <td>{m.exercice ?? "—"}</td>
                      <td>{celluleBloc(m.tva)}</td>
                      <td>{celluleBloc(m.salaires)}</td>
                      <td>
                        <span
                          className={
                            m.statut === "a_completer"
                              ? "ctrale-chip vigilance"
                              : "ctrale-chip"
                          }
                        >
                          {LIBELLES_STATUT[m.statut] ?? m.statut}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {vue.note && <p className="ctrale-note">{vue.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}
