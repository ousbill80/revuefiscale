import { useEffect, useState } from "react";
import { api } from "./api";
import { InfoTip } from "./Tooltip";

/** Civisme déclaratif (GET /missions/{id}/civisme-fiscal).
 *
 * Rapprochement déterministe entre l'échéancier fiscal théorique de
 * l'exercice revu et les pièces collectées en data room de mission :
 * échéances couvertes, en attente ou manquantes, avec taux de civisme.
 * Consultatif — l'application ne stocke pas les déclarations déposées.
 */
type EcheanceRapprochee = {
  impot: string;
  obligation: string;
  periode: string;
  date_limite: string;
  statut: "couverte" | "en_attente" | "manquante" | string;
  source?: string | null;
};

type CivismeOut = {
  mission_id: number;
  exercice: number;
  regime: string;
  aujourd_hui: string;
  elements_collectes: { impot: string; periode: string | null; source: string }[];
  rapprochement: EcheanceRapprochee[];
  synthese: {
    couvertes: number;
    en_attente: number;
    manquantes: number;
    taux_civisme: string;
  };
  note: string;
};

/** Date ISO (AAAA-MM-JJ) → JJ/MM/AAAA, sans fuseau. */
function fmtDate(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso ?? ""));
  if (!m) return iso || "—";
  return `${m[3]}/${m[2]}/${m[1]}`;
}

/** Taux str Decimal (« 8.33 ») → « 8,33 % » (fr-FR). */
function fmtTaux(v: string | null | undefined): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return (
    n.toLocaleString("fr-FR", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }) + " %"
  );
}

const LIBELLES_STATUT: Record<string, string> = {
  couverte: "Couverte",
  en_attente: "En attente",
  manquante: "Manquante",
};

type ReclamationOut = {
  crees: number;
  ignores_existants: number;
  total_manquantes: number;
};

type Props = {
  missionId: number;
  jeton?: string | null;
  onFermer: () => void;
  /** Mission clôturée : la réclamation des pièces manquantes est désactivée. */
  missionCloturee?: boolean;
};

export function CivismeVue({ missionId, jeton, onFermer, missionCloturee }: Props) {
  const [etat, setEtat] = useState<CivismeOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reclamation, setReclamation] = useState<ReclamationOut | null>(null);
  const [reclamationErr, setReclamationErr] = useState<string | null>(null);
  const [reclamationBusy, setReclamationBusy] = useState(false);

  async function reclamerPiecesManquantes() {
    if (!jeton || !missionId || reclamationBusy) return;
    setReclamationBusy(true);
    setReclamationErr(null);
    try {
      const out = await api<ReclamationOut>(
        `/api/v1/missions/${missionId}/suivi-renseignements/depuis-civisme`,
        { jeton, method: "POST" },
      );
      setReclamation(out ?? null);
    } catch (e) {
      setReclamation(null);
      setReclamationErr(
        e instanceof Error
          ? e.message
          : "ajout à la demande de renseignements impossible",
      );
    } finally {
      setReclamationBusy(false);
    }
  }

  useEffect(() => {
    if (!jeton || !missionId) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<CivismeOut>(
          `/api/v1/missions/${missionId}/civisme-fiscal`,
          { jeton },
        );
        if (!annule) setEtat(out ?? null);
      } catch (e) {
        if (!annule) {
          setEtat(null);
          setErr(
            e instanceof Error
              ? e.message
              : "analyse de civisme déclaratif indisponible",
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
      className="rest-suivi rest-prescription rest-civisme"
      aria-label="Civisme déclaratif"
    >
      <div className="rest-suivi-head">
        <h3 className="rest-suivi-titre label-with-tip">
          Civisme déclaratif
          <InfoTip
            label="Rapprochement entre l'échéancier fiscal théorique de l'exercice revu et les pièces collectées en data room : échéances couvertes, en attente ou manquantes, avec taux de civisme. L'application ne stocke pas les déclarations déposées : une échéance « manquante » signifie seulement qu'aucune pièce correspondante n'a été collectée — à vérifier par le fiscaliste."
            ariaLabel="Aide : civisme déclaratif"
          />
        </h3>
        <div className="rest-suivi-outils">
          {etat && (
            <span className="muted">
              Exercice {etat.exercice} — régime : {etat.regime} — analyse au{" "}
              {fmtDate(etat.aujourd_hui)}
            </span>
          )}
          <button type="button" className="btn btn-ghost btn-sm" onClick={onFermer}>
            Fermer
          </button>
        </div>
      </div>
      {busy && <p className="muted">Analyse du civisme déclaratif…</p>}
      {err && (
        <p className="rest-lettre-err" role="alert">
          Civisme déclaratif indisponible : {err}
        </p>
      )}
      {etat && (
        <>
          <div className="rest-prescription-synthese">
            <div className="rest-prescription-stat">
              <span className="rest-prescription-stat-val">
                {fmtTaux(etat.synthese.taux_civisme)}
              </span>
              <span className="rest-prescription-stat-lbl">
                Taux de civisme
              </span>
            </div>
            <div className="rest-prescription-stat civisme-stat--couverte">
              <span className="rest-prescription-stat-val">
                {etat.synthese.couvertes}
              </span>
              <span className="rest-prescription-stat-lbl">
                Couverte{etat.synthese.couvertes > 1 ? "s" : ""}
              </span>
            </div>
            <div className="rest-prescription-stat rest-prescription-stat--prescrit">
              <span className="rest-prescription-stat-val">
                {etat.synthese.manquantes}
              </span>
              <span className="rest-prescription-stat-lbl">
                Manquante{etat.synthese.manquantes > 1 ? "s" : ""}
              </span>
            </div>
            <div className="rest-prescription-stat">
              <span className="rest-prescription-stat-val">
                {etat.synthese.en_attente}
              </span>
              <span className="rest-prescription-stat-lbl">En attente</span>
            </div>
          </div>

          {etat.synthese.manquantes > 0 && (
            <div className="rest-prescription-meta civisme-reclamation">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => void reclamerPiecesManquantes()}
                disabled={reclamationBusy || Boolean(missionCloturee)}
                title={
                  missionCloturee
                    ? "Mission clôturée — réouvrez-la pour réclamer les pièces"
                    : "Ajoute un item par échéance manquante à la demande de renseignements"
                }
              >
                {reclamationBusy
                  ? "Ajout en cours…"
                  : "Réclamer les pièces manquantes au client"}
              </button>
              {missionCloturee && (
                <span className="muted">Mission clôturée — action indisponible.</span>
              )}
              {reclamation && (
                <span className="muted" role="status">
                  {reclamation.crees} ajoutée{reclamation.crees > 1 ? "s" : ""} à
                  la demande de renseignements ({reclamation.ignores_existants}{" "}
                  déjà présente{reclamation.ignores_existants > 1 ? "s" : ""})
                </span>
              )}
              {reclamationErr && (
                <span className="rest-lettre-err" role="alert">
                  {reclamationErr}
                </span>
              )}
            </div>
          )}

          {etat.rapprochement.length === 0 ? (
            <p className="muted">
              Aucune échéance théorique pour l'exercice revu — rien à
              rapprocher.
            </p>
          ) : (
            <ul className="rest-suivi-items rest-prescription-items">
              {etat.rapprochement.map((e, i) => (
                <li
                  key={`${e.impot}-${e.periode}-${e.date_limite}-${i}`}
                  className={`rest-suivi-item rest-prescription-item civisme-item--${e.statut}`}
                >
                  <div className="rest-suivi-libelle">
                    {e.impot && <span className="rest-suivi-cle">{e.impot}</span>}
                    <span className="rest-prescription-libelle">
                      {e.obligation || "—"}
                    </span>
                    <span
                      className={`rest-prescription-badge civisme-badge--${e.statut}`}
                    >
                      {LIBELLES_STATUT[e.statut] ?? e.statut}
                    </span>
                  </div>
                  <div className="rest-prescription-meta muted">
                    {e.periode && <span>Période : {e.periode}</span>}
                    <span>
                      Échéance le{" "}
                      <strong className="rest-prescription-date">
                        {fmtDate(e.date_limite)}
                      </strong>
                    </span>
                    {e.source && <span>Couverte par {e.source}</span>}
                  </div>
                </li>
              ))}
            </ul>
          )}

        </>
      )}
    </section>
  );
}
