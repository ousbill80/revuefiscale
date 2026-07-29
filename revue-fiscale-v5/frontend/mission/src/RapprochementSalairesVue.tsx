import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Rapprochement des impôts sur salaires — vue consultative.
 *
 * Compare la masse salariale des déclarations de salaires saisies par
 * le fiscaliste (masse brute, ITS retenu, contribution employeur par
 * période AAAA-MM) aux comptes 66x « Charges de personnel » de la
 * balance importée (cumul annuel) ; comptes 447x/42x restitués à titre
 * informatif. Une masse comptable supérieure au déclaré peut révéler
 * des salaires non déclarés — commentaire consultatif, l'humain
 * apprécie et décide, rien ne se corrige ici. La saisie d'une période
 * (clic explicite) alimente le rapprochement ; re-saisir une période
 * remplace ses montants.
 */
type EcartSalaires = {
  nature: string;
  libelle: string;
  declare: string;
  comptabilise: string;
  ecart: string;
  significatif: boolean;
  commentaire: string;
};

type DeclarationSalaires = {
  periode: string;
  masse_salariale_brute: string;
  its_retenu: string;
  contribution_employeur: string;
};

type RapprochementSalairesOut = {
  mission_id: number;
  exercice: number;
  disponible: boolean;
  seuil_signification: string;
  declarations: DeclarationSalaires[];
  totaux_declares: {
    masse_salariale_brute: string;
    its_retenu: string;
    contribution_employeur: string;
  };
  comptabilise: {
    masse_salariale: string;
    solde_etat_retenues: string;
    solde_personnel: string;
    comptes: {
      compte: string;
      libelle: string;
      nature: string;
      solde: string;
    }[];
  };
  ecarts: EcartSalaires[];
  synthese: {
    statut: string;
    nb_periodes_declarees: number;
    nb_comptes_66_balance: number;
    nb_ecarts_significatifs: number;
  };
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
  estLecteur?: boolean;
};

export function RapprochementSalairesVue({
  missionId,
  jeton,
  estLecteur,
}: Props) {
  const [etat, setEtat] = useState<RapprochementSalairesOut | null>(null);
  const [periode, setPeriode] = useState("");
  const [masse, setMasse] = useState("");
  const [its, setIts] = useState("");
  const [contribution, setContribution] = useState("");
  const [msg, setMsg] = useState<{ texte: string; err: boolean } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<RapprochementSalairesOut>(
        `/api/v1/missions/${missionId}/rapprochement-salaires`,
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
      await api(`/api/v1/missions/${missionId}/declarations-salaires`, {
        method: "POST",
        jeton,
        json: {
          periode,
          masse_salariale_brute: masse || "0",
          its_retenu: its || "0",
          contribution_employeur: contribution || "0",
        },
      });
      setPeriode("");
      setMasse("");
      setIts("");
      setContribution("");
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
  }, [jeton, missionId, periode, masse, its, contribution, charger]);

  if (!etat) return null;
  const s = etat.synthese;
  return (
    <section
      className="rtva panel dense"
      aria-label="Rapprochement des impôts sur salaires"
    >
      <div className="rtva-head">
        <h4 className="rtva-titre label-with-tip">
          Rapprochement impôts sur salaires déclarés / comptabilisés
          <InfoTip
            label="Compare la masse salariale des déclarations de salaires saisies (masse brute, ITS retenu, contribution employeur) aux comptes 66x « Charges de personnel » de la balance, en cumul annuel ; comptes 447x/42x restitués à titre informatif. Un écart au-delà du seuil de signification appelle une explication — vue consultative, l'humain décide."
            ariaLabel="Aide : rapprochement des impôts sur salaires"
          />
        </h4>
        <span className="rtva-synthese muted">
          {s.nb_periodes_declarees} période
          {s.nb_periodes_declarees > 1 ? "s" : ""} déclarée
          {s.nb_periodes_declarees > 1 ? "s" : ""} ·{" "}
          {s.nb_comptes_66_balance} compte
          {s.nb_comptes_66_balance > 1 ? "s" : ""} 66x en balance
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
            Masse salariale brute déclarée
            <input
              type="number"
              min="0"
              step="1"
              value={masse}
              onChange={(e) => setMasse(e.target.value)}
              placeholder="0"
              aria-label="Masse salariale brute déclarée (FCFA)"
            />
          </label>
          <label className="rtva-champ">
            ITS retenu (part salariale)
            <input
              type="number"
              min="0"
              step="1"
              value={its}
              onChange={(e) => setIts(e.target.value)}
              placeholder="0"
              aria-label="ITS retenu déclaré (FCFA)"
            />
          </label>
          <label className="rtva-champ">
            Contribution employeur
            <input
              type="number"
              min="0"
              step="1"
              value={contribution}
              onChange={(e) => setContribution(e.target.value)}
              placeholder="0"
              aria-label="Contribution employeur déclarée (FCFA)"
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
        <>
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
                      <span className="rtva-badge-ecart">
                        {" "}
                        Significatif
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {etat.ecarts
            .filter((e) => e.commentaire)
            .map((e) => (
              <p key={`${e.nature}-commentaire`} className="rtva-note muted">
                {e.commentaire}
              </p>
            ))}
          <p className="rtva-note muted">
            Informatif — ITS retenu déclaré (cumul) :{" "}
            {fmtMontant(etat.totaux_declares.its_retenu)} · contribution
            employeur déclarée (cumul) :{" "}
            {fmtMontant(etat.totaux_declares.contribution_employeur)} ·
            solde 447x (État, impôts retenus à la source) :{" "}
            {fmtMontant(etat.comptabilise.solde_etat_retenues)} · solde
            42x (Personnel) :{" "}
            {fmtMontant(etat.comptabilise.solde_personnel)}
          </p>
        </>
      ) : (
        <p className="empty-state">
          Rapprochement indisponible : saisissez au moins une période
          déclarée et importez une balance portant des comptes de
          charges de personnel (66x).
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
                <th scope="col">Masse brute</th>
                <th scope="col">ITS retenu</th>
                <th scope="col">Contribution employeur</th>
              </tr>
            </thead>
            <tbody>
              {etat.declarations.map((d) => (
                <tr key={d.periode}>
                  <td>{d.periode}</td>
                  <td className="rtva-montant">
                    {fmtMontant(d.masse_salariale_brute)}
                  </td>
                  <td className="rtva-montant">
                    {fmtMontant(d.its_retenu)}
                  </td>
                  <td className="rtva-montant">
                    {fmtMontant(d.contribution_employeur)}
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
