import { useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Pilotage de mission (GET /missions/{id}/pilotage) — synthèses agrégées. */
type PhasePilotage = {
  phase: string;
  faites: number;
  total: number;
  avancement_pct: string;
};

type PilotageOut = {
  mission: {
    id: number;
    exercice: number;
    statut: string;
    contribuable: string;
  };
  programme: {
    synthese: { faites: number; total: number; avancement_pct: string };
    phases: PhasePilotage[];
  };
  controle_cloture: {
    synthese: { ok: number; attention: number; bloquant: number };
    cloture_recommandee: boolean;
  };
  temps: { total_heures: string; par_phase: Record<string, string> };
  rentabilite: {
    honoraires: string | null;
    cout_estime: string | null;
    marge_estimee: string | null;
    taux_marge_pct: string | null;
  } | null;
  visas: { phases_completes: number; total_visas: number };
  derniere_execution: {
    execution_id: number;
    conclusions_par_statut: Record<string, number>;
    total_conclusions: number;
  } | null;
};

const LIBELLES_STATUT_CONCLUSION: Record<string, string> = {
  conforme: "Conformes",
  anomalie: "Anomalies",
  sous_seuil: "Sous seuil",
  non_verifiable: "Non vérifiables",
  hors_perimetre: "Hors périmètre",
};

function libelleStatutConclusion(statut: string): string {
  return LIBELLES_STATUT_CONCLUSION[statut] ?? statut;
}

type Props = {
  missionId: number;
  jeton?: string | null;
  onFermer: () => void;
};

export function PilotageVue({ missionId, jeton, onFermer }: Props) {
  const [etat, setEtat] = useState<PilotageOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!jeton || !missionId) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<PilotageOut>(
          `/api/v1/missions/${missionId}/pilotage`,
          { jeton },
        );
        if (!annule) setEtat(out ?? null);
      } catch (e) {
        if (!annule) {
          setEtat(null);
          setErr(
            e instanceof Error ? e.message : "pilotage de mission indisponible",
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

  return (
    <section className="rest-suivi rest-pilotage" aria-label="Pilotage">
      <div className="rest-suivi-head">
        <h3 className="rest-suivi-titre label-with-tip">
          Pilotage
          <InfoTip
            label="Synthèse transverse de la mission pour le chef de mission et l'associé : avancement du programme, contrôle de pré-clôture, temps passés, rentabilité, visas et conclusions de la dernière exécution — agrégation déterministe des modules existants."
            ariaLabel="Aide : pilotage de mission"
          />
        </h3>
        <div className="rest-suivi-outils">
          {etat && (
            <span className="muted">
              {etat.mission.contribuable} · Exercice {etat.mission.exercice} ·{" "}
              {etat.mission.statut}
            </span>
          )}
          <button type="button" className="btn btn-ghost btn-sm" onClick={onFermer}>
            Fermer
          </button>
        </div>
      </div>
      {busy && <p className="muted">Chargement du pilotage…</p>}
      {err && (
        <p className="rest-lettre-err" role="alert">
          Pilotage indisponible : {err}
        </p>
      )}
      {etat && (
        <ul className="rest-suivi-items rest-pilotage-items">
          <li className="rest-suivi-item">
            <div className="rest-suivi-libelle">
              <span className="rest-suivi-cle">Programme de travail</span>
              <span>
                {etat.programme.synthese.faites}/{etat.programme.synthese.total}{" "}
                diligences faites ({etat.programme.synthese.avancement_pct} %)
              </span>
              <span className="muted">
                {etat.programme.phases
                  .map((p) => `${p.phase} : ${p.faites}/${p.total}`)
                  .join(" · ")}
              </span>
            </div>
          </li>
          <li className="rest-suivi-item">
            <div className="rest-suivi-libelle">
              <span className="rest-suivi-cle">Contrôle de pré-clôture</span>
              <span>
                {etat.controle_cloture.synthese.ok} OK ·{" "}
                {etat.controle_cloture.synthese.attention} attention ·{" "}
                {etat.controle_cloture.synthese.bloquant} bloquant
                {etat.controle_cloture.synthese.bloquant > 1 ? "s" : ""}
              </span>
              <span className="muted">
                {etat.controle_cloture.cloture_recommandee
                  ? "Clôture recommandée"
                  : "Clôture non recommandée"}
              </span>
            </div>
          </li>
          <li className="rest-suivi-item">
            <div className="rest-suivi-libelle">
              <span className="rest-suivi-cle">Temps passés</span>
              <span>{etat.temps.total_heures} h au total</span>
              {Object.keys(etat.temps.par_phase).length > 0 && (
                <span className="muted">
                  {Object.entries(etat.temps.par_phase)
                    .map(([phase, h]) => `${phase} : ${h} h`)
                    .join(" · ")}
                </span>
              )}
            </div>
          </li>
          <li className="rest-suivi-item">
            <div className="rest-suivi-libelle">
              <span className="rest-suivi-cle">Rentabilité</span>
              {etat.rentabilite ? (
                <>
                  <span>
                    {etat.rentabilite.marge_estimee !== null
                      ? `Marge estimée ${fmtMontant(
                          etat.rentabilite.marge_estimee,
                        )} FCFA`
                      : "Marge non calculable"}
                    {etat.rentabilite.taux_marge_pct !== null
                      ? ` (${etat.rentabilite.taux_marge_pct} %)`
                      : ""}
                  </span>
                  <span className="muted">
                    {[
                      etat.rentabilite.honoraires !== null
                        ? `honoraires ${fmtMontant(
                            etat.rentabilite.honoraires,
                          )} FCFA`
                        : null,
                      etat.rentabilite.cout_estime !== null
                        ? `coût estimé ${fmtMontant(
                            etat.rentabilite.cout_estime,
                          )} FCFA`
                        : null,
                    ]
                      .filter((x) => x !== null)
                      .join(" · ")}
                  </span>
                </>
              ) : (
                <span className="muted">
                  Paramètres non renseignés (honoraires, taux horaire).
                </span>
              )}
            </div>
          </li>
          <li className="rest-suivi-item">
            <div className="rest-suivi-libelle">
              <span className="rest-suivi-cle">Visas de supervision</span>
              <span>
                {etat.visas.phases_completes} phase
                {etat.visas.phases_completes > 1 ? "s" : ""} complète
                {etat.visas.phases_completes > 1 ? "s" : ""} ·{" "}
                {etat.visas.total_visas} visa
                {etat.visas.total_visas > 1 ? "s" : ""} posé
                {etat.visas.total_visas > 1 ? "s" : ""}
              </span>
            </div>
          </li>
          <li className="rest-suivi-item">
            <div className="rest-suivi-libelle">
              <span className="rest-suivi-cle">Dernière exécution</span>
              {etat.derniere_execution ? (
                <span>
                  {Object.entries(
                    etat.derniere_execution.conclusions_par_statut,
                  )
                    .map(
                      ([statut, n]) =>
                        `${libelleStatutConclusion(statut)} : ${n}`,
                    )
                    .join(" · ") ||
                    "Aucune conclusion produite"}
                </span>
              ) : (
                <span className="muted">Aucune exécution lancée.</span>
              )}
            </div>
          </li>
        </ul>
      )}
    </section>
  );
}
