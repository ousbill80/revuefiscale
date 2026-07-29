import { useEffect, useState } from "react";
import { api } from "./api";
import { InfoTip } from "./Tooltip";

/** Prescription des risques (GET /missions/{id}/prescription).
 *
 * Analyse déterministe du délai de reprise de droit commun (LPF CI) :
 * risques prescrits à basculer, proches de prescription (<12 mois),
 * non prescrits. Consultatif — l'humain décide de la bascule.
 */
type RisquePrescription = {
  risque_id: number;
  libelle: string;
  impot: string;
  exercice_origine: number;
  statut: string;
  montant: string | null;
  date_prescription: string;
};

type AnalysePrescription = {
  prescrits_a_basculer: RisquePrescription[];
  proches_prescription: RisquePrescription[];
  non_prescrits: RisquePrescription[];
  exposition_prescrite: string;
};

type PrescriptionOut = {
  mission_id: number;
  contribuable_id: number;
  date_analyse: string;
  exercices_reprenables: number[];
  analyse: AnalysePrescription;
  synthese: {
    prescrits_a_basculer: number;
    proches_prescription: number;
    non_prescrits: number;
    exposition_prescrite: string;
  };
  hypothese: string;
};

/** Montant str Decimal → « 1 234 567 FCFA » (fr-FR, sans décimales). */
function fmtMontant(v: string | null | undefined): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString("fr-FR", { maximumFractionDigits: 0 }) + " FCFA";
}

/** Date ISO (AAAA-MM-JJ) → JJ/MM/AAAA, sans fuseau. */
function fmtDate(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso ?? ""));
  if (!m) return iso || "—";
  return `${m[3]}/${m[2]}/${m[1]}`;
}

/** [2023, 2024, 2025] → « 2023 – 2025 » (ou liste brute si non contigus). */
function fmtExercices(annees: number[]): string {
  if (annees.length === 0) return "—";
  if (annees.length === 1) return String(annees[0]);
  const tries = [...annees].sort((a, b) => a - b);
  const contigus = tries.every((a, i) => i === 0 || a === tries[i - 1] + 1);
  if (contigus) return `${tries[0]} – ${tries[tries.length - 1]}`;
  return tries.join(", ");
}

function ListeRisques({
  titre,
  items,
  variante,
}: {
  titre: string;
  items: RisquePrescription[];
  variante: "prescrit" | "proche" | "non-prescrit";
}) {
  if (items.length === 0) return null;
  return (
    <div className={`rest-prescription-groupe rest-prescription-groupe--${variante}`}>
      <h4 className="rest-prescription-groupe-titre">
        <span className={`rest-prescription-badge rest-prescription-badge--${variante}`}>
          {items.length}
        </span>
        {titre}
      </h4>
      <ul className="rest-suivi-items rest-prescription-items">
        {items.map((r) => (
          <li key={r.risque_id} className="rest-suivi-item rest-prescription-item">
            <div className="rest-suivi-libelle">
              {r.impot && <span className="rest-suivi-cle">{r.impot}</span>}
              <span className="rest-prescription-libelle">{r.libelle || "—"}</span>
            </div>
            <div className="rest-prescription-meta muted">
              <span>Exercice {r.exercice_origine}</span>
              <span>
                {variante === "prescrit" ? "Prescrit depuis le " : "Prescription le "}
                <strong className="rest-prescription-date">
                  {fmtDate(r.date_prescription)}
                </strong>
              </span>
              {r.montant != null && r.montant !== "" && (
                <span>Exposition : {fmtMontant(r.montant)}</span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

type Props = {
  missionId: number;
  jeton?: string | null;
  onFermer: () => void;
};

export function PrescriptionVue({ missionId, jeton, onFermer }: Props) {
  const [etat, setEtat] = useState<PrescriptionOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!jeton || !missionId) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<PrescriptionOut>(
          `/api/v1/missions/${missionId}/prescription`,
          { jeton },
        );
        if (!annule) setEtat(out ?? null);
      } catch (e) {
        if (!annule) {
          setEtat(null);
          setErr(
            e instanceof Error
              ? e.message
              : "analyse de prescription indisponible",
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

  const totalRisques = etat
    ? etat.synthese.prescrits_a_basculer +
      etat.synthese.proches_prescription +
      etat.synthese.non_prescrits
    : 0;

  return (
    <section
      className="rest-suivi rest-prescription"
      aria-label="Prescription des risques"
    >
      <div className="rest-suivi-head">
        <h3 className="rest-suivi-titre label-with-tip">
          Prescription des risques
          <InfoTip
            label="Analyse du délai de reprise de droit commun (pratique LPF CI : fin de la 3e année suivant celle au titre de laquelle l'impôt est dû ; des délais spéciaux existent) : risques dont la prescription est acquise (à basculer au statut « prescrit »), proches de prescription (moins de 12 mois) et non prescrits. Analyse consultative, à valider par le fiscaliste — la bascule reste une décision humaine."
            ariaLabel="Aide : prescription des risques"
          />
        </h3>
        <div className="rest-suivi-outils">
          {etat && (
            <span className="muted">
              Analyse au {fmtDate(etat.date_analyse)}
            </span>
          )}
          <button type="button" className="btn btn-ghost btn-sm" onClick={onFermer}>
            Fermer
          </button>
        </div>
      </div>
      {busy && <p className="muted">Analyse de la prescription…</p>}
      {err && (
        <p className="rest-lettre-err" role="alert">
          Prescription indisponible : {err}
        </p>
      )}
      {etat && (
        <>
          <div className="rest-prescription-synthese">
            <div className="rest-prescription-stat">
              <span className="rest-prescription-stat-val">
                {fmtExercices(etat.exercices_reprenables)}
              </span>
              <span className="rest-prescription-stat-lbl">
                Exercices reprenables
              </span>
            </div>
            <div className="rest-prescription-stat rest-prescription-stat--prescrit">
              <span className="rest-prescription-stat-val">
                {etat.synthese.prescrits_a_basculer}
              </span>
              <span className="rest-prescription-stat-lbl">
                Prescrit{etat.synthese.prescrits_a_basculer > 1 ? "s" : ""} à
                basculer
              </span>
            </div>
            <div className="rest-prescription-stat rest-prescription-stat--proche">
              <span className="rest-prescription-stat-val">
                {etat.synthese.proches_prescription}
              </span>
              <span className="rest-prescription-stat-lbl">
                Proche{etat.synthese.proches_prescription > 1 ? "s" : ""} de
                prescription (&lt;12 mois)
              </span>
            </div>
            <div className="rest-prescription-stat">
              <span className="rest-prescription-stat-val">
                {fmtMontant(etat.synthese.exposition_prescrite)}
              </span>
              <span className="rest-prescription-stat-lbl">
                Exposition prescrite
              </span>
            </div>
          </div>

          {totalRisques === 0 ? (
            <p className="muted">
              Aucun risque enregistré — la prescription s'appréciera au fil de
              la revue.
            </p>
          ) : (
            <>
              <ListeRisques
                titre="Prescrits — à basculer au statut « prescrit »"
                items={etat.analyse.prescrits_a_basculer}
                variante="prescrit"
              />
              <ListeRisques
                titre="Proches de prescription (moins de 12 mois)"
                items={etat.analyse.proches_prescription}
                variante="proche"
              />
              <ListeRisques
                titre="Non prescrits — exercices encore reprenables"
                items={etat.analyse.non_prescrits}
                variante="non-prescrit"
              />
            </>
          )}

        </>
      )}
    </section>
  );
}
