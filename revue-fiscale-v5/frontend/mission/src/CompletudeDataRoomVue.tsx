import { useEffect, useState } from "react";
import { api } from "./api";
import { InfoTip } from "./Tooltip";

/** Complétude du socle documentaire (GET /missions/{id}/completude-data-room).
 *
 * Vue consultative : pièces comptables de base attendues selon le
 * régime de la mission (états financiers, balance, grand livre/FEC,
 * déclarations), présentes ou manquantes, et taux sur les essentielles.
 */
type AttenduCompletude = {
  code: string;
  libelle: string;
  essentielle: boolean;
  presente: boolean;
  nb_pieces: number;
  exemples: string[];
};

type CompletudeOut = {
  mission_id: number;
  regime: string;
  attendus: AttenduCompletude[];
  synthese: {
    attendues: number;
    presentes: number;
    essentielles_manquantes: number;
    taux_completude: string;
  };
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
  /** Change à chaque dépôt/retrait de pièce pour re-évaluer. */
  version: number;
};

export function CompletudeDataRoomVue({ missionId, jeton, version }: Props) {
  const [etat, setEtat] = useState<CompletudeOut | null>(null);

  useEffect(() => {
    if (!jeton || !missionId) return;
    let annule = false;
    void (async () => {
      try {
        const out = await api<CompletudeOut>(
          `/api/v1/missions/${missionId}/completude-data-room`,
          { jeton },
        );
        if (!annule) setEtat(out ?? null);
      } catch {
        if (!annule) setEtat(null);
      }
    })();
    return () => {
      annule = true;
    };
  }, [jeton, missionId, version]);

  if (!etat) return null;
  const s = etat.synthese;
  return (
    <section
      className="compdr"
      aria-label="Complétude du socle documentaire"
    >
      <div className="compdr-head">
        <h4 className="compdr-titre label-with-tip">
          Complétude du socle documentaire
          <InfoTip
            label="Pièces comptables de base attendues pour la revue selon le régime de la mission. Consultatif : une pièce « manquante » signifie seulement qu'aucun document du type attendu n'a été déposé ici."
            ariaLabel="Aide : complétude du socle documentaire"
          />
        </h4>
        <span
          className={`compdr-taux${
            s.essentielles_manquantes > 0 ? " compdr-taux-attention" : ""
          }`}
        >
          {s.taux_completude} % des pièces essentielles
        </span>
      </div>
      <ul className="compdr-liste">
        {etat.attendus.map((a) => (
          <li
            key={a.code}
            className={`compdr-item${a.presente ? "" : " compdr-manquante"}`}
          >
            <span className="compdr-marque" aria-hidden="true">
              {a.presente ? "✓" : "—"}
            </span>
            <span className="compdr-libelle">
              {a.libelle}
              {!a.presente && a.essentielle && (
                <span className="compdr-badge-essentielle">essentielle</span>
              )}
            </span>
            {a.presente && (
              <span className="compdr-exemples muted">
                {a.nb_pieces > 1 ? `${a.nb_pieces} pièces · ` : ""}
                {a.exemples.join(", ")}
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="compdr-note muted">{etat.note}</p>
    </section>
  );
}
