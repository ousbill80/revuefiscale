/** Registre des risques d'un contribuable — post-mission (docs/25). */
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, apiUpload, telecharger } from "./api";
import { TexteJuridique } from "./TexteJuridique";

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

export type PreuveResolutionRow = {
  id: number;
  risque_id: number;
  nom_fichier: string;
  format: string;
  verdict_ia: "probante" | "insuffisante" | "sans_rapport" | "indisponible" | null;
  justification_ia: string | null;
  decision: "acceptee" | "forcee" | null;
  motif_forcage: string | null;
  auteur: string | null;
  cree_le: string | null;
};

const LIBELLES_VERDICT: Record<string, string> = {
  probante: "Probante",
  insuffisante: "Insuffisante",
  sans_rapport: "Sans rapport",
  indisponible: "Indisponible",
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
  /** Fourchette du niveau (ex. « 20–39 ») — fournie par le moteur ; absente si « aucun ». */
  plage?: string | null;
  facteurs: { code: string; libelle: string; points: number; detail: string }[];
  alertes: string[];
  exposition_totale: string;
};

/**
 * Texte d’interprétation du score registre (pastille fiche client).
 * Plages uniquement si le moteur les renvoie — pas de seuils inventés côté UI.
 */
export function tipInterpretationScoreRisque(s: ScoreRisque): string {
  if (s.niveau === "aucun") {
    return [
      "Aucun risque ouvert dans le registre.",
      "Score d’exposition agrégée : 0/100 (risques non clos, enjeu, suivi).",
      "Ouvrir l’onglet Risques pour consulter le registre.",
    ].join("\n");
  }
  const plage =
    typeof s.plage === "string" && s.plage.trim() ? ` (${s.plage})` : "";
  const suite =
    s.alertes.length > 0
      ? "Ouvrir Risques : traiter les points ouverts et les actions signalées."
      : "Ouvrir l’onglet Risques pour suivre et traiter les points ouverts.";
  return [
    `Score ${s.score}/100 — ${s.libelle_niveau}${plage}.`,
    "Exposition agrégée du registre : risques non clos, enjeu financier et qualité du suivi.",
    suite,
  ].join("\n");
}

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
  const [exportEnCours, setExportEnCours] = useState(false);

  const [preuveRisqueId, setPreuveRisqueId] = useState<number | null>(null);
  const [preuveFichier, setPreuveFichier] = useState<File | null>(null);
  const [preuveAnalyseEnCours, setPreuveAnalyseEnCours] = useState(false);
  const [preuve, setPreuve] = useState<PreuveResolutionRow | null>(null);
  const [motifForcage, setMotifForcage] = useState("");
  const [resolutionEnCours, setResolutionEnCours] = useState(false);
  const [preuvesVuesId, setPreuvesVuesId] = useState<number | null>(null);
  const [preuvesVues, setPreuvesVues] = useState<PreuveResolutionRow[]>([]);

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

  async function exporterCsv() {
    setExportEnCours(true);
    setErr(null);
    try {
      const jour = new Date().toISOString().slice(0, 10);
      await telecharger(
        `/api/v1/contribuables/${contribuableId}/risques/export.csv`,
        jeton,
        `risques_client_${contribuableId}_${jour}.csv`,
      );
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setExportEnCours(false);
    }
  }

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

  function ouvrirPanneauPreuve(risqueId: number) {
    if (estLecteur) return;
    setPreuveRisqueId((prev) => (prev === risqueId ? null : risqueId));
    setPreuveFichier(null);
    setPreuve(null);
    setMotifForcage("");
  }

  async function analyserPreuve(risqueId: number) {
    if (estLecteur || !preuveFichier) return;
    setPreuveAnalyseEnCours(true);
    setErr(null);
    try {
      const p = await apiUpload<PreuveResolutionRow>(
        `/api/v1/risques/${risqueId}/preuves`,
        preuveFichier,
        jeton,
      );
      setPreuve(p);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPreuveAnalyseEnCours(false);
    }
  }

  async function resoudreAvecPreuve(risqueId: number) {
    if (estLecteur || !preuve) return;
    const forcage = preuve.verdict_ia !== "probante";
    if (forcage && !motifForcage.trim()) return;
    setResolutionEnCours(true);
    setErr(null);
    try {
      await api(`/api/v1/risques/${risqueId}/resolution`, {
        method: "POST",
        jeton,
        json: {
          preuve_id: preuve.id,
          motif_forcage: forcage ? motifForcage.trim() : null,
        },
      });
      setPreuveRisqueId(null);
      setPreuveFichier(null);
      setPreuve(null);
      setMotifForcage("");
      await charger();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setResolutionEnCours(false);
    }
  }

  async function voirPreuves(risqueId: number) {
    if (preuvesVuesId === risqueId) {
      setPreuvesVuesId(null);
      setPreuvesVues([]);
      return;
    }
    setErr(null);
    try {
      const list = await api<PreuveResolutionRow[]>(
        `/api/v1/risques/${risqueId}/preuves`,
        { jeton },
      );
      setPreuvesVuesId(risqueId);
      setPreuvesVues(Array.isArray(list) ? list : []);
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
        <div className="registre-actions-row">
          <button
            type="button"
            className="btn ghost btn-xs"
            onClick={() => void exporterCsv()}
            disabled={exportEnCours || risques.length === 0}
          >
            {exportEnCours ? "Export…" : "Exporter CSV"}
          </button>
          <button
            type="button"
            className="btn ghost btn-xs"
            onClick={() => void charger()}
            disabled={busy}
          >
            Actualiser
          </button>
        </div>
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
                  <li key={a}>
                    <TexteJuridique texte={a} />
                  </li>
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
                  <strong>
                    <TexteJuridique texte={r.libelle} />
                  </strong>
                  <span className="muted">{fmtMontant(r.montant_estime)}</span>
                </div>
                {r.reference_legale && (
                  <p className="muted small">
                    Réf. <TexteJuridique texte={r.reference_legale} />
                  </p>
                )}
                {!estLecteur && (
                  <div className="registre-actions-row">
                    <select
                      value={r.statut}
                      onChange={(e) => {
                        const st = e.target.value;
                        if (st === "resolu") {
                          ouvrirPanneauPreuve(r.id);
                          return;
                        }
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
                    {r.statut !== "resolu" && (
                      <button
                        type="button"
                        className="btn ghost btn-xs"
                        onClick={() => ouvrirPanneauPreuve(r.id)}
                      >
                        {preuveRisqueId === r.id
                          ? "Annuler la résolution"
                          : "Résoudre (preuve)"}
                      </button>
                    )}
                  </div>
                )}
                {r.statut === "resolu" && (
                  <button
                    type="button"
                    className="btn ghost btn-xs"
                    onClick={() => void voirPreuves(r.id)}
                  >
                    {preuvesVuesId === r.id
                      ? "Masquer les preuves"
                      : "Preuves de résolution"}
                  </button>
                )}
                {preuvesVuesId === r.id && (
                  <ul className="registre-preuve-liste">
                    {preuvesVues.length === 0 && (
                      <li className="muted">Aucune preuve enregistrée.</li>
                    )}
                    {preuvesVues.map((p) => (
                      <li key={p.id}>
                        <span
                          className={`registre-preuve-verdict verdict-${p.verdict_ia ?? "indisponible"}`}
                        >
                          {LIBELLES_VERDICT[p.verdict_ia ?? "indisponible"] ??
                            p.verdict_ia}
                        </span>{" "}
                        <strong>{p.nom_fichier}</strong>
                        {p.decision && (
                          <span className="muted">
                            {" "}
                            · décision{" "}
                            {p.decision === "forcee" ? "forcée" : "acceptée"}
                            {p.motif_forcage ? ` — ${p.motif_forcage}` : ""}
                          </span>
                        )}
                        {p.cree_le && (
                          <span className="muted small">
                            {" "}
                            · {p.cree_le.slice(0, 10)}
                          </span>
                        )}
                        {p.justification_ia && (
                          <p className="muted small">{p.justification_ia}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                {!estLecteur && preuveRisqueId === r.id && (
                  <div className="registre-preuve-panneau">
                    <p className="registre-preuve-titre">
                      <strong>Preuve de résolution</strong> — justificatif
                      obligatoire (PDF, PNG, JPEG ou WEBP — 25 Mo max)
                    </p>
                    <div className="registre-preuve-actions">
                      <input
                        type="file"
                        accept=".pdf,.png,.jpg,.jpeg,.webp"
                        onChange={(e) => {
                          setPreuveFichier(e.target.files?.[0] ?? null);
                          setPreuve(null);
                        }}
                      />
                      <button
                        type="button"
                        className="btn btn-primary btn-xs"
                        disabled={!preuveFichier || preuveAnalyseEnCours}
                        onClick={() => void analyserPreuve(r.id)}
                      >
                        {preuveAnalyseEnCours
                          ? "Analyse en cours…"
                          : "Analyser la preuve"}
                      </button>
                    </div>
                    {preuve && (
                      <div className="registre-preuve-resultat">
                        <span
                          className={`registre-preuve-verdict verdict-${preuve.verdict_ia ?? "indisponible"}`}
                        >
                          {LIBELLES_VERDICT[
                            preuve.verdict_ia ?? "indisponible"
                          ] ?? preuve.verdict_ia}
                        </span>
                        {preuve.justification_ia && (
                          <p className="registre-preuve-justification">
                            {preuve.justification_ia}
                          </p>
                        )}
                        <p className="registre-preuve-bandeau">
                          Verdict consultatif généré par IA — la décision vous
                          appartient.
                        </p>
                        {preuve.verdict_ia === "probante" ? (
                          <button
                            type="button"
                            className="btn btn-primary btn-xs"
                            disabled={resolutionEnCours}
                            onClick={() => void resoudreAvecPreuve(r.id)}
                          >
                            {resolutionEnCours
                              ? "Résolution…"
                              : "Confirmer la résolution"}
                          </button>
                        ) : (
                          <>
                            <textarea
                              className="registre-preuve-motif"
                              placeholder="Motif de résolution malgré le verdict (obligatoire)"
                              value={motifForcage}
                              onChange={(e) => setMotifForcage(e.target.value)}
                            />
                            <button
                              type="button"
                              className="btn btn-xs registre-preuve-forcer"
                              disabled={
                                resolutionEnCours || !motifForcage.trim()
                              }
                              onClick={() => void resoudreAvecPreuve(r.id)}
                            >
                              {resolutionEnCours
                                ? "Résolution…"
                                : "Forcer la résolution"}
                            </button>
                          </>
                        )}
                      </div>
                    )}
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
