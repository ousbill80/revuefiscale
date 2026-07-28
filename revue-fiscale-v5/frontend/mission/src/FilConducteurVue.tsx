import { useEffect, useState } from "react";
import { api } from "./api";
import { InfoTip } from "./Tooltip";

/** Fil conducteur de la mission (GET /missions/{id}/fil-conducteur).
 *
 * Guide LECTURE SEULE placé en tête de la vue mission : l'état de
 * chaque étape du process (cadrage, collecte, ciblage, revues,
 * liquidation, restitution, suivi) est dérivé de manière déterministe
 * des modules existants côté serveur. Consultatif : la progression
 * suggérée n'impose rien, le fiscaliste décide de l'ordre réel.
 */

type StatutEtape = "faite" | "en_cours" | "a_faire" | "indisponible";

type EtapeFil = {
  code: string;
  libelle: string;
  statut: StatutEtape;
  detail: string;
};

type FilOut = {
  mission_id: number;
  etapes: EtapeFil[];
  synthese: {
    faites: number;
    total: number;
    prochaine_etape: { code: string; libelle: string } | null;
  };
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

const LIBELLES_STATUT: Record<StatutEtape, string> = {
  faite: "Faite",
  en_cours: "En cours",
  a_faire: "À faire",
  indisponible: "Indisponible",
};

/** Modificateur de badge — réutilise les classes badge-traitement. */
const CLASSE_STATUT: Record<StatutEtape, string> = {
  faite: "badge-traitement badge-traitement--conforme",
  en_cours: "badge-traitement badge-traitement--en_cours",
  a_faire: "badge-traitement badge-traitement--a_faire",
  indisponible: "badge-traitement",
};

export function FilConducteurVue({ missionId, jeton }: Props) {
  const [etat, setEtat] = useState<FilOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!jeton || !missionId) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<FilOut>(
          `/api/v1/missions/${missionId}/fil-conducteur`,
          { jeton },
        );
        if (!annule) setEtat(out ?? null);
      } catch (e) {
        if (!annule) {
          setEtat(null);
          setErr(
            e instanceof Error ? e.message : "fil conducteur indisponible",
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
    <section
      className="rest-suivi fil-conducteur"
      aria-label="Fil conducteur de la mission"
    >
      <div className="rest-suivi-head">
        <h3 className="rest-suivi-titre label-with-tip">
          Fil conducteur de la mission
          <InfoTip
            label="Guide consultatif du process de revue : l'état de chaque étape est dérivé des modules existants (lettre de mission, data room, matérialité, programme, rapprochements, résultat fiscal, restitution, suivi). Rien n'est imposé : vous décidez de l'ordre réel de vos travaux."
            ariaLabel="Aide : fil conducteur de la mission"
          />
        </h3>
        <div className="rest-suivi-outils">
          {etat && (
            <span className="muted">
              {etat.synthese.faites}/{etat.synthese.total} étape(s) faite(s)
            </span>
          )}
        </div>
      </div>
      {busy && <p className="muted">Fil conducteur…</p>}
      {err && (
        <p className="rest-lettre-err" role="alert">
          Fil conducteur indisponible : {err}
        </p>
      )}
      {etat && !busy && (
        <>
          {etat.synthese.prochaine_etape ? (
            <p className="muted">
              Prochaine étape suggérée :{" "}
              <strong>{etat.synthese.prochaine_etape.libelle}</strong>{" "}
              (consultatif — vous décidez de l&apos;ordre réel).
            </p>
          ) : (
            <p className="muted">
              Toutes les étapes du process sont faites.
            </p>
          )}
          <ol className="delais-liste">
            {etat.etapes.map((e, idx) => (
              <li key={e.code} className="delais-item">
                <span className="delais-ligne">
                  <span className={CLASSE_STATUT[e.statut]}>
                    {LIBELLES_STATUT[e.statut]}
                  </span>
                  <span
                    className={`delais-libelle${
                      e.statut === "indisponible" ? " delais-absent" : ""
                    }`}
                  >
                    {idx + 1}. {e.libelle}
                    {" — "}
                    <span className="muted">{e.detail}</span>
                  </span>
                </span>
              </li>
            ))}
          </ol>
          <p className="delais-note muted">{etat.note}</p>
        </>
      )}
    </section>
  );
}
