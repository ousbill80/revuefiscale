import { useEffect, useState } from "react";
import { api } from "./api";
import { REGIMES_FISCAUX } from "./legalite";
import { InfoTip } from "./Tooltip";

/** Échéancier fiscal de la mission (GET /missions/{id}/echeancier-fiscal). */
type EcheanceMission = {
  impot: string;
  obligation: string;
  periode: string;
  date_limite: string;
  base_legale: string;
};

type EcheancierMissionOut = {
  mission_id: number;
  exercice: number;
  regime: string;
  dge: boolean;
  echeances: EcheanceMission[];
  synthese: { total: number; par_impot: Record<string, number> };
};

function libelleRegime(value: string | null | undefined): string {
  if (!value) return "—";
  return REGIMES_FISCAUX.find((r) => r.value === value)?.label ?? value;
}

/** Date ISO (AAAA-MM-JJ) → JJ/MM/AAAA, sans fuseau. */
function formaterDateLimite(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso ?? ""));
  if (!m) return iso || "—";
  return `${m[3]}/${m[2]}/${m[1]}`;
}

/** Groupe les échéances par impôt en conservant l'ordre d'apparition. */
function grouperParImpot(
  echeances: EcheanceMission[],
): Array<{ impot: string; lignes: EcheanceMission[] }> {
  const groupes: Array<{ impot: string; lignes: EcheanceMission[] }> = [];
  const index = new Map<string, number>();
  for (const e of echeances) {
    const i = index.get(e.impot);
    if (i === undefined) {
      index.set(e.impot, groupes.length);
      groupes.push({ impot: e.impot, lignes: [e] });
    } else {
      groupes[i].lignes.push(e);
    }
  }
  return groupes;
}

type Props = {
  missionId: number;
  jeton?: string | null;
  onFermer: () => void;
};

export function EcheancierFiscalVue({ missionId, jeton, onFermer }: Props) {
  const [etat, setEtat] = useState<EcheancierMissionOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!jeton || !missionId) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<EcheancierMissionOut>(
          `/api/v1/missions/${missionId}/echeancier-fiscal`,
          { jeton },
        );
        if (!annule) setEtat(out ?? null);
      } catch (e) {
        if (!annule) {
          setEtat(null);
          setErr(
            e instanceof Error ? e.message : "échéancier fiscal indisponible",
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

  const groupes = etat ? grouperParImpot(etat.echeances) : [];

  return (
    <section
      className="rest-suivi rest-echeancier"
      aria-label="Échéancier fiscal"
    >
      <div className="rest-suivi-head">
        <h3 className="rest-suivi-titre label-with-tip">
          Échéancier fiscal
          <InfoTip
            label="Calendrier déterministe des obligations déclaratives et de paiement de l'exercice revu, selon le régime du profil mission — dates indicatives (pratique déclarative DGI), sans calcul d'impôt."
            ariaLabel="Aide : échéancier fiscal"
          />
        </h3>
        <div className="rest-suivi-outils">
          {etat && (
            <span className="muted">
              Exercice {etat.exercice} · {etat.synthese.total} échéance
              {etat.synthese.total > 1 ? "s" : ""}
            </span>
          )}
          <button type="button" className="btn btn-ghost btn-sm" onClick={onFermer}>
            Fermer
          </button>
        </div>
      </div>
      {busy && <p className="muted">Chargement de l’échéancier…</p>}
      {err && (
        <p className="rest-lettre-err" role="alert">
          Échéancier indisponible : {err}
        </p>
      )}
      {etat && (
        <>
          <p className="muted rest-echeancier-synthese">
            Exercice {etat.exercice} · Régime {libelleRegime(etat.regime)}
            {etat.dge ? " · DGE" : ""} · {etat.synthese.total} échéance
            {etat.synthese.total > 1 ? "s" : ""}
            {Object.keys(etat.synthese.par_impot).length > 0 && (
              <>
                {" — "}
                {Object.entries(etat.synthese.par_impot)
                  .map(([impot, n]) => `${impot} : ${n}`)
                  .join(" · ")}
              </>
            )}
          </p>
          {etat.echeances.length === 0 ? (
            <p className="muted">
              Aucune échéance calculée pour cet exercice et ce régime.
            </p>
          ) : (
            <ul className="rest-suivi-items rest-echeancier-items">
              {groupes.map((g) => (
                <li key={g.impot} className="rest-suivi-item">
                  <div className="rest-suivi-libelle">
                    <span className="rest-suivi-cle">
                      {g.impot}
                      <span className="muted">
                        {" "}
                        — {g.lignes.length} échéance
                        {g.lignes.length > 1 ? "s" : ""}
                      </span>
                    </span>
                    <table className="rest-echeancier-table">
                      <thead>
                        <tr>
                          <th>Obligation</th>
                          <th>Période</th>
                          <th>Date limite</th>
                          <th>Base légale</th>
                        </tr>
                      </thead>
                      <tbody>
                        {g.lignes.map((e, i) => (
                          <tr key={`${e.date_limite}-${i}`}>
                            <td>{e.obligation}</td>
                            <td>{e.periode}</td>
                            <td className="rest-echeancier-date">
                              {formaterDateLimite(e.date_limite)}
                            </td>
                            <td className="muted">{e.base_legale}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
