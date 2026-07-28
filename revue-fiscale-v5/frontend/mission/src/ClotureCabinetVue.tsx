import { useEffect, useState } from "react";
import { api } from "./api";

/** Clôture des missions (GET /api/v1/cabinet/preparation-cloture). */
type ItemPreparation = {
  mission_id: number;
  client: string;
  exercice: number;
  nb_ok: number;
  nb_attention: number;
  prete: boolean;
  points_attention: string[];
};

type PreparationClotureOut = {
  items: ItemPreparation[];
  synthese: {
    en_cours: number;
    pretes: number;
    a_completer: number;
  };
  note: string;
};

type Props = {
  jeton?: string | null;
  onOuvrirMission: (missionId: number) => void;
};

export function ClotureCabinetVue({ jeton, onOuvrirMission }: Props) {
  const [prep, setPrep] = useState<PreparationClotureOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!jeton) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<PreparationClotureOut>(
          "/api/v1/cabinet/preparation-cloture",
          { jeton },
        );
        if (!annule) setPrep(out ?? null);
      } catch {
        if (!annule) {
          setPrep(null);
          setErr("Préparation à la clôture indisponible pour le moment.");
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
      className="cloturecab-zone"
      aria-label="Clôture des missions"
    >
      <div className="cloturecab-head">
        <div>
          <h3 className="cloturecab-title">Clôture des missions</h3>
          <p className="cloturecab-sub">
            État de préparation à la clôture des missions en cours :
            points du bilan au vert et points d&apos;attention restants.
          </p>
        </div>
      </div>

      <article className="panel dense cloturecab-card">
        {busy && !prep && (
          <p className="cloturecab-vide">
            Chargement de la préparation à la clôture…
          </p>
        )}
        {err && !busy && <p className="cloturecab-err">{err}</p>}

        {prep && (
          <>
            <div className="cloturecab-synthese">
              <span className="cloturecab-chip">
                <strong>{prep.synthese.en_cours}</strong> mission
                {prep.synthese.en_cours > 1 ? "s" : ""} en cours
              </span>
              <span
                className={`cloturecab-chip${
                  prep.synthese.pretes > 0 ? " prete" : ""
                }`}
              >
                <strong>{prep.synthese.pretes}</strong> prête
                {prep.synthese.pretes > 1 ? "s" : ""} à clôturer
              </span>
              <span
                className={`cloturecab-chip${
                  prep.synthese.a_completer > 0 ? " attention" : ""
                }`}
              >
                <strong>{prep.synthese.a_completer}</strong> à compléter
              </span>
            </div>

            {!prep.items.length && (
              <p className="cloturecab-vide">
                Aucune mission en cours — rien à préparer pour la clôture.
              </p>
            )}

            {prep.items.length > 0 && (
              <ul className="cloturecab-liste">
                {prep.items.map((it) => (
                  <li key={it.mission_id}>
                    <button
                      type="button"
                      className="cloturecab-row"
                      title={`Ouvrir la mission #${it.mission_id} · ${it.client}`}
                      onClick={() => onOuvrirMission(it.mission_id)}
                    >
                      <span className="cloturecab-ligne">
                        <span className="cloturecab-libelle">
                          {it.client} · exercice {it.exercice}
                        </span>
                        <span className="cloturecab-meta">
                          {it.nb_ok} point{it.nb_ok > 1 ? "s" : ""} au vert
                        </span>
                        <span
                          className={`cloturecab-badge ${
                            it.prete ? "prete" : "attention"
                          }`}
                        >
                          {it.prete
                            ? "Prête à clôturer"
                            : `${it.nb_attention} point${
                                it.nb_attention > 1 ? "s" : ""
                              } d'attention`}
                        </span>
                      </span>
                      {it.points_attention.length > 0 && (
                        <span className="cloturecab-points">
                          {it.points_attention.join(" · ")}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {prep.note && <p className="cloturecab-note">{prep.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}
