import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Rapprochement TVA déclarée / comptabilisée — vue consultative.
 *
 * Compare la TVA des déclarations saisies par le fiscaliste (collectée
 * et déductible par période AAAA-MM) aux comptes 443x/445x de la
 * balance importée (cumul annuel). Les écarts au-delà du seuil de
 * signification sont signalés — l'humain apprécie et décide, rien ne
 * se corrige ici. La saisie d'une période (clic explicite) alimente le
 * rapprochement ; re-saisir une période remplace ses montants.
 */
type EcartTva = {
  nature: string;
  libelle: string;
  declare: string;
  comptabilise: string;
  ecart: string;
  significatif: boolean;
};

type DeclarationTva = {
  periode: string;
  tva_collectee: string;
  tva_deductible: string;
  tva_nette: string;
};

type RapprochementTvaOut = {
  mission_id: number;
  exercice: number;
  disponible: boolean;
  seuil_signification: string;
  declarations: DeclarationTva[];
  totaux_declares: {
    tva_collectee: string;
    tva_deductible: string;
    tva_nette: string;
  };
  comptabilise: {
    tva_collectee: string;
    tva_deductible: string;
    tva_nette: string;
    solde_tva_due_ou_credit: string;
    comptes: {
      compte: string;
      libelle: string;
      nature: string;
      solde: string;
    }[];
  };
  ecarts: EcartTva[];
  synthese: {
    statut: string;
    nb_periodes_declarees: number;
    nb_comptes_tva_balance: number;
    nb_ecarts_significatifs: number;
  };
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
  estLecteur?: boolean;
};

export function RapprochementTvaVue({ missionId, jeton, estLecteur }: Props) {
  const [etat, setEtat] = useState<RapprochementTvaOut | null>(null);
  const [periode, setPeriode] = useState("");
  const [collectee, setCollectee] = useState("");
  const [deductible, setDeductible] = useState("");
  const [msg, setMsg] = useState<{ texte: string; err: boolean } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<RapprochementTvaOut>(
        `/api/v1/missions/${missionId}/rapprochement-tva`,
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

  const saisir = useCallback(async () => {
    if (!jeton || !missionId || !periode) return;
    setBusy(true);
    setMsg(null);
    try {
      await api(`/api/v1/missions/${missionId}/declarations-tva`, {
        method: "POST",
        jeton,
        json: {
          periode,
          tva_collectee: collectee || "0",
          tva_deductible: deductible || "0",
        },
      });
      setPeriode("");
      setCollectee("");
      setDeductible("");
      setMsg({ texte: `Période ${periode} enregistrée.`, err: false });
      await charger();
    } catch (e) {
      setMsg({
        texte: e instanceof Error ? e.message : "Saisie impossible.",
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }, [jeton, missionId, periode, collectee, deductible, charger]);

  if (!etat) return null;
  const s = etat.synthese;
  return (
    <section className="rtva panel dense" aria-label="Rapprochement TVA">
      <div className="rtva-head">
        <h4 className="rtva-titre label-with-tip">
          Rapprochement TVA déclarée / comptabilisée
          <InfoTip
            label="Compare la TVA des déclarations saisies (collectée, déductible) aux comptes 443x/445x de la balance, en cumul annuel. Un écart au-delà du seuil de signification appelle une explication — vue consultative, l'humain décide."
            ariaLabel="Aide : rapprochement TVA"
          />
        </h4>
        <span className="rtva-synthese muted">
          {s.nb_periodes_declarees} période
          {s.nb_periodes_declarees > 1 ? "s" : ""} déclarée
          {s.nb_periodes_declarees > 1 ? "s" : ""} ·{" "}
          {s.nb_comptes_tva_balance} compte
          {s.nb_comptes_tva_balance > 1 ? "s" : ""} TVA en balance
          {s.nb_ecarts_significatifs > 0 && (
            <>
              {" "}
              ·{" "}
              <strong className="rtva-badge-ecart">
                {s.nb_ecarts_significatifs} écart
                {s.nb_ecarts_significatifs > 1 ? "s" : ""} significatif
                {s.nb_ecarts_significatifs > 1 ? "s" : ""}
              </strong>
            </>
          )}
        </span>
      </div>

      {!estLecteur && (
        <div className="rtva-saisie">
          <label className="rtva-champ">
            Période
            <input
              type="month"
              value={periode}
              onChange={(e) => setPeriode(e.target.value)}
              aria-label="Période déclarée (AAAA-MM)"
            />
          </label>
          <label className="rtva-champ">
            TVA collectée déclarée
            <input
              type="number"
              min="0"
              step="1"
              value={collectee}
              onChange={(e) => setCollectee(e.target.value)}
              placeholder="0"
              aria-label="TVA collectée déclarée (FCFA)"
            />
          </label>
          <label className="rtva-champ">
            TVA déductible déclarée
            <input
              type="number"
              min="0"
              step="1"
              value={deductible}
              onChange={(e) => setDeductible(e.target.value)}
              placeholder="0"
              aria-label="TVA déductible déclarée (FCFA)"
            />
          </label>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy || !periode}
            onClick={() => void saisir()}
          >
            Enregistrer la période
          </button>
        </div>
      )}
      {msg && (
        <p className={`status${msg.err ? " err" : ""}`} role="status">
          {msg.texte}
        </p>
      )}

      {etat.disponible ? (
        <table className="rtva-table">
          <thead>
            <tr>
              <th scope="col">Nature</th>
              <th scope="col">Déclaré (FCFA)</th>
              <th scope="col">Comptabilisé (FCFA)</th>
              <th scope="col">Écart</th>
            </tr>
          </thead>
          <tbody>
            {etat.ecarts.map((e) => (
              <tr key={e.nature}>
                <td className="rtva-nature">{e.libelle}</td>
                <td className="rtva-montant">{fmtMontant(e.declare)}</td>
                <td className="rtva-montant">
                  {fmtMontant(e.comptabilise)}
                </td>
                <td className="rtva-montant">
                  {fmtMontant(e.ecart)}
                  {e.significatif && (
                    <span className="rtva-badge-ecart"> Significatif</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="empty-state">
          Rapprochement indisponible : saisissez au moins une période
          déclarée et importez une balance portant des comptes TVA
          (443x/445x).
        </p>
      )}

      {etat.declarations.length > 0 && (
        <details className="rtva-detail">
          <summary>
            Détail déclaré par période ({etat.declarations.length})
          </summary>
          <table className="rtva-table">
            <thead>
              <tr>
                <th scope="col">Période</th>
                <th scope="col">Collectée</th>
                <th scope="col">Déductible</th>
                <th scope="col">Nette</th>
              </tr>
            </thead>
            <tbody>
              {etat.declarations.map((d) => (
                <tr key={d.periode}>
                  <td>{d.periode}</td>
                  <td className="rtva-montant">
                    {fmtMontant(d.tva_collectee)}
                  </td>
                  <td className="rtva-montant">
                    {fmtMontant(d.tva_deductible)}
                  </td>
                  <td className="rtva-montant">
                    {fmtMontant(d.tva_nette)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <p className="rtva-note muted">
        Seuil de signification : {fmtMontant(etat.seuil_signification)}{" "}
        FCFA.
      </p>
    </section>
  );
}
