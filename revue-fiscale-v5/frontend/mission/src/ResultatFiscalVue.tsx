import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Tableau de passage résultat comptable → résultat fiscal — consultatif.
 *
 * Le résultat comptable est calculé de la balance (classes 6/7, HAO 8x
 * inclus si présents) ; le fiscaliste saisit les réintégrations et
 * déductions (libellé, montant, référence CGI facultative) et le
 * report déficitaire antérieur. Le module déroule le passage
 * déterministe (report imputé dans la limite du bénéfice), l'IS
 * théorique au taux normal 25 % et signale — sans le calculer — si
 * l'impôt minimum forfaitaire pourrait s'appliquer. Le bouton
 * « Reprendre comme IS dû estimé » écrit l'IS théorique dans le suivi
 * des acomptes, uniquement sur clic humain — l'humain liquide et
 * décide.
 */
type RetraitementLigne = {
  id: number | null;
  sens: string;
  libelle_sens: string;
  libelle: string;
  montant: string;
  reference_cgi: string | null;
};

type ResultatFiscalOut = {
  mission_id: number;
  exercice: number;
  disponible: boolean;
  comptable: {
    produits_classe7: string;
    charges_classe6: string;
    solde_hao_classe8: string;
    resultat_comptable: string;
    nb_comptes_resultat: number;
  };
  retraitements: RetraitementLigne[];
  totaux_retraitements: {
    reintegrations: string;
    deductions: string;
  };
  report_deficitaire: {
    saisi: boolean;
    anterieur: string;
    impute: string;
    restant: string;
  };
  resultat_fiscal_avant_report: string;
  resultat_fiscal: string;
  taux_is_normal: string;
  is_theorique: string;
  imf: {
    possible: boolean;
    motif: string | null;
    libelle: string | null;
    minimum_perception_indicatif: string;
  };
  synthese: {
    statut: string;
    libelle_statut: string;
    nb_retraitements: number;
    imf_possible: boolean;
  };
  note: string;
};

const SENS_RETRAITEMENT = [
  { valeur: "reintegration", libelle: "Réintégration" },
  { valeur: "deduction", libelle: "Déduction" },
] as const;

type Props = {
  missionId: number;
  jeton?: string | null;
  estLecteur?: boolean;
};

export function ResultatFiscalVue({ missionId, jeton, estLecteur }: Props) {
  const [etat, setEtat] = useState<ResultatFiscalOut | null>(null);
  const [sens, setSens] = useState<string>("reintegration");
  const [libelle, setLibelle] = useState("");
  const [montant, setMontant] = useState("");
  const [referenceCgi, setReferenceCgi] = useState("");
  const [report, setReport] = useState("");
  const [msg, setMsg] = useState<{ texte: string; err: boolean } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<ResultatFiscalOut>(
        `/api/v1/missions/${missionId}/resultat-fiscal`,
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

  const poster = useCallback(
    async (corps: Record<string, unknown>, ok: string) => {
      if (!jeton || !missionId) return;
      setBusy(true);
      setMsg(null);
      try {
        await api(`/api/v1/missions/${missionId}/retraitements`, {
          method: "POST",
          jeton,
          json: corps,
        });
        setMsg({ texte: ok, err: false });
        await charger();
      } catch (e) {
        setMsg({
          texte: e instanceof Error ? e.message : "Saisie impossible.",
          err: true,
        });
      } finally {
        setBusy(false);
      }
    },
    [jeton, missionId, charger],
  );

  const ajouterLigne = useCallback(async () => {
    if (!libelle.trim()) return;
    await poster(
      {
        sens,
        libelle,
        montant: montant || "0",
        reference_cgi: referenceCgi || null,
      },
      "Retraitement enregistré.",
    );
    setLibelle("");
    setMontant("");
    setReferenceCgi("");
  }, [poster, sens, libelle, montant, referenceCgi]);

  const saisirReport = useCallback(async () => {
    if (report === "") return;
    await poster(
      { sens: "report_deficitaire", montant: report },
      "Report déficitaire enregistré.",
    );
    setReport("");
  }, [poster, report]);

  const supprimerLigne = useCallback(
    async (id: number | null) => {
      if (id === null) return;
      await poster({ supprimer_id: id }, "Retraitement supprimé.");
    },
    [poster],
  );

  const reprendreIsDu = useCallback(async () => {
    if (!jeton || !missionId) return;
    setBusy(true);
    setMsg(null);
    try {
      const out = await api<{ is_du_estime: string }>(
        `/api/v1/missions/${missionId}/resultat-fiscal/reprendre-is-du`,
        { method: "POST", jeton },
      );
      setMsg({
        texte: `IS dû estimé repris : ${fmtMontant(
          out?.is_du_estime ?? "0",
        )} FCFA (visible dans le suivi des acomptes).`,
        err: false,
      });
    } catch (e) {
      setMsg({
        texte: e instanceof Error ? e.message : "Reprise impossible.",
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }, [jeton, missionId]);

  if (!etat) return null;
  const s = etat.synthese;
  return (
    <section
      className="rtva panel dense"
      aria-label="Résultat fiscal"
    >
      <div className="rtva-head">
        <h4 className="rtva-titre label-with-tip">
          Passage au résultat fiscal et IS théorique
          <InfoTip
            label="Déroule le tableau de passage : résultat comptable de la balance (classes 6/7, HAO 8x inclus), réintégrations et déductions saisies par le fiscaliste (référence CGI facultative), report déficitaire imputé dans la limite du bénéfice, IS théorique au taux normal 25 % et signal indicatif d'impôt minimum forfaitaire — vue consultative, l'humain liquide et décide."
            ariaLabel="Aide : résultat fiscal"
          />
        </h4>
        <span className="rtva-synthese muted">
          {s.libelle_statut} · {s.nb_retraitements} retraitement
          {s.nb_retraitements > 1 ? "s" : ""}
          {s.imf_possible && (
            <>
              {" "}
              ·{" "}
              <strong className="rtva-badge-ecart">IMF possible</strong>
            </>
          )}
        </span>
      </div>

      {!estLecteur && (
        <>
          <div className="rtva-saisie">
            <label className="rtva-champ">
              Sens
              <select
                value={sens}
                onChange={(e) => setSens(e.target.value)}
                aria-label="Sens du retraitement"
              >
                {SENS_RETRAITEMENT.map((n) => (
                  <option key={n.valeur} value={n.valeur}>
                    {n.libelle}
                  </option>
                ))}
              </select>
            </label>
            <label className="rtva-champ">
              Libellé
              <input
                type="text"
                value={libelle}
                onChange={(e) => setLibelle(e.target.value)}
                placeholder="Amendes et pénalités…"
                aria-label="Libellé du retraitement"
              />
            </label>
            <label className="rtva-champ">
              Montant
              <input
                type="number"
                min="0"
                step="1"
                value={montant}
                onChange={(e) => setMontant(e.target.value)}
                placeholder="0"
                aria-label="Montant du retraitement (FCFA)"
              />
            </label>
            <label className="rtva-champ">
              Réf. CGI (facultative)
              <input
                type="text"
                value={referenceCgi}
                onChange={(e) => setReferenceCgi(e.target.value)}
                placeholder="art. 18…"
                aria-label="Référence CGI (facultative)"
              />
            </label>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy || !libelle.trim()}
              onClick={() => void ajouterLigne()}
            >
              Ajouter le retraitement
            </button>
          </div>
          <div className="rtva-saisie">
            <label className="rtva-champ">
              Report déficitaire antérieur (facultatif)
              <input
                type="number"
                min="0"
                step="1"
                value={report}
                onChange={(e) => setReport(e.target.value)}
                placeholder={etat.report_deficitaire.anterieur}
                aria-label="Report déficitaire antérieur (FCFA)"
              />
            </label>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy || report === ""}
              onClick={() => void saisirReport()}
            >
              Enregistrer le report
            </button>
          </div>
        </>
      )}
      {msg && (
        <p className={`status${msg.err ? " err" : ""}`} role="status">
          {msg.texte}
        </p>
      )}

      {etat.disponible ? (
        <table className="rtva-table">
          <tbody>
            <tr>
              <td className="rtva-nature">
                Résultat comptable (classe 7 − classe 6, HAO 8x inclus)
              </td>
              <td className="rtva-montant">
                {fmtMontant(etat.comptable.resultat_comptable)}
              </td>
            </tr>
            <tr>
              <td className="rtva-nature">+ Réintégrations</td>
              <td className="rtva-montant">
                {fmtMontant(etat.totaux_retraitements.reintegrations)}
              </td>
            </tr>
            <tr>
              <td className="rtva-nature">− Déductions</td>
              <td className="rtva-montant">
                {fmtMontant(etat.totaux_retraitements.deductions)}
              </td>
            </tr>
            <tr>
              <td className="rtva-nature">
                − Report déficitaire imputé (plafonné au bénéfice
                {etat.report_deficitaire.saisi &&
                etat.report_deficitaire.restant !== "0.00" &&
                etat.report_deficitaire.restant !== "0"
                  ? ` — restant ${fmtMontant(
                      etat.report_deficitaire.restant,
                    )}`
                  : ""}
                )
              </td>
              <td className="rtva-montant">
                {fmtMontant(etat.report_deficitaire.impute)}
              </td>
            </tr>
            <tr>
              <td className="rtva-nature">
                <strong>Résultat fiscal</strong>
              </td>
              <td className="rtva-montant">
                <strong>{fmtMontant(etat.resultat_fiscal)}</strong>
              </td>
            </tr>
            <tr>
              <td className="rtva-nature">
                IS théorique (taux normal 25 %, arrondi au franc)
              </td>
              <td className="rtva-montant">
                <strong>{fmtMontant(etat.is_theorique)}</strong>
              </td>
            </tr>
          </tbody>
        </table>
      ) : (
        <p className="empty-state">
          Passage indisponible : importez la balance (comptes de
          résultat, classes 6 et 7) — les retraitements saisis restent
          listés ci-dessous.
        </p>
      )}

      {etat.imf.possible && etat.imf.libelle && (
        <p className="rtva-note">
          <strong className="rtva-badge-ecart">IMF</strong>{" "}
          {etat.imf.libelle} (minimum de perception indicatif :{" "}
          {fmtMontant(etat.imf.minimum_perception_indicatif)} FCFA).
        </p>
      )}

      {!estLecteur && etat.disponible && (
        <p className="rtva-note">
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy}
            onClick={() => void reprendreIsDu()}
          >
            Reprendre comme IS dû estimé
          </button>{" "}
          <span className="muted">
            Écrit l'IS théorique dans le suivi des acomptes IS —
            uniquement sur ce clic.
          </span>
        </p>
      )}

      {etat.retraitements.length > 0 && (
        <details className="rtva-detail" open>
          <summary>
            Retraitements saisis ({etat.retraitements.length})
          </summary>
          <table className="rtva-table">
            <thead>
              <tr>
                <th scope="col">Sens</th>
                <th scope="col">Libellé</th>
                <th scope="col">Montant</th>
                <th scope="col">Réf. CGI</th>
                {!estLecteur && <th scope="col" />}
              </tr>
            </thead>
            <tbody>
              {etat.retraitements.map((r) => (
                <tr key={r.id ?? `${r.sens}-${r.libelle}`}>
                  <td className="rtva-nature">{r.libelle_sens}</td>
                  <td>{r.libelle}</td>
                  <td className="rtva-montant">{fmtMontant(r.montant)}</td>
                  <td>{r.reference_cgi ?? "—"}</td>
                  {!estLecteur && (
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        disabled={busy}
                        onClick={() => void supprimerLigne(r.id)}
                        aria-label={`Supprimer « ${r.libelle} »`}
                      >
                        Supprimer
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {etat.disponible && (
        <details className="rtva-detail">
          <summary>
            Détail du résultat comptable (
            {etat.comptable.nb_comptes_resultat} comptes 6x/7x/8x)
          </summary>
          <p className="muted">
            Produits (classe 7) :{" "}
            {fmtMontant(etat.comptable.produits_classe7)} FCFA · Charges
            (classe 6) : {fmtMontant(etat.comptable.charges_classe6)}{" "}
            FCFA · Solde HAO net (classe 8, 87x/89x inclus) :{" "}
            {fmtMontant(etat.comptable.solde_hao_classe8)} FCFA. Si l'IS
            comptabilisé (89x) figure en balance, il est à réintégrer
            par une ligne humaine.
          </p>
        </details>
      )}

    </section>
  );
}
