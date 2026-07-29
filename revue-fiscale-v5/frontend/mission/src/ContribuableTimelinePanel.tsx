/** Journal d'audit du contribuable — timeline des événements liés à la fiche. */
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { TexteJuridique } from "./TexteJuridique";

type EvenementTimeline = {
  id: number;
  horodatage?: string | null;
  acteur: string;
  action: string;
  libelle?: string;
  consultation?: boolean;
  mission_id?: number | null;
  charge_utile?: Record<string, unknown>;
};

function formaterDateHeure(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("fr-FR", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function libelleEvenement(ev: EvenementTimeline): string {
  return ev.libelle || ev.action.replace(/_/g, " ");
}

type Props = {
  jeton: string;
  contribuableId: number;
};

export function ContribuableTimelinePanel({ jeton, contribuableId }: Props) {
  const [evenements, setEvenements] = useState<EvenementTimeline[]>([]);
  const [chargement, setChargement] = useState(true);

  const charger = useCallback(async () => {
    setChargement(true);
    try {
      const liste = await api<EvenementTimeline[]>(
        `/api/v1/contribuables/${contribuableId}/timeline`,
        { jeton },
      );
      setEvenements(Array.isArray(liste) ? liste : []);
    } catch {
      setEvenements([]);
    } finally {
      setChargement(false);
    }
  }, [contribuableId, jeton]);

  useEffect(() => {
    void charger();
  }, [charger]);

  const evenementsCles = evenements.filter((ev) => !ev.consultation);
  const evenementsConsultation = evenements.filter((ev) => ev.consultation);

  function ligne(ev: EvenementTimeline) {
    return (
      <li key={ev.id} className="dataroom-timeline-item">
        <span className="dataroom-timeline-date">
          {formaterDateHeure(ev.horodatage)}
        </span>
        <span className="dataroom-timeline-corps">
          <strong>
            <TexteJuridique texte={libelleEvenement(ev)} />
          </strong>
          {ev.mission_id != null ? ` — mission #${ev.mission_id}` : ""}
          <span className="dataroom-timeline-acteur"> · {ev.acteur}</span>
        </span>
      </li>
    );
  }

  return (
    <div className="panel dense clients-fiche-panel dataroom-section historique-timeline">
      <div className="clients-fiche-section-head">
        <div>
          <p className="picker-kicker">Timeline</p>
          <p className="picker-hint">
            Événements clés du journal d&apos;audit liés à ce contribuable.
          </p>
        </div>
      </div>
      {chargement ? (
        <p className="dataroom-vide muted">Chargement…</p>
      ) : evenements.length > 0 ? (
        <>
          {evenementsCles.length > 0 ? (
            <ol className="dataroom-timeline">
              {evenementsCles.map((ev) => ligne(ev))}
            </ol>
          ) : (
            <p className="dataroom-vide">
              Aucun événement clé — uniquement des consultations.
            </p>
          )}
          {evenementsConsultation.length > 0 && (
            <details className="compte-details historique-timeline-consultations">
              <summary>
                Journal de consultation ({evenementsConsultation.length})
              </summary>
              <ol className="dataroom-timeline">
                {evenementsConsultation.map((ev) => ligne(ev))}
              </ol>
            </details>
          )}
        </>
      ) : (
        <p className="dataroom-vide">Aucun événement enregistré.</p>
      )}
    </div>
  );
}
