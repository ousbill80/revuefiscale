import { useEffect, useState } from "react";
import { api } from "./api";
import { libelleStatut } from "./MissionsVue";

/** « Mon tableau de bord » (GET /api/v1/moi/tableau) — l'email vient
 *  du jeton de l'utilisateur connecté. Bloc affiché seulement si le
 *  collaborateur a au moins une mission affectée. Lecture seule. */
type MaMission = {
  mission_id: number;
  client: string;
  exercice: number;
  statut: string;
};

type MonPoint = {
  mission_id: number;
  client: string;
  exercice: number;
  point_id: number;
  libelle: string;
  date_cible: string | null;
  en_retard: boolean;
  anciennete_jours: number;
};

type MonEcheance = {
  client: string;
  mission_id: number;
  exercice: number;
  impot: string;
  obligation: string;
  periode: string;
  date_limite: string;
  jours_restants: number;
};

type MonTableauOut = {
  aujourd_hui: string;
  email: string;
  missions: MaMission[];
  points: MonPoint[];
  echeances: MonEcheance[];
  synthese: {
    missions: number;
    points_a_faire: number;
    points_en_retard: number;
    echeances_30j: number;
    echeances_semaine: number;
  };
  note: string;
};

type Props = {
  jeton?: string | null;
  onOuvrirMission: (missionId: number) => void;
};

function dateFr(iso: string): string {
  const [a, m, j] = iso.split("-");
  return a && m && j ? `${j}/${m}/${a}` : iso;
}

export function MonTableauVue({ jeton, onOuvrirMission }: Props) {
  const [vue, setVue] = useState<MonTableauOut | null>(null);

  useEffect(() => {
    if (!jeton) return;
    let annule = false;
    void (async () => {
      try {
        const out = await api<MonTableauOut>("/api/v1/moi/tableau", {
          jeton,
        });
        if (!annule) setVue(out ?? null);
      } catch {
        if (!annule) setVue(null);
      }
    })();
    return () => {
      annule = true;
    };
  }, [jeton]);

  // Bloc personnel : rien à afficher tant que le collaborateur n'a
  // aucune mission affectée (pas de bruit sur le tableau de bord).
  if (!vue || vue.missions.length === 0) return null;

  return (
    <section className="montab-zone" aria-label="Mon tableau de bord">
      <div className="montab-head">
        <div>
          <h3 className="montab-title">Mon tableau de bord</h3>
          <p className="montab-sub">
            Vos priorités du jour — missions dont vous êtes responsable,
            points à traiter et échéances fiscales à venir.
          </p>
        </div>
      </div>

      <article className="panel dense montab-card">
        <div className="montab-grille">
          <div className="montab-col">
            <h4 className="montab-soustitre">
              Mes missions ({vue.synthese.missions})
            </h4>
            <ul className="montab-liste">
              {vue.missions.map((m) => (
                <li key={m.mission_id}>
                  <button
                    type="button"
                    className="montab-row"
                    title={`Ouvrir la mission #${m.mission_id} · ${m.client}`}
                    onClick={() => onOuvrirMission(m.mission_id)}
                  >
                    <span className="montab-libelle">{m.client}</span>
                    <span className="montab-meta">
                      {m.exercice} ·{" "}
                      <span className={`badge statut-${m.statut}`}>
                        {libelleStatut(m.statut)}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="montab-col">
            <h4 className="montab-soustitre">
              Mes points à traiter ({vue.synthese.points_a_faire})
              {vue.synthese.points_en_retard > 0 && (
                <span className="montab-badge retard">
                  {vue.synthese.points_en_retard} en retard
                </span>
              )}
            </h4>
            {vue.points.length === 0 && (
              <p className="montab-vide">
                Aucun point à traiter. Rien en attente sur vos missions.
              </p>
            )}
            <ul className="montab-liste">
              {vue.points.map((p) => (
                <li key={p.point_id}>
                  <button
                    type="button"
                    className="montab-row"
                    title={`Ouvrir la mission #${p.mission_id} · ${p.client}`}
                    onClick={() => onOuvrirMission(p.mission_id)}
                  >
                    <span className="montab-libelle">
                      {p.en_retard && (
                        <span className="montab-badge retard">retard</span>
                      )}
                      {p.libelle}
                    </span>
                    <span className="montab-meta">
                      {p.client}
                      {p.date_cible
                        ? ` · pour le ${dateFr(p.date_cible)}`
                        : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="montab-col">
            <h4 className="montab-soustitre">
              Mes échéances 30 j ({vue.synthese.echeances_30j})
              {vue.synthese.echeances_semaine > 0 && (
                <span className="montab-badge retard">
                  {vue.synthese.echeances_semaine} ≤ 7 j
                </span>
              )}
            </h4>
            {vue.echeances.length === 0 && (
              <p className="montab-vide">
                Aucune échéance. Rien dans les 30 prochains jours pour vos
                missions en cours.
              </p>
            )}
            <ul className="montab-liste">
              {vue.echeances.map((e, idx) => (
                <li key={`${e.mission_id}-${e.date_limite}-${idx}`}>
                  <button
                    type="button"
                    className="montab-row"
                    title={`Ouvrir la mission #${e.mission_id} · ${e.client}`}
                    onClick={() => onOuvrirMission(e.mission_id)}
                  >
                    <span className="montab-libelle">
                      <span
                        className={`montab-badge${
                          e.jours_restants <= 7 ? " retard" : ""
                        }`}
                      >
                        {dateFr(e.date_limite)}
                      </span>
                      {e.impot}
                    </span>
                    <span className="montab-meta">
                      {e.client} · {e.obligation} — {e.periode}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {vue.note && <p className="montab-note">{vue.note}</p>}
      </article>
    </section>
  );
}
