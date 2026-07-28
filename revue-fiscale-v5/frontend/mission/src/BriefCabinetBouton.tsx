import { useState } from "react";
import { telecharger } from "./api";

/** Bouton « Brief du cabinet (.txt) » (GET /api/v1/cabinet/brief.txt).
 *
 * Un seul document texte pour la réunion hebdomadaire : centre
 * d'alertes + calendrier fiscal + portefeuille déclaratif, assemblés
 * côté serveur — rien ne part par email, tout reste consultatif.
 */
type Props = {
  jeton?: string | null;
};

export function BriefCabinetBouton({ jeton }: Props) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function telechargerBrief() {
    if (!jeton || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const jour = new Date().toISOString().slice(0, 10);
      await telecharger(
        "/api/v1/cabinet/brief.txt",
        jeton,
        `brief-cabinet-${jour}.txt`,
      );
    } catch (e) {
      setErr(
        e instanceof Error ? e.message : "téléchargement impossible",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ctrale-exports" aria-label="Brief du cabinet">
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        onClick={() => void telechargerBrief()}
        disabled={busy}
        title="Un seul document texte pour la réunion hebdomadaire : alertes, calendrier et portefeuille déclaratif"
      >
        Brief du cabinet (.txt)
      </button>
      {err && <span className="ctrale-err">{err}</span>}
    </div>
  );
}
