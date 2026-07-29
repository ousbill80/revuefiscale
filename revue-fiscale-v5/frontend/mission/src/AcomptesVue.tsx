import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Suivi des acomptes IS et position de solde — vue consultative.
 *
 * Le fiscaliste saisit les versements d'impôt de l'exercice (acomptes
 * IS, retenues à la source, crédits reportés — date, montant,
 * référence de quittance facultative) et l'IS dû estimé (le moteur
 * n'expose pas d'IS estimé). Le module projette la position (solde à
 * payer ou crédit d'impôt à reporter, signalée si importante) et
 * restitue les comptes 441x/444x de la balance à titre informatif —
 * l'humain liquide et décide, rien ne se corrige ici. Re-saisir une
 * même nature à la même date remplace le montant.
 */
type AcompteLigne = {
  id: number | null;
  nature: string;
  libelle_nature: string;
  date_versement: string;
  montant: string;
  reference_quittance: string | null;
};

type AcomptesOut = {
  mission_id: number;
  exercice: number;
  disponible: boolean;
  seuil_solde_residuel: string;
  acomptes: AcompteLigne[];
  totaux_verses: {
    acompte_is: string;
    retenue_source: string;
    credit_reporte: string;
    total: string;
  };
  is_du_estime: string | null;
  is_du_source: string;
  position: {
    statut: string;
    libelle: string;
    montant: string;
    solde_signe: string;
    solde_important: boolean;
  };
  balance: {
    solde_441x: string;
    solde_444x: string;
    comptes: {
      compte: string;
      libelle: string;
      prefixe: string;
      solde: string;
    }[];
  };
  synthese: {
    statut: string;
    nb_versements: number;
    nb_comptes_impot_balance: number;
    solde_important: boolean;
  };
  note: string;
};

const NATURES_VERSEMENT = [
  { valeur: "acompte_is", libelle: "Acompte IS" },
  { valeur: "retenue_source", libelle: "Retenue à la source" },
  { valeur: "credit_reporte", libelle: "Crédit d'impôt reporté" },
] as const;

const LIBELLES_NATURE: Record<string, string> = {
  acompte_is: "Acomptes IS versés",
  retenue_source: "Retenues à la source subies",
  credit_reporte: "Crédits d'impôt reportés",
};

type Props = {
  missionId: number;
  jeton?: string | null;
  estLecteur?: boolean;
};

export function AcomptesVue({ missionId, jeton, estLecteur }: Props) {
  const [etat, setEtat] = useState<AcomptesOut | null>(null);
  const [nature, setNature] = useState<string>("acompte_is");
  const [dateVersement, setDateVersement] = useState("");
  const [montant, setMontant] = useState("");
  const [reference, setReference] = useState("");
  const [duEstime, setDuEstime] = useState("");
  const [msg, setMsg] = useState<{ texte: string; err: boolean } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<AcomptesOut>(
        `/api/v1/missions/${missionId}/acomptes`,
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

  const saisirVersement = useCallback(async () => {
    if (!jeton || !missionId || !dateVersement) return;
    setBusy(true);
    setMsg(null);
    try {
      await api(`/api/v1/missions/${missionId}/acomptes`, {
        method: "POST",
        jeton,
        json: {
          nature,
          date_versement: dateVersement,
          montant: montant || "0",
          reference_quittance: reference || null,
        },
      });
      setDateVersement("");
      setMontant("");
      setReference("");
      setMsg({ texte: "Versement enregistré.", err: false });
      await charger();
    } catch (e) {
      setMsg({
        texte: e instanceof Error ? e.message : "Saisie impossible.",
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }, [jeton, missionId, nature, dateVersement, montant, reference, charger]);

  const saisirDuEstime = useCallback(async () => {
    if (!jeton || !missionId || duEstime === "") return;
    setBusy(true);
    setMsg(null);
    try {
      await api(`/api/v1/missions/${missionId}/acomptes`, {
        method: "POST",
        jeton,
        json: { nature: "is_du_estime", montant: duEstime },
      });
      setDuEstime("");
      setMsg({ texte: "IS dû estimé enregistré.", err: false });
      await charger();
    } catch (e) {
      setMsg({
        texte: e instanceof Error ? e.message : "Saisie impossible.",
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }, [jeton, missionId, duEstime, charger]);

  if (!etat) return null;
  const s = etat.synthese;
  return (
    <section className="rtva panel dense" aria-label="Acomptes IS">
      <div className="rtva-head">
        <h4 className="rtva-titre label-with-tip">
          Acomptes IS et position de solde
          <InfoTip
            label="Totalise les versements d'impôt saisis (acomptes IS, retenues à la source, crédits reportés) et les rapproche de l'IS dû estimé saisi par le fiscaliste pour projeter la position : solde à payer ou crédit d'impôt à reporter. Les comptes 441x/444x de la balance sont informatifs — vue consultative, l'humain décide."
            ariaLabel="Aide : acomptes IS"
          />
        </h4>
        <span className="rtva-synthese muted">
          {s.nb_versements} versement{s.nb_versements > 1 ? "s" : ""} ·{" "}
          {s.nb_comptes_impot_balance} compte
          {s.nb_comptes_impot_balance > 1 ? "s" : ""} d'impôt en balance
          {s.solde_important && (
            <>
              {" "}
              ·{" "}
              <strong className="rtva-badge-ecart">
                Solde résiduel important
              </strong>
            </>
          )}
        </span>
      </div>

      {!estLecteur && (
        <>
          <div className="rtva-saisie">
            <label className="rtva-champ">
              Nature
              <select
                value={nature}
                onChange={(e) => setNature(e.target.value)}
                aria-label="Nature du versement"
              >
                {NATURES_VERSEMENT.map((n) => (
                  <option key={n.valeur} value={n.valeur}>
                    {n.libelle}
                  </option>
                ))}
              </select>
            </label>
            <label className="rtva-champ">
              Date du versement
              <input
                type="date"
                value={dateVersement}
                onChange={(e) => setDateVersement(e.target.value)}
                aria-label="Date du versement (AAAA-MM-JJ)"
              />
            </label>
            <label className="rtva-champ">
              Montant versé
              <input
                type="number"
                min="0"
                step="1"
                value={montant}
                onChange={(e) => setMontant(e.target.value)}
                placeholder="0"
                aria-label="Montant versé (FCFA)"
              />
            </label>
            <label className="rtva-champ">
              Réf. quittance (facultative)
              <input
                type="text"
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                placeholder="Q-2025-…"
                aria-label="Référence de quittance (facultative)"
              />
            </label>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy || !dateVersement}
              onClick={() => void saisirVersement()}
            >
              Enregistrer le versement
            </button>
          </div>
          <div className="rtva-saisie">
            <label className="rtva-champ">
              IS dû estimé de l'exercice (saisi par le fiscaliste)
              <input
                type="number"
                min="0"
                step="1"
                value={duEstime}
                onChange={(e) => setDuEstime(e.target.value)}
                placeholder={etat.is_du_estime ?? "0"}
                aria-label="IS dû estimé (FCFA)"
              />
            </label>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy || duEstime === ""}
              onClick={() => void saisirDuEstime()}
            >
              Enregistrer l'IS dû estimé
            </button>
          </div>
        </>
      )}
      {msg && (
        <p className={`status${msg.err ? " err" : ""}`} role="status">
          {msg.texte}
        </p>
      )}

      <table className="rtva-table">
        <thead>
          <tr>
            <th scope="col">Nature</th>
            <th scope="col">Total versé (FCFA)</th>
          </tr>
        </thead>
        <tbody>
          {(["acompte_is", "retenue_source", "credit_reporte"] as const).map(
            (n) => (
              <tr key={n}>
                <td className="rtva-nature">{LIBELLES_NATURE[n]}</td>
                <td className="rtva-montant">
                  {fmtMontant(etat.totaux_verses[n])}
                </td>
              </tr>
            ),
          )}
          <tr>
            <td className="rtva-nature">
              <strong>Total versé</strong>
            </td>
            <td className="rtva-montant">
              <strong>{fmtMontant(etat.totaux_verses.total)}</strong>
            </td>
          </tr>
        </tbody>
      </table>

      {etat.disponible ? (
        <p className="rtva-note">
          IS dû estimé : {fmtMontant(etat.is_du_estime ?? "0")} FCFA —{" "}
          <strong>
            {etat.position.libelle} : {fmtMontant(etat.position.montant)}{" "}
            FCFA
          </strong>
          {etat.position.solde_important && (
            <span className="rtva-badge-ecart"> Important</span>
          )}
        </p>
      ) : (
        <p className="empty-state">
          Position indisponible : saisissez l'IS dû estimé de l'exercice
          (le moteur n'expose pas d'IS estimé) — les totaux versés
          restent chiffrés ci-dessus.
        </p>
      )}

      {etat.acomptes.length > 0 && (
        <details className="rtva-detail">
          <summary>
            Détail des versements saisis ({etat.acomptes.length})
          </summary>
          <table className="rtva-table">
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Nature</th>
                <th scope="col">Montant</th>
                <th scope="col">Réf. quittance</th>
              </tr>
            </thead>
            <tbody>
              {etat.acomptes.map((a) => (
                <tr key={`${a.nature}-${a.date_versement}`}>
                  <td>{a.date_versement}</td>
                  <td className="rtva-nature">{a.libelle_nature}</td>
                  <td className="rtva-montant">{fmtMontant(a.montant)}</td>
                  <td>{a.reference_quittance ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {etat.balance.comptes.length > 0 && (
        <details className="rtva-detail">
          <summary>
            Comptes d'impôt en balance — informatif (
            {etat.balance.comptes.length})
          </summary>
          <table className="rtva-table">
            <thead>
              <tr>
                <th scope="col">Compte</th>
                <th scope="col">Libellé</th>
                <th scope="col">Solde créditeur net</th>
              </tr>
            </thead>
            <tbody>
              {etat.balance.comptes.map((c) => (
                <tr key={c.compte}>
                  <td>{c.compte}</td>
                  <td className="rtva-nature">{c.libelle}</td>
                  <td className="rtva-montant">{fmtMontant(c.solde)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">
            441x (État, impôt sur les bénéfices) :{" "}
            {fmtMontant(etat.balance.solde_441x)} FCFA · 444x :{" "}
            {fmtMontant(etat.balance.solde_444x)} FCFA — soldes annuels
            mêlant acomptes et liquidations.
          </p>
        </details>
      )}

      <p className="rtva-note muted">
        Seuil de solde résiduel : {fmtMontant(etat.seuil_solde_residuel)}{" "}
        FCFA.
      </p>
    </section>
  );
}
