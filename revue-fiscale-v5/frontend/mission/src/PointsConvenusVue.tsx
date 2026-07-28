import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "./api";
import { InfoTip } from "./Tooltip";

/** Suivi des points convenus du compte-rendu de restitution.
 *
 * Vue consultative : un point convenu par ligne, saisi par le
 * fiscaliste, avec un statut de suivi explicite (« à faire » par
 * défaut, puis « fait » ou « abandonné » sur clic humain confirmé).
 */
type PointConvenu = {
  id: number;
  libelle: string;
  statut: "a_faire" | "fait" | "abandonne";
  date_cible: string | null;
  en_retard?: boolean;
  cree_le: string | null;
  mis_a_jour_le: string | null;
};

type PointsConvenusOut = {
  mission_id: number;
  points: PointConvenu[];
  synthese: {
    a_faire: number;
    fait: number;
    abandonne: number;
    en_retard?: number;
  };
  note: string;
};

const LIBELLES_STATUT: Record<PointConvenu["statut"], string> = {
  a_faire: "À faire",
  fait: "Fait",
  abandonne: "Abandonné",
};

type Props = {
  missionId: number;
  jeton?: string | null;
  estLecteur?: boolean;
};

export function PointsConvenusVue({ missionId, jeton, estLecteur }: Props) {
  const [etat, setEtat] = useState<PointsConvenusOut | null>(null);
  const [saisie, setSaisie] = useState("");
  const [dateCible, setDateCible] = useState("");
  const [busy, setBusy] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<PointsConvenusOut>(
        `/api/v1/missions/${missionId}/points-convenus`,
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

  async function ajouter() {
    const libelle = saisie.trim();
    if (!jeton || !libelle) return;
    setBusy(true);
    setErreur(null);
    try {
      await api(`/api/v1/missions/${missionId}/points-convenus`, {
        method: "POST",
        jeton,
        json: dateCible
          ? { libelle, date_cible: dateCible }
          : { libelle },
      });
      setSaisie("");
      setDateCible("");
      await charger();
    } catch (e) {
      setErreur(
        e instanceof ApiError ? e.message : "ajout du point impossible",
      );
    } finally {
      setBusy(false);
    }
  }

  async function changerStatut(
    point: PointConvenu,
    statut: "fait" | "abandonne",
  ) {
    if (!jeton) return;
    const question =
      statut === "fait"
        ? `Marquer « ${point.libelle} » comme fait ?`
        : `Abandonner le point « ${point.libelle} » ?`;
    if (!window.confirm(question)) return;
    setBusy(true);
    setErreur(null);
    try {
      await api(`/api/v1/points-convenus/${point.id}/statut`, {
        method: "POST",
        jeton,
        json: { statut },
      });
      await charger();
    } catch (e) {
      setErreur(
        e instanceof ApiError
          ? e.message
          : "changement de statut impossible",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!etat) return null;
  const s = etat.synthese;
  return (
    <section className="pconv" aria-label="Suivi des points convenus">
      <div className="pconv-head">
        <h4 className="pconv-titre label-with-tip">
          Suivi des points convenus
          <InfoTip
            label="Points convenus avec le client lors de la restitution, suivis un par un. Consultatif : les statuts « fait » et « abandonné » sont posés par le fiscaliste, sur clic confirmé — rien n'est automatique."
            ariaLabel="Aide : suivi des points convenus"
          />
        </h4>
        <span className="pconv-synthese muted">
          {s.a_faire} à faire · {s.fait} fait{s.fait > 1 ? "s" : ""} ·{" "}
          {s.abandonne} abandonné{s.abandonne > 1 ? "s" : ""}
          {(s.en_retard ?? 0) > 0 && (
            <>
              {" "}
              ·{" "}
              <strong className="pconv-synthese-retard">
                {s.en_retard} en retard
              </strong>
            </>
          )}
        </span>
      </div>
      {etat.points.length === 0 ? (
        <p className="pconv-vide muted">
          Aucun point convenu suivi pour cette mission.
        </p>
      ) : (
        <ul className="pconv-liste">
          {etat.points.map((p) => (
            <li key={p.id} className={`pconv-item pconv-item-${p.statut}`}>
              <span className={`pconv-badge pconv-badge-${p.statut}`}>
                {LIBELLES_STATUT[p.statut]}
              </span>
              <span className="pconv-libelle">{p.libelle}</span>
              {p.date_cible && (
                <span className="pconv-cible muted">
                  cible {p.date_cible}
                </span>
              )}
              {p.en_retard && (
                <span className="pconv-badge pconv-badge-retard">
                  En retard
                </span>
              )}
              {!estLecteur && p.statut === "a_faire" && (
                <span className="pconv-actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={busy}
                    onClick={() => void changerStatut(p, "fait")}
                  >
                    Fait
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={busy}
                    onClick={() => void changerStatut(p, "abandonne")}
                  >
                    Abandonner
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {!estLecteur && (
        <div className="pconv-form">
          <input
            type="text"
            value={saisie}
            maxLength={500}
            placeholder="Ex. : régulariser la TVA du T4 avant le 15"
            onChange={(e) => setSaisie(e.target.value)}
            disabled={busy}
          />
          <input
            type="date"
            className="pconv-input-date"
            value={dateCible}
            title="Date cible convenue avec le client (optionnelle)"
            aria-label="Date cible convenue avec le client (optionnelle)"
            onChange={(e) => setDateCible(e.target.value)}
            disabled={busy}
          />
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void ajouter()}
            disabled={busy || !jeton || !saisie.trim()}
          >
            {busy ? "Ajout…" : "Ajouter le point"}
          </button>
        </div>
      )}
      {erreur && (
        <p className="pconv-erreur" role="alert">
          {erreur}
        </p>
      )}
      <p className="pconv-note muted">{etat.note}</p>
    </section>
  );
}
