import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { InfoTip } from "./Tooltip";

/** Points en suspens des missions antérieures du même contribuable.
 *
 * Vue strictement consultative affichée au démarrage / à la reprise
 * d'une mission (typiquement après reconduction) : les points
 * convenus encore « à faire » nés des missions des exercices
 * antérieurs. Le traitement (fait / abandonné) se saisit dans la
 * mission d'origine — rien ne s'écrit ici.
 */
type PointAnterieur = {
  point_id: number;
  mission_id: number;
  exercice: number;
  libelle: string;
  date_cible: string | null;
  en_retard: boolean;
};

type PointsAnterieursOut = {
  mission_id: number;
  exercice: number;
  points: PointAnterieur[];
  synthese: { total: number; en_retard: number; missions: number };
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

export function PointsAnterieursVue({ missionId, jeton }: Props) {
  const [etat, setEtat] = useState<PointsAnterieursOut | null>(null);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<PointsAnterieursOut>(
        `/api/v1/missions/${missionId}/points-anterieurs`,
        { jeton },
      );
      setEtat(out ?? null);
    } catch {
      setEtat(null);
    }
  }, [jeton, missionId]);

  useEffect(() => {
    void charger();
  }, [charger]);

  // Rien à rappeler : le bloc ne s'affiche pas (zéro bruit).
  if (!etat || etat.synthese.total === 0) return null;
  const s = etat.synthese;
  return (
    <section
      className="pant"
      aria-label="Points en suspens des missions antérieures"
    >
      <div className="pant-head">
        <h4 className="pant-titre label-with-tip">
          Points en suspens des missions antérieures
          <InfoTip
            label="Points convenus encore « à faire » nés des missions des exercices antérieurs de ce client. Rappel consultatif au démarrage de la mission : le traitement se saisit dans la mission d'origine du point."
            ariaLabel="Aide : points en suspens des missions antérieures"
          />
        </h4>
        <span className="pant-synthese muted">
          {s.total} point{s.total > 1 ? "s" : ""} · {s.missions} mission
          {s.missions > 1 ? "s" : ""}
          {s.en_retard > 0 && (
            <>
              {" "}
              ·{" "}
              <strong className="pant-synthese-retard">
                {s.en_retard} en retard
              </strong>
            </>
          )}
        </span>
      </div>
      <table className="pant-table">
        <thead>
          <tr>
            <th scope="col">Exercice</th>
            <th scope="col">Libellé</th>
            <th scope="col">Date cible</th>
          </tr>
        </thead>
        <tbody>
          {etat.points.map((p) => (
            <tr key={p.point_id}>
              <td className="pant-exercice">{p.exercice}</td>
              <td className="pant-libelle">{p.libelle}</td>
              <td className="pant-cible">
                {p.date_cible ?? "—"}
                {p.en_retard && (
                  <span className="pant-badge-retard">En retard</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="pant-note muted">{etat.note}</p>
    </section>
  );
}
