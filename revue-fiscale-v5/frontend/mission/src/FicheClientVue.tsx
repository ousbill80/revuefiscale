import { useEffect, useState } from "react";
import { api } from "./api";
import { libelleStatut } from "./statuts";

/** Fiche client consolidée (GET /api/v1/contribuables/{id}/fiche). */
type MissionFiche = {
  mission_id: number;
  exercice: number;
  statut: string;
};

type PointOuvert = {
  point_id: number;
  mission_id: number | null;
  exercice: number | null;
  libelle: string;
  date_cible: string | null;
  depassee: boolean;
};

type AlerteFiche = {
  type: string;
  gravite: string;
  client: string;
  mission_id: number | null;
  libelle: string;
  echeance: string | null;
  lien: string;
};

type ExerciceEvolution = {
  exercice: number;
  mission_id: number;
  disponible: boolean;
  total: string | null;
};

type EvolutionFiche = {
  disponible: boolean;
  statut: string;
  exercices: ExerciceEvolution[];
  synthese: { libelle_statut: string };
} | null;

type FicheClientOut = {
  aujourd_hui: string;
  contribuable_id: number;
  denomination: string;
  forme: string | null;
  missions: MissionFiche[];
  points_ouverts: PointOuvert[];
  evolution_charge_fiscale: EvolutionFiche;
  alertes: AlerteFiche[];
  synthese: {
    nb_missions: number;
    nb_points_ouverts: number;
    nb_points_depasses: number;
    nb_alertes: number;
  };
  volets_en_echec: string[];
  note: string;
};

type Props = {
  jeton?: string | null;
  contribuableId: number;
  onOuvrirMission?: (missionId: number) => void;
};

const LIBELLES_GRAVITE: Record<string, string> = {
  critique: "Critique",
  vigilance: "Vigilance",
  info: "Info",
};

const LIBELLES_VOLET: Record<string, string> = {
  missions: "missions",
  points_convenus: "points convenus",
  evolution_charge_fiscale: "évolution de la charge fiscale",
  alertes: "alertes",
};

function dateFr(iso: string | null): string {
  if (!iso) return "—";
  const [a, m, j] = iso.split("-");
  return a && m && j ? `${j}/${m}/${a}` : iso;
}

function montantFr(brut: string | null): string {
  if (brut === null || brut === "") return "—";
  const n = Number(brut);
  if (!Number.isFinite(n)) return brut;
  return `${n.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} FCFA`;
}

export function FicheClientVue({ jeton, contribuableId, onOuvrirMission }: Props) {
  const [fiche, setFiche] = useState<FicheClientOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!jeton) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<FicheClientOut>(
          `/api/v1/contribuables/${contribuableId}/fiche`,
          { jeton },
        );
        if (!annule) setFiche(out ?? null);
      } catch {
        if (!annule) {
          setFiche(null);
          setErr("Fiche client indisponible pour le moment.");
        }
      } finally {
        if (!annule) setBusy(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, [jeton, contribuableId]);

  const evolution = fiche?.evolution_charge_fiscale ?? null;
  const exercicesDisponibles = (evolution?.exercices ?? []).filter(
    (e) => e.disponible,
  );

  return (
    <section className="ctrale-zone" aria-label="Fiche client consolidée">
      <article className="panel dense ctrale-card">
        {busy && !fiche && <p className="ctrale-vide">Chargement de la fiche…</p>}
        {err && !busy && <p className="ctrale-err">{err}</p>}

        {fiche && (
          <>
            <div className="ctrale-synthese">
              <span className="ctrale-chip">
                <strong>{fiche.synthese.nb_missions}</strong> mission
                {fiche.synthese.nb_missions > 1 ? "s" : ""}
              </span>
              <span className="ctrale-chip">
                <strong>{fiche.synthese.nb_points_ouverts}</strong> point
                {fiche.synthese.nb_points_ouverts > 1 ? "s" : ""} convenu
                {fiche.synthese.nb_points_ouverts > 1 ? "s" : ""} ouvert
                {fiche.synthese.nb_points_ouverts > 1 ? "s" : ""}
              </span>
              {fiche.synthese.nb_points_depasses > 0 && (
                <span className="ctrale-chip vigilance">
                  <strong>{fiche.synthese.nb_points_depasses}</strong> date
                  {fiche.synthese.nb_points_depasses > 1 ? "s" : ""} cible
                  {fiche.synthese.nb_points_depasses > 1 ? "s" : ""} dépassée
                  {fiche.synthese.nb_points_depasses > 1 ? "s" : ""}
                </span>
              )}
              <span className="ctrale-chip">
                <strong>{fiche.synthese.nb_alertes}</strong> signal
                {fiche.synthese.nb_alertes > 1 ? "aux" : ""} du centre
                d'alertes
              </span>
            </div>

            {fiche.volets_en_echec.length > 0 && (
              <p className="ctrale-echec">
                Volet{fiche.volets_en_echec.length > 1 ? "s" : ""} momentanément
                indisponible{fiche.volets_en_echec.length > 1 ? "s" : ""} :{" "}
                {fiche.volets_en_echec
                  .map((v) => LIBELLES_VOLET[v] ?? v)
                  .join(", ")}{" "}
                — le reste de la fiche reste affiché.
              </p>
            )}

            <div className="calcab-mois">
              <h4 className="calcab-mois-titre">Missions par exercice</h4>
              {!fiche.missions.length && (
                <p className="ctrale-vide">Aucune mission pour ce client.</p>
              )}
              <ul className="ctrale-liste">
                {fiche.missions.map((m) => (
                  <li key={m.mission_id}>
                    <button
                      type="button"
                      className="ctrale-row"
                      title={`Ouvrir la mission #${m.mission_id}`}
                      disabled={!onOuvrirMission}
                      onClick={() => onOuvrirMission?.(m.mission_id)}
                    >
                      <span className="ctrale-ligne">
                        <span className="ctrale-meta">
                          Exercice {m.exercice}
                        </span>
                        <span className="ctrale-type">
                          {libelleStatut(m.statut)}
                        </span>
                        <span className="ctrale-libelle">
                          Mission #{m.mission_id}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            <div className="calcab-mois">
              <h4 className="calcab-mois-titre">
                Points convenus encore ouverts
              </h4>
              {!fiche.points_ouverts.length && (
                <p className="ctrale-vide">
                  Aucun point convenu en attente pour ce client.
                </p>
              )}
              <ul className="ctrale-liste">
                {fiche.points_ouverts.map((p) => (
                  <li key={p.point_id}>
                    <span className="ctrale-row">
                      <span className="ctrale-ligne">
                        <span className="ctrale-meta">
                          {p.date_cible
                            ? `Cible ${dateFr(p.date_cible)}`
                            : "Sans date cible"}
                        </span>
                        <span className="ctrale-libelle">
                          {p.exercice ? `Exercice ${p.exercice} · ` : ""}
                          {p.libelle}
                        </span>
                        {p.depassee && (
                          <span className="calcab-badge-depassee">
                            date passée — à reprogrammer si besoin
                          </span>
                        )}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="calcab-mois">
              <h4 className="calcab-mois-titre">
                Évolution de la charge fiscale estimée
              </h4>
              {!evolution && (
                <p className="ctrale-vide">
                  Évolution indisponible pour ce client.
                </p>
              )}
              {evolution && !exercicesDisponibles.length && (
                <p className="ctrale-vide">
                  {evolution.synthese?.libelle_statut ??
                    "Pas encore d'exercice exploitable."}
                </p>
              )}
              {exercicesDisponibles.length > 0 && (
                <ul className="ctrale-liste">
                  {exercicesDisponibles.map((e) => (
                    <li key={e.exercice}>
                      <span className="ctrale-row">
                        <span className="ctrale-ligne">
                          <span className="ctrale-meta">
                            Exercice {e.exercice}
                          </span>
                          <span className="ctrale-libelle">
                            Charge fiscale propre estimée :{" "}
                            {montantFr(e.total)}
                          </span>
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="calcab-mois">
              <h4 className="calcab-mois-titre">
                Signaux du centre d'alertes
              </h4>
              {!fiche.alertes.length && (
                <p className="ctrale-vide">
                  Aucun signal du centre d'alertes ne concerne ce client.
                </p>
              )}
              <ul className="ctrale-liste">
                {fiche.alertes.map((a, idx) => (
                  <li key={`${a.type}-${a.mission_id}-${idx}`}>
                    <button
                      type="button"
                      className="ctrale-row"
                      disabled={!a.mission_id || !onOuvrirMission}
                      title={
                        a.mission_id
                          ? `Ouvrir la mission #${a.mission_id}`
                          : a.libelle
                      }
                      onClick={() => {
                        if (a.mission_id) onOuvrirMission?.(a.mission_id);
                      }}
                    >
                      <span className="ctrale-ligne">
                        <span className={`ctrale-badge ${a.gravite}`}>
                          {LIBELLES_GRAVITE[a.gravite] ?? a.gravite}
                        </span>
                        {a.echeance && (
                          <span className="ctrale-meta">
                            {dateFr(a.echeance)}
                          </span>
                        )}
                        <span className="ctrale-libelle">{a.libelle}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            {fiche.note && <p className="ctrale-note">{fiche.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}
