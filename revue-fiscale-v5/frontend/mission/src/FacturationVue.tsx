import { useCallback, useEffect, useState } from "react";
import { api, telecharger, fmtMontant } from "./api";

type FactureRow = {
  id: number;
  numero: string;
  periode?: string;
  montant: string | number;
  devise?: string;
  statut: string;
  palier?: string | null;
  demande_paiement_ouverte?: string | null;
};

type Virement = {
  raison_sociale: string;
  compte_bancaire: string;
  siege: string;
  a_confirmer: boolean;
  note: string;
};

type PaystackConfig = {
  disponible: boolean;
  public_key?: string;
  channels?: string[];
  currency?: string;
  message?: string | null;
};

type Props = {
  jeton: string;
  estAdmin: boolean;
};

function facturePayable(f: FactureRow): boolean {
  return f.statut === "emise" || f.statut === "brouillon";
}

function libelleStatut(statut: string): string {
  switch (statut) {
    case "emise":
      return "À payer";
    case "payee":
      return "Payée";
    case "brouillon":
      return "Brouillon";
    case "annulee":
      return "Annulée";
    default:
      return statut;
  }
}

export function FacturationVue({ jeton, estAdmin }: Props) {
  const [factures, setFactures] = useState<FactureRow[]>([]);
  const [virement, setVirement] = useState<Virement | null>(null);
  const [paystack, setPaystack] = useState<PaystackConfig>({
    disponible: false,
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; err: boolean } | null>(null);

  const charger = useCallback(async () => {
    setBusy(true);
    try {
      const data = await api<{
        factures: FactureRow[];
        virement: Virement;
        paystack?: { disponible: boolean };
      }>("/api/v1/factures", { jeton });
      setFactures(data.factures || []);
      setVirement(data.virement);
      setPaystack((prev) => ({
        ...prev,
        disponible: Boolean(data.paystack?.disponible),
      }));
      try {
        const cfg = await api<PaystackConfig>(
          "/api/v1/factures/paystack-config",
          { jeton },
        );
        setPaystack(cfg);
      } catch {
        /* liste déjà a paystack.disponible */
      }
    } catch (e) {
      setMsg({
        text: e instanceof Error ? e.message : String(e),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }, [jeton]);

  useEffect(() => {
    void charger();
  }, [charger]);

  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.get("paystack") === "1") {
        setMsg({
          text: "Paiement en ligne reçu — actualisation en cours.",
          err: false,
        });
        void charger();
        params.delete("paystack");
        const qs = params.toString();
        const next = `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`;
        window.history.replaceState({}, "", next);
      }
    } catch {
      /* ignore */
    }
  }, [charger]);

  async function telechargerPdf(f: FactureRow) {
    try {
      await telecharger(
        `/api/v1/factures/${f.id}/pdf`,
        jeton,
        `facture-${f.numero.replace(/\//g, "-")}.pdf`,
      );
    } catch (e) {
      setMsg({
        text: e instanceof Error ? e.message : String(e),
        err: true,
      });
    }
  }

  async function payerEnLigne(f: FactureRow) {
    if (!estAdmin || !paystack.disponible) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<{
        authorization_url: string;
        reference: string;
      }>(`/api/v1/factures/${f.id}/payer-paystack`, {
        method: "POST",
        jeton,
        json: {},
      });
      if (!r.authorization_url) {
        throw new Error("URL de paiement indisponible");
      }
      window.location.assign(r.authorization_url);
    } catch (e) {
      setMsg({
        text: e instanceof Error ? e.message : String(e),
        err: true,
      });
      setBusy(false);
    }
  }

  async function signaler(f: FactureRow) {
    if (!estAdmin) return;
    const note = window.prompt("Réf. virement (optionnel) :", "");
    if (note === null) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<{ message?: string }>(
        `/api/v1/factures/${f.id}/signaler-paiement`,
        { method: "POST", jeton, json: { note: note || null } },
      );
      setMsg({
        text: r.message || "Signalement enregistré.",
        err: false,
      });
      await charger();
    } catch (e) {
      setMsg({
        text: e instanceof Error ? e.message : String(e),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page facturation-page">
      <header className="page-head">
        <div>
          <h2 className="section-title">Facturation</h2>
        </div>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={busy}
          onClick={() => void charger()}
        >
          Actualiser
        </button>
      </header>

      {msg && (
        <div className={`status${msg.err ? " err" : ""}`} role="status">
          {msg.text}
        </div>
      )}

      <section className="panel dense list-panel" aria-label="Factures">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>N°</th>
                <th>Période</th>
                <th className="num">Montant</th>
                <th>Statut</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {factures.length === 0 && (
                <tr>
                  <td colSpan={5} className="empty-cell">
                    <div className="equipe-empty">
                      <p className="equipe-empty-title">
                        Aucune facture pour le moment
                      </p>
                      <p className="equipe-empty-body">
                        Vos factures d&apos;abonnement apparaîtront ici dès
                        leur émission.
                      </p>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        disabled={busy}
                        onClick={() => void charger()}
                      >
                        Actualiser la liste
                      </button>
                    </div>
                  </td>
                </tr>
              )}
              {factures.map((f) => (
                <tr key={f.id}>
                  <td>{f.numero}</td>
                  <td>{f.periode ? String(f.periode).slice(0, 10) : "—"}</td>
                  <td className="num">
                    {fmtMontant(f.montant)} {f.devise || "XOF"}
                  </td>
                  <td>
                    {libelleStatut(f.statut)}
                    {f.demande_paiement_ouverte
                      ? " · demande de paiement ouverte"
                      : ""}
                  </td>
                  <td>
                    <div className="row-actions">
                      {estAdmin &&
                        facturePayable(f) &&
                        paystack.disponible && (
                          <button
                            type="button"
                            className="btn btn-primary btn-sm"
                            disabled={busy}
                            onClick={() => void payerEnLigne(f)}
                          >
                            Payer en ligne
                          </button>
                        )}
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => void telechargerPdf(f)}
                      >
                        PDF
                      </button>
                      {estAdmin &&
                        facturePayable(f) &&
                        !f.demande_paiement_ouverte && (
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            disabled={busy}
                            onClick={() => void signaler(f)}
                          >
                            Virement fait
                          </button>
                        )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {virement && (
        <section className="panel dense facturation-virement" aria-label="Virement">
          <h3 className="compte-section-title">Virement</h3>
          <p className="facturation-virement-line">
            {virement.raison_sociale}
            {" · "}
            {virement.compte_bancaire}
            {virement.siege ? ` · ${virement.siege}` : ""}
          </p>
          {virement.a_confirmer && (
            <p className="compte-note-discrete">Coordonnées à confirmer.</p>
          )}
        </section>
      )}
    </div>
  );
}
