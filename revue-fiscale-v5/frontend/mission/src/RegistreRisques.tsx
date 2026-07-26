/** Registre des risques d'un contribuable — post-mission (docs/25). */
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";

export type RisqueRow = {
  id: number;
  contribuable_id: number;
  impot: string;
  libelle: string;
  montant_estime: string | null;
  probabilite: string;
  statut: string;
  exercice_origine: number;
  reference_legale?: string | null;
  motif_acceptation?: string | null;
};

export type ActionRisqueRow = {
  id: number;
  risque_id: number;
  nature: string;
  libelle: string;
  statut: string;
  echeance: string | null;
  motif_refus?: string | null;
  en_retard?: boolean;
  responsable_label?: string | null;
};

export type ScoreRisque = {
  score: number;
  niveau: "aucun" | "faible" | "modere" | "eleve" | "critique";
  libelle_niveau: string;
  facteurs: { code: string; libelle: string; points: number; detail: string }[];
  alertes: string[];
  exposition_totale: string;
};

type Props = {
  jeton: string;
  contribuableId: number;
  estLecteur?: boolean;
};

const STATUTS_RISQUE = [
  { value: "ouvert", label: "Ouvert" },
  { value: "en_traitement", label: "En traitement" },
  { value: "resolu", label: "Résolu" },
  { value: "accepte", label: "Accepté (client)" },
  { value: "prescrit", label: "Prescrit" },
] as const;

function fmtMontant(v: string | null | undefined): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString("fr-FR", { maximumFractionDigits: 0 }) + " FCFA";
}

export function RegistreRisquesVue({
  jeton,
  contribuableId,
  estLecteur,
}: Props) {
  const [risques, setRisques] = useState<RisqueRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ouvertId, setOuvertId] = useState<number | null>(null);
  const [actions, setActions] = useState<ActionRisqueRow[]>([]);
  const [motifAccepte, setMotifAccepte] = useState("");
  const [nouvelleAction, setNouvelleAction] = useState({
    nature: "corrective" as "corrective" | "preventive",
    libelle: "",
    echeance: "",
  });

  const [score, setScore] = useState<ScoreRisque | null>(null);

  const charger = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const list = await api<RisqueRow[]>(
        `/api/v1/contribuables/${contribuableId}/risques`,
        { jeton },
      );
      setRisques(Array.isArray(list) ? list : []);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setRisques([]);
    } finally {
      setBusy(false);
    }
    // Score : silencieux si l'API échoue.
    try {
      const s = await api<ScoreRisque>(
        `/api/v1/contribuables/${contribuableId}/risques/score`,
        { jeton },
      );
      setScore(s && typeof s.score === "number" ? s : null);
    } catch {
      setScore(null);
    }
  }, [contribuableId, jeton]);

  useEffect(() => {
    void charger();
  }, [charger]);

  const cumulOuverts = useMemo(() => {
    return risques
      .filter((r) => r.statut === "ouvert" || r.statut === "en_traitement")
      .reduce((acc, r) => acc + (Number(r.montant_estime) || 0), 0);
  }, [risques]);

  const parImpot = useMemo(() => {
    const m = new Map<string, RisqueRow[]>();
    for (const r of risques) {
      const k = `${r.impot} · ${r.exercice_origine}`;
      const arr = m.get(k) || [];
      arr.push(r);
      m.set(k, arr);
    }
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [risques]);

  async function patchRisque(
    id: number,
    corps: Record<string, unknown>,
  ) {
    if (estLecteur) return;
    setErr(null);
    try {
      await api(`/api/v1/risques/${id}`, {
        method: "PATCH",
        jeton,
        json: corps,
      });
      await charger();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function ouvrirActions(risqueId: number) {
    if (ouvertId === risqueId) {
      setOuvertId(null);
      setActions([]);
      return;
    }
    setOuvertId(risqueId);
    try {
      const list = await api<ActionRisqueRow[]>(
        `/api/v1/risques/${risqueId}/actions`,
        { jeton },
      );
      setActions(Array.isArray(list) ? list : []);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setActions([]);
    }
  }

  async function creerAction(risqueId: number) {
    if (estLecteur || !nouvelleAction.libelle.trim()) return;
    try {
      await api(`/api/v1/risques/${risqueId}/actions`, {
        method: "POST",
        jeton,
        json: {
          nature: nouvelleAction.nature,
          libelle: nouvelleAction.libelle.trim(),
          echeance: nouvelleAction.echeance || null,
        },
      });
      setNouvelleAction({ nature: "corrective", libelle: "", echeance: "" });
      const list = await api<ActionRisqueRow[]>(
        `/api/v1/risques/${risqueId}/actions`,
        { jeton },
      );
      setActions(Array.isArray(list) ? list : []);
      await charger();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function patchAction(
    actionId: number,
    corps: Record<string, unknown>,
  ) {
    if (estLecteur) return;
    try {
      await api(`/api/v1/actions-risque/${actionId}`, {
        method: "PATCH",
        jeton,
        json: corps,
      });
      if (ouvertId != null) {
        const list = await api<ActionRisqueRow[]>(
          `/api/v1/risques/${ouvertId}/actions`,
          { jeton },
        );
        setActions(Array.isArray(list) ? list : []);
      }
      await charger();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <section className="registre-risques" aria-label="Registre des risques">
      <header className="registre-risques-head">
        <div>
          <h3>Registre des risques</h3>
          <p className="muted">
            Survit aux missions — cumul ouvert :{" "}
            <strong>{fmtMontant(String(cumulOuverts))}</strong>
          </p>
        </div>
        <button
          type="button"
          className="btn ghost btn-xs"
          onClick={() => void charger()}
          disabled={busy}
        >
          Actualiser
        </button>
      </header>
      {score && (
        <div
          className={`risques-score-carte niveau-${score.niveau}`}
          aria-label="Score de risque du client"
        >
          <div className="risques-score-head">
            <span className={`risques-score-badge niveau-${score.niveau}`}>
              {score.libelle_niveau}
            </span>
            <strong className="risques-score-valeur">
              {score.score}/100
            </strong>
            <span className="muted small">
              Exposition : {fmtMontant(score.exposition_totale)}
            </span>
          </div>
          <div
            className="risques-score-jauge"
            role="progressbar"
            aria-valuenow={score.score}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className={`risques-score-jauge-remplie niveau-${score.niveau}`}
              style={{ width: `${Math.min(score.score, 100)}%` }}
            />
          </div>
          {score.facteurs.some((f) => f.points > 0) && (
            <ul className="risques-score-facteurs">
              {score.facteurs
                .filter((f) => f.points > 0)
                .map((f) => (
                  <li key={f.code}>
                    {f.libelle} — <strong>+{f.points} pts</strong>{" "}
                    <span className="muted">({f.detail})</span>
                  </li>
                ))}
            </ul>
          )}
          {score.alertes.length > 0 && (
            <div className="risques-score-alertes">
              <p className="risques-score-alertes-titre">
                Actions recommandées
              </p>
              <ul>
                {score.alertes.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      {err && <p className="status err">{err}</p>}
      {risques.length === 0 && !busy && (
        <p className="muted">
          Aucun risque enregistré. Les anomalies clôturées en génèrent
          automatiquement.
        </p>
      )}
      {parImpot.map(([cle, list]) => (
        <details key={cle} className="registre-groupe" open>
          <summary>
            <strong>{cle}</strong> — {list.length} risque
            {list.length > 1 ? "s" : ""}
          </summary>
          <ul className="registre-liste">
            {list.map((r) => (
              <li key={r.id} className={`registre-item statut-${r.statut}`}>
                <div className="registre-item-main">
                  <span className="badge">{r.statut}</span>
                  <span className="badge ghost">{r.probabilite}</span>
                  <strong>{r.libelle}</strong>
                  <span className="muted">{fmtMontant(r.montant_estime)}</span>
                </div>
                {r.reference_legale && (
                  <p className="muted small">Réf. {r.reference_legale}</p>
                )}
                {!estLecteur && (
                  <div className="registre-actions-row">
                    <select
                      value={r.statut}
                      onChange={(e) => {
                        const st = e.target.value;
                        if (st === "accepte") {
                          const motif =
                            motifAccepte.trim() ||
                            window.prompt(
                              "Motif d'acceptation du risque par le client ?",
                            );
                          if (!motif) return;
                          void patchRisque(r.id, {
                            statut: st,
                            motif_acceptation: motif,
                          });
                          return;
                        }
                        void patchRisque(r.id, { statut: st });
                      }}
                    >
                      {STATUTS_RISQUE.map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="btn ghost btn-xs"
                      onClick={() => void ouvrirActions(r.id)}
                    >
                      {ouvertId === r.id ? "Masquer actions" : "Actions"}
                    </button>
                  </div>
                )}
                {ouvertId === r.id && (
                  <div className="registre-actions-panel">
                    <ul>
                      {actions.map((a) => (
                        <li key={a.id}>
                          <span className="badge">{a.nature}</span>
                          <span className="badge">{a.statut}</span>
                          {a.en_retard && (
                            <span className="badge warn">En retard</span>
                          )}
                          {a.libelle}
                          {a.echeance ? ` · éch. ${a.echeance}` : ""}
                          {!estLecteur && a.statut === "proposee" && (
                            <>
                              {" "}
                              <button
                                type="button"
                                className="btn ghost btn-xs"
                                onClick={() =>
                                  void patchAction(a.id, {
                                    statut: "acceptee",
                                  })
                                }
                              >
                                Accepter
                              </button>
                              <button
                                type="button"
                                className="btn ghost btn-xs"
                                onClick={() => {
                                  const m = window.prompt("Motif du refus ?");
                                  if (!m) return;
                                  void patchAction(a.id, {
                                    statut: "refusee",
                                    motif_refus: m,
                                  });
                                }}
                              >
                                Refuser
                              </button>
                            </>
                          )}
                          {!estLecteur && a.statut === "acceptee" && (
                            <button
                              type="button"
                              className="btn ghost btn-xs"
                              onClick={() =>
                                void patchAction(a.id, { statut: "en_cours" })
                              }
                            >
                              Démarrer
                            </button>
                          )}
                          {!estLecteur && a.statut === "en_cours" && (
                            <button
                              type="button"
                              className="btn ghost btn-xs"
                              onClick={() => {
                                const uri = window.prompt(
                                  "URI / référence preuve (ou laisser vide) ?",
                                );
                                void patchAction(a.id, {
                                  statut: "preuve_deposee",
                                  preuve_uri: uri || "preuve déposée",
                                });
                              }}
                            >
                              Preuve
                            </button>
                          )}
                          {!estLecteur && a.statut === "preuve_deposee" && (
                            <button
                              type="button"
                              className="btn ghost btn-xs"
                              onClick={() => {
                                void (async () => {
                                  await patchAction(a.id, {
                                    statut: "verifiee",
                                  });
                                  await patchAction(a.id, { statut: "close" });
                                })();
                              }}
                            >
                              Vérifier & clôturer
                            </button>
                          )}
                          {!estLecteur && a.statut === "verifiee" && (
                            <button
                              type="button"
                              className="btn ghost btn-xs"
                              onClick={() =>
                                void patchAction(a.id, { statut: "close" })
                              }
                            >
                              Clôturer
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                    {!estLecteur && (
                      <div className="registre-new-action">
                        <select
                          value={nouvelleAction.nature}
                          onChange={(e) =>
                            setNouvelleAction((s) => ({
                              ...s,
                              nature: e.target.value as
                                | "corrective"
                                | "preventive",
                            }))
                          }
                        >
                          <option value="corrective">Corrective</option>
                          <option value="preventive">Préventive</option>
                        </select>
                        <input
                          type="text"
                          placeholder="Libellé action"
                          value={nouvelleAction.libelle}
                          onChange={(e) =>
                            setNouvelleAction((s) => ({
                              ...s,
                              libelle: e.target.value,
                            }))
                          }
                        />
                        <input
                          type="date"
                          value={nouvelleAction.echeance}
                          onChange={(e) =>
                            setNouvelleAction((s) => ({
                              ...s,
                              echeance: e.target.value,
                            }))
                          }
                        />
                        <button
                          type="button"
                          className="btn btn-primary btn-xs"
                          onClick={() => void creerAction(r.id)}
                        >
                          Ajouter
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </details>
      ))}
      {!estLecteur && risques.length > 0 && (
        <p className="muted small">
          Motif acceptation (prérempli pour « Accepté ») :{" "}
          <input
            type="text"
            value={motifAccepte}
            onChange={(e) => setMotifAccepte(e.target.value)}
            placeholder="Client assume le risque…"
            style={{ minWidth: "16rem" }}
          />
        </p>
      )}
    </section>
  );
}

export type ResumeRisques = {
  total: number;
  ouverts: number;
  traites: number;
  acceptes_client: number;
  actions_en_retard: number;
  actions_refusees: number;
};
