import { useEffect, useState } from "react";
import { api, fmtMontant } from "./api";

/** Suivi budgétaire des missions (GET /api/v1/cabinet/rentabilite). */
type ItemRentabilite = {
  mission_id: number;
  client: string;
  exercice: number;
  total_heures: string;
  honoraires: string | null;
  cout_estime: string | null;
  pourcentage_consomme: string | null;
  seuil: string | null;
};

type RentabiliteCabinetOut = {
  items: ItemRentabilite[];
  synthese: {
    missions_suivies: number;
    en_vigilance: number;
    en_depassement: number;
  };
  note: string;
};

type Props = {
  jeton?: string | null;
  onOuvrirMission: (missionId: number) => void;
};

/** « 112.5 » → « 112,5 % consommé » (affichage FR). */
function fmtPct(pct: string | null): string {
  return pct == null ? "—" : `${pct.replace(".", ",")} % consommé`;
}

export function RentabiliteCabinetVue({ jeton, onOuvrirMission }: Props) {
  const [suivi, setSuivi] = useState<RentabiliteCabinetOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!jeton) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<RentabiliteCabinetOut>(
          "/api/v1/cabinet/rentabilite",
          { jeton },
        );
        if (!annule) setSuivi(out ?? null);
      } catch {
        if (!annule) {
          setSuivi(null);
          setErr("Suivi budgétaire indisponible pour le moment.");
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
      className="rentacab-zone"
      aria-label="Suivi budgétaire des missions"
    >
      <div className="rentacab-head">
        <div>
          <h3 className="rentacab-title">Suivi budgétaire des missions</h3>
          <p className="rentacab-sub">
            Missions en cours dont le budget temps est sous tension
            (honoraires consommés à 80 % et plus).
          </p>
        </div>
      </div>

      <article className="panel dense rentacab-card">
        {busy && !suivi && (
          <p className="rentacab-vide">Chargement du suivi budgétaire…</p>
        )}
        {err && !busy && <p className="rentacab-err">{err}</p>}

        {suivi && (
          <>
            <div className="rentacab-synthese">
              <span className="rentacab-chip">
                <strong>{suivi.synthese.missions_suivies}</strong> mission
                {suivi.synthese.missions_suivies > 1 ? "s" : ""} suivie
                {suivi.synthese.missions_suivies > 1 ? "s" : ""}
              </span>
              <span
                className={`rentacab-chip${
                  suivi.synthese.en_vigilance > 0 ? " vigilance" : ""
                }`}
              >
                <strong>{suivi.synthese.en_vigilance}</strong> en vigilance
              </span>
              <span
                className={`rentacab-chip${
                  suivi.synthese.en_depassement > 0 ? " depassement" : ""
                }`}
              >
                <strong>{suivi.synthese.en_depassement}</strong> en dépassement
              </span>
            </div>

            {!suivi.items.length && (
              <p className="rentacab-vide">
                Aucune mission sous tension budgétaire.
              </p>
            )}

            {suivi.items.length > 0 && (
              <ul className="rentacab-liste">
                {suivi.items.map((it) => (
                  <li key={it.mission_id}>
                    <button
                      type="button"
                      className="rentacab-row"
                      title={`Ouvrir la mission #${it.mission_id} · ${it.client}`}
                      onClick={() => onOuvrirMission(it.mission_id)}
                    >
                      <span className="rentacab-libelle">
                        {it.client} · exercice {it.exercice}
                      </span>
                      <span className="rentacab-meta">
                        {it.total_heures} h ·{" "}
                        {it.cout_estime != null
                          ? `${fmtMontant(it.cout_estime)} FCFA consommés`
                          : "—"}
                        {it.honoraires != null
                          ? ` sur ${fmtMontant(it.honoraires)} FCFA`
                          : ""}
                      </span>
                      <span
                        className={`rentacab-badge ${
                          it.seuil === "depassement"
                            ? "depassement"
                            : "vigilance"
                        }`}
                      >
                        {fmtPct(it.pourcentage_consomme)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {suivi.note && <p className="rentacab-note">{suivi.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}
