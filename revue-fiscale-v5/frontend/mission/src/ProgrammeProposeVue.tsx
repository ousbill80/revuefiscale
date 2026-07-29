import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { InfoTip } from "./Tooltip";

/** Programme de travail proposé — pont consultatif.
 *
 * Propose des diligences déterministes déduites des comptes ciblés par
 * le seuil de matérialité retenu (mapping préfixe SYSCOHADA →
 * diligence type : 70x → revue du CA, 44x → comptes d'État, 66x/42x →
 * rémunérations/ITS, 2x → immobilisations…) et des risques non clos du
 * contribuable. Le fiscaliste ACCEPTE une proposition d'un clic : elle
 * est alors créée dans le programme de travail existant. Les
 * propositions déjà couvertes sont signalées. Strictement consultatif :
 * aucune écriture automatique, l'humain décide du programme.
 */
type Proposition = {
  code: string;
  phase: string;
  libelle: string;
  origine: string;
  comptes: string[];
  justification: string;
  deja_couverte: boolean;
};

type ProgrammeProposeOut = {
  mission_id: number;
  exercice: number;
  seuil_retenu: string | null;
  propositions: Proposition[];
  synthese: {
    statut: string;
    nb_propositions: number;
    nb_deja_couvertes: number;
    nb_a_accepter: number;
  };
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
  estLecteur?: boolean;
};

const LIBELLES_PHASES: Record<string, string> = {
  cadrage: "Cadrage",
  collecte: "Collecte",
  controles: "Contrôles",
  restitution: "Restitution",
  suivi: "Suivi",
};

export function ProgrammeProposeVue({
  missionId,
  jeton,
  estLecteur,
}: Props) {
  const [etat, setEtat] = useState<ProgrammeProposeOut | null>(null);
  const [msg, setMsg] = useState<{ texte: string; err: boolean } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<ProgrammeProposeOut>(
        `/api/v1/missions/${missionId}/programme-propose`,
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

  const accepter = useCallback(
    async (code: string) => {
      if (!jeton || !missionId) return;
      setBusy(true);
      setMsg(null);
      try {
        const out = await api<{ statut: string }>(
          `/api/v1/missions/${missionId}/programme-propose`,
          { method: "POST", jeton, json: { code } },
        );
        setMsg({
          texte:
            out?.statut === "deja_couverte"
              ? "Diligence déjà couverte par le programme de travail."
              : "Diligence ajoutée au programme de travail.",
          err: false,
        });
        await charger();
      } catch (e) {
        setMsg({
          texte:
            e instanceof Error ? e.message : "Acceptation impossible.",
          err: true,
        });
      } finally {
        setBusy(false);
      }
    },
    [jeton, missionId, charger],
  );

  if (!etat) return null;
  const s = etat.synthese;
  return (
    <section
      className="matx panel dense"
      aria-label="Programme de travail proposé"
    >
      <div className="matx-head">
        <h4 className="matx-titre label-with-tip">
          Programme de travail proposé
          <InfoTip
            label="Diligences proposées depuis les comptes ciblés par le seuil de matérialité retenu (mapping SYSCOHADA → diligence type) et depuis les risques non clos du contribuable. Chaque proposition n'entre dans le programme de travail que sur votre acceptation explicite — vue consultative, l'humain décide."
            ariaLabel="Aide : programme de travail proposé"
          />
        </h4>
        <span className="matx-synthese muted">
          {s.nb_propositions} proposition
          {s.nb_propositions > 1 ? "s" : ""}
          {s.nb_deja_couvertes > 0 && (
            <> · {s.nb_deja_couvertes} déjà couverte
              {s.nb_deja_couvertes > 1 ? "s" : ""}</>
          )}
        </span>
      </div>

      {s.statut === "seuil_a_retenir" && (
        <p className="empty-state">
          Retenez d'abord un seuil de matérialité pour obtenir les
          diligences proposées depuis le ciblage des comptes
          {etat.propositions.length > 0
            ? " — les propositions issues des risques restent listées ci-dessous."
            : "."}
        </p>
      )}
      {s.statut === "aucune_proposition" && (
        <p className="empty-state">
          Aucune diligence complémentaire à proposer : aucun compte
          ciblé et aucun risque non clos au registre.
        </p>
      )}

      {etat.propositions.length > 0 && (
        <table className="matx-table">
          <thead>
            <tr>
              <th scope="col">Diligence proposée</th>
              <th scope="col">Phase</th>
              <th scope="col">Justification</th>
              {!estLecteur && <th scope="col" />}
            </tr>
          </thead>
          <tbody>
            {etat.propositions.map((p) => (
              <tr key={p.code}>
                <td className="matx-ref">
                  {p.libelle}
                  {p.deja_couverte && (
                    <span className="matx-badge-retenu">
                      {" "}
                      Déjà couverte
                    </span>
                  )}
                </td>
                <td>{LIBELLES_PHASES[p.phase] ?? p.phase}</td>
                <td className="muted">{p.justification}</td>
                {!estLecteur && (
                  <td>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      disabled={busy || p.deja_couverte}
                      onClick={() => void accepter(p.code)}
                    >
                      Ajouter au programme
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {msg && (
        <p className={`status${msg.err ? " err" : ""}`} role="status">
          {msg.texte}
        </p>
      )}

    </section>
  );
}
