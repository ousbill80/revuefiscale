import { useEffect, useState } from "react";
import { api } from "./api";
import { InfoTip } from "./Tooltip";

/** Fil conducteur de la mission (GET /missions/{id}/fil-conducteur). */

type StatutEtape = "faite" | "en_cours" | "a_faire" | "indisponible";

type EtapeFil = {
  code: string;
  libelle: string;
  statut: StatutEtape;
  detail: string;
};

type FilOut = {
  mission_id: number;
  etapes: EtapeFil[];
  synthese: {
    faites: number;
    total: number;
    prochaine_etape: { code: string; libelle: string } | null;
  };
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
  /** Scroll vers les volets fiscaux (étape « revues »). */
  onAllerVoletsFiscaux?: () => void;
};

const LIBELLES_STATUT: Record<StatutEtape, string> = {
  faite: "Faite",
  en_cours: "En cours",
  a_faire: "À faire",
  indisponible: "Indisponible",
};

const CLASSE_STATUT: Record<StatutEtape, string> = {
  faite: "badge-traitement badge-traitement--conforme",
  en_cours: "badge-traitement badge-traitement--en_cours",
  a_faire: "badge-traitement badge-traitement--a_faire",
  indisponible: "badge-traitement",
};

function lireDeplie(missionId: number): boolean {
  try {
    return sessionStorage.getItem(`fil-conducteur-${missionId}`) === "1";
  } catch {
    return false;
  }
}

function ecrireDeplie(missionId: number, deplie: boolean) {
  try {
    sessionStorage.setItem(`fil-conducteur-${missionId}`, deplie ? "1" : "0");
  } catch {
    /* ignore */
  }
}

export function FilConducteurVue({
  missionId,
  jeton,
  onAllerVoletsFiscaux,
}: Props) {
  const [etat, setEtat] = useState<FilOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deplie, setDeplie] = useState(() => lireDeplie(missionId));
  const [modeListe, setModeListe] = useState(true);

  useEffect(() => {
    setDeplie(lireDeplie(missionId));
  }, [missionId]);

  useEffect(() => {
    if (!jeton || !missionId) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<FilOut>(
          `/api/v1/missions/${missionId}/fil-conducteur`,
          { jeton },
        );
        if (!annule) setEtat(out ?? null);
      } catch (e) {
        if (!annule) {
          setEtat(null);
          setErr(
            e instanceof Error ? e.message : "fil conducteur indisponible",
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

  function basculerDeplie() {
    setDeplie((v) => {
      const next = !v;
      ecrireDeplie(missionId, next);
      return next;
    });
  }

  const resumeProchaine = etat?.synthese.prochaine_etape
    ? etat.synthese.prochaine_etape.libelle
    : etat
      ? "Toutes les étapes sont faites"
      : null;

  return (
    <section
      className="rest-suivi fil-conducteur fil-conducteur-compact"
      aria-label="Fil conducteur de la mission"
    >
      <div className="fil-conducteur-bar">
        <button
          type="button"
          className="fil-conducteur-toggle"
          aria-expanded={deplie}
          aria-controls={`fil-conducteur-corps-${missionId}`}
          onClick={basculerDeplie}
        >
          <span className="fil-conducteur-chevron" aria-hidden="true">
            {deplie ? "▾" : "▸"}
          </span>
          <span className="fil-conducteur-resume">
            <span className="label-with-tip fil-conducteur-titre-inline">
              Fil conducteur
              <InfoTip
                label="Guide consultatif du process de revue : l'état de chaque étape est dérivé des modules existants. Rien n'est imposé : vous décidez de l'ordre réel de vos travaux."
                ariaLabel="Aide : fil conducteur de la mission"
              />
            </span>
            {etat && !busy && (
              <>
                {" · "}
                <strong>
                  {etat.synthese.faites}/{etat.synthese.total}
                </strong>
                {resumeProchaine ? (
                  <>
                    {" · Prochaine étape : "}
                    <strong>{resumeProchaine}</strong>
                  </>
                ) : null}
              </>
            )}
            {busy && <span className="muted"> · Chargement…</span>}
          </span>
        </button>
        {deplie && etat && !busy && (
          <div
            className="fil-conducteur-vue-switch"
            role="group"
            aria-label="Mode d'affichage du fil conducteur"
          >
            <button
              type="button"
              className={`fil-conducteur-vue-btn${modeListe ? " is-active" : ""}`}
              aria-pressed={modeListe}
              onClick={() => setModeListe(true)}
            >
              Liste
            </button>
            <button
              type="button"
              className={`fil-conducteur-vue-btn${!modeListe ? " is-active" : ""}`}
              aria-pressed={!modeListe}
              onClick={() => setModeListe(false)}
            >
              Tableau
            </button>
          </div>
        )}
      </div>

      {err && (
        <p className="rest-lettre-err" role="alert">
          Fil conducteur indisponible : {err}
        </p>
      )}

      {deplie && etat && !busy && (
        <div
          id={`fil-conducteur-corps-${missionId}`}
          className="fil-conducteur-corps"
        >
          {modeListe ? (
            <ol className="delais-liste">
              {etat.etapes.map((e, idx) => (
                <li key={e.code} className="delais-item">
                  <span className="delais-ligne">
                    <span className={CLASSE_STATUT[e.statut]}>
                      {LIBELLES_STATUT[e.statut]}
                    </span>
                    <span
                      className={`delais-libelle${
                        e.statut === "indisponible" ? " delais-absent" : ""
                      }`}
                    >
                      {idx + 1}. {e.libelle}
                      {" — "}
                      <span className="muted">{e.detail}</span>
                    </span>
                    {e.code === "revues" && onAllerVoletsFiscaux ? (
                      <button
                        type="button"
                        className="btn btn-ghost btn-xs fil-conducteur-lien"
                        onClick={onAllerVoletsFiscaux}
                      >
                        Voir les volets
                      </button>
                    ) : null}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <div className="missions-table-wrap">
              <table className="missions-table supervision-table fil-conducteur-table">
                <thead className="missions-thead">
                  <tr>
                    <th>#</th>
                    <th>Étape</th>
                    <th>Statut</th>
                    <th>Détail</th>
                  </tr>
                </thead>
                <tbody>
                  {etat.etapes.map((e, idx) => (
                    <tr key={e.code}>
                      <td>{idx + 1}</td>
                      <td>
                        {e.libelle}
                        {e.code === "revues" && onAllerVoletsFiscaux ? (
                          <button
                            type="button"
                            className="btn btn-ghost btn-xs fil-conducteur-lien"
                            onClick={onAllerVoletsFiscaux}
                          >
                            Volets
                          </button>
                        ) : null}
                      </td>
                      <td>
                        <span className={CLASSE_STATUT[e.statut]}>
                          {LIBELLES_STATUT[e.statut]}
                        </span>
                      </td>
                      <td className="muted">{e.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="delais-note muted">{etat.note}</p>
        </div>
      )}
    </section>
  );
}
