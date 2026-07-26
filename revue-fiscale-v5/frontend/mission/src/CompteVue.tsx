import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api, fmtMontant } from "./api";
import { FORMES_JURIDIQUES_PM } from "./legalite";
import { PhoneField } from "./PhoneField";

type TenantCompte = {
  id: number;
  denomination: string;
  type: string;
  palier: string;
  statut: string;
  ncc?: string | null;
  rccm?: string | null;
  dfe?: string | null;
  forme_juridique?: string | null;
  siege_social?: string | null;
  commune?: string | null;
  centre_impots?: string | null;
  capital_social?: number | string | null;
};

type CompteData = {
  tenant: TenantCompte;
  utilisateur: {
    id: number;
    email: string;
    role: string;
    telephone: string | null;
  };
};

type IdentiteForm = {
  denomination: string;
  ncc: string;
  rccm: string;
  dfe: string;
  forme_juridique: string;
  siege_social: string;
  commune: string;
  centre_impots: string;
  capital_social: string;
};

type PalierRow = {
  code: string;
  missions_incluses?: number;
  prix_mensuel_xof?: string;
  courant?: boolean;
};

type DemandePalierOuverte = {
  id: number;
  palier_cible: string;
  statut: string;
  palier_actuel?: string;
  motif?: string | null;
  cree_le?: string;
};

type AbonnementData = {
  palier: string;
  tarifs_a_confirmer: boolean;
  avertissement: string;
  paliers: PalierRow[];
  quota?: {
    missions_incluses: number;
    missions_utilisees: number;
    bloque: boolean;
  } | null;
  demandes_palier_ouvertes: DemandePalierOuverte[];
};

type Props = {
  jeton: string;
  estAdmin: boolean;
  onDenominationChange?: (denom: string) => void;
  onProfilSaved?: () => void;
  onOuvrirFacturation?: () => void;
};

const LIBELLES_PALIER: Record<string, string> = {
  essentiel: "Essentiel",
  standard: "Standard",
  premium: "Premium",
  souverain: "Souverain",
};

function libellePalier(code: string | undefined | null): string {
  if (!code) return "—";
  return LIBELLES_PALIER[code] || code;
}

function capitalVersSaisie(v: number | string | null | undefined): string {
  if (v == null || v === "") return "";
  const n = typeof v === "number" ? v : Number(String(v).replace(/\s/g, ""));
  if (!Number.isFinite(n)) return "";
  return String(Math.round(n));
}

function identiteDepuisTenant(t: TenantCompte): IdentiteForm {
  return {
    denomination: t.denomination ?? "",
    ncc: t.ncc ?? "",
    rccm: t.rccm ?? "",
    dfe: t.dfe ?? "",
    forme_juridique: t.forme_juridique ?? "",
    siege_social: t.siege_social ?? "",
    commune: t.commune ?? "",
    centre_impots: t.centre_impots ?? "",
    capital_social: capitalVersSaisie(t.capital_social),
  };
}

function payloadIdentite(edit: IdentiteForm): Record<string, unknown> {
  const capitalRaw = edit.capital_social.trim().replace(/\s/g, "").replace(",", ".");
  let capital_social: number | null = null;
  if (capitalRaw) {
    const n = Number(capitalRaw);
    capital_social = Number.isFinite(n) ? n : null;
  }
  return {
    denomination: edit.denomination.trim(),
    ncc: edit.ncc.trim() || null,
    rccm: edit.rccm.trim() || null,
    dfe: edit.dfe.trim() || null,
    forme_juridique: edit.forme_juridique.trim() || null,
    siege_social: edit.siege_social.trim() || null,
    commune: edit.commune.trim() || null,
    centre_impots: edit.centre_impots.trim() || null,
    capital_social,
  };
}

export function CompteVue({
  jeton,
  estAdmin,
  onDenominationChange,
  onProfilSaved,
  onOuvrirFacturation,
}: Props) {
  const [compte, setCompte] = useState<CompteData | null>(null);
  const [abo, setAbo] = useState<AbonnementData | null>(null);
  const [identite, setIdentite] = useState<IdentiteForm>({
    denomination: "",
    ncc: "",
    rccm: "",
    dfe: "",
    forme_juridique: "",
    siege_social: "",
    commune: "",
    centre_impots: "",
    capital_social: "",
  });
  const [tel, setTel] = useState("");
  const [palierCible, setPalierCible] = useState("standard");
  const [motif, setMotif] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; err: boolean } | null>(null);
  const [dirtyIdentite, setDirtyIdentite] = useState(false);
  const [dirtyContact, setDirtyContact] = useState(false);
  const [detailsOuverts, setDetailsOuverts] = useState(false);
  const [changerOuvert, setChangerOuvert] = useState(false);
  const [comparerOuvert, setComparerOuvert] = useState(false);

  const charger = useCallback(async () => {
    setBusy(true);
    setMsg(null);
    try {
      const [c, a] = await Promise.all([
        api<CompteData>("/api/v1/compte", { jeton }),
        api<AbonnementData>("/api/v1/abonnement", { jeton }),
      ]);
      setCompte(c);
      setAbo(a);
      setIdentite(identiteDepuisTenant(c.tenant));
      setTel(c.utilisateur.telephone || "");
      setDirtyIdentite(false);
      setDirtyContact(false);
      const autre = (a.paliers || []).find((p) => !p.courant);
      if (autre) setPalierCible(autre.code);
      if ((a.demandes_palier_ouvertes || []).length > 0) {
        setChangerOuvert(true);
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

  const quotaPct = useMemo(() => {
    const q = abo?.quota;
    if (!q || q.missions_incluses <= 0) return 0;
    return Math.min(
      100,
      Math.round((q.missions_utilisees / q.missions_incluses) * 100),
    );
  }, [abo?.quota]);

  const demandeEnCours = abo?.demandes_palier_ouvertes?.[0] ?? null;
  const demandeOuverte = !!demandeEnCours;
  const palierCourant = abo?.palier || compte?.tenant.palier;
  const palierCourantRow = (abo?.paliers || []).find((p) => p.courant);
  const missionsRestantes =
    abo?.quota != null
      ? Math.max(0, abo.quota.missions_incluses - abo.quota.missions_utilisees)
      : null;

  function majIdentite<K extends keyof IdentiteForm>(cle: K, val: IdentiteForm[K]) {
    setIdentite((s) => ({ ...s, [cle]: val }));
    setDirtyIdentite(true);
  }

  async function sauverIdentite(e?: FormEvent) {
    e?.preventDefault();
    if (!estAdmin) return;
    setBusy(true);
    setMsg(null);
    try {
      const body: Record<string, unknown> = payloadIdentite(identite);
      if (dirtyContact) body.telephone = tel;
      const r = await api<CompteData>("/api/v1/compte", {
        method: "PATCH",
        jeton,
        json: body,
      });
      setCompte(r);
      setIdentite(identiteDepuisTenant(r.tenant));
      setTel(r.utilisateur.telephone || "");
      setDirtyIdentite(false);
      setDirtyContact(false);
      onDenominationChange?.(r.tenant.denomination);
      onProfilSaved?.();
      setMsg({ text: "Enregistré.", err: false });
    } catch (err) {
      setMsg({
        text: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function demanderPalier(e?: FormEvent) {
    e?.preventDefault();
    if (!estAdmin) return;
    setBusy(true);
    setMsg(null);
    try {
      await api<{ message?: string; id?: number }>(
        "/api/v1/abonnement/demande-palier",
        {
          method: "POST",
          jeton,
          json: { palier_cible: palierCible, motif: motif || null },
        },
      );
      setMsg({
        text: "Demande envoyée. Après validation, réglez dans Facturation.",
        err: false,
      });
      setMotif("");
      await charger();
    } catch (err) {
      setMsg({
        text: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  const lectureSeule = !estAdmin || busy;
  const dirty = dirtyIdentite || dirtyContact;

  return (
    <div className="page compte-page">
      <header className="page-head">
        <div>
          <h2 className="section-title">Compte</h2>
        </div>
        <div className="page-head-actions">
          {onOuvrirFacturation && (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={onOuvrirFacturation}
            >
              Facturation
            </button>
          )}
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy}
            onClick={() => void charger()}
          >
            Actualiser
          </button>
        </div>
      </header>

      {msg && (
        <div className={`status${msg.err ? " err" : ""}`} role="status">
          {msg.text}
        </div>
      )}

      <section className="panel dense compte-section" aria-labelledby="compte-identite">
        <h3 id="compte-identite" className="compte-section-title">
          Identité
        </h3>
        <form className="form-stack" onSubmit={(e) => void sauverIdentite(e)}>
          <div className="field-grid field-grid-2 compte-identite-grid">
            <label>
              Dénomination
              <input
                value={identite.denomination}
                onChange={(e) => majIdentite("denomination", e.target.value)}
                disabled={lectureSeule}
                required
                maxLength={200}
                autoComplete="organization"
              />
            </label>
            <label>
              NCC
              <input
                value={identite.ncc}
                onChange={(e) => majIdentite("ncc", e.target.value)}
                disabled={lectureSeule}
                maxLength={64}
                spellCheck={false}
                autoComplete="off"
              />
            </label>
            <label>
              Email
              <input
                value={compte?.utilisateur.email || ""}
                disabled
                readOnly
                autoComplete="email"
              />
            </label>
            <div>
              <span className="compte-field-label">Téléphone</span>
              <PhoneField
                id="compte-telephone"
                valueE164={tel}
                onChangeE164={(v) => {
                  setTel(v);
                  setDirtyContact(true);
                }}
                disabled={lectureSeule}
              />
            </div>
          </div>

          <details
            className="compte-details"
            open={detailsOuverts}
            onToggle={(e) => setDetailsOuverts((e.target as HTMLDetailsElement).open)}
          >
            <summary>Compléter</summary>
            <div className="field-grid field-grid-2 compte-identite-grid">
              <label>
                RCCM
                <input
                  value={identite.rccm}
                  onChange={(e) => majIdentite("rccm", e.target.value)}
                  disabled={lectureSeule}
                  maxLength={80}
                  spellCheck={false}
                  autoComplete="off"
                />
              </label>
              <label>
                Forme juridique
                <select
                  value={identite.forme_juridique}
                  onChange={(e) => majIdentite("forme_juridique", e.target.value)}
                  disabled={lectureSeule}
                >
                  <option value="">—</option>
                  {identite.forme_juridique &&
                    !FORMES_JURIDIQUES_PM.some(
                      (f) => f.value === identite.forme_juridique,
                    ) && (
                      <option value={identite.forme_juridique}>
                        {identite.forme_juridique}
                      </option>
                    )}
                  {FORMES_JURIDIQUES_PM.map((f) => (
                    <option key={f.value} value={f.value}>
                      {f.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Capital social (XOF)
                <input
                  type="number"
                  inputMode="decimal"
                  min={0}
                  step={1}
                  value={identite.capital_social}
                  onChange={(e) => majIdentite("capital_social", e.target.value)}
                  disabled={lectureSeule}
                />
              </label>
              <label>
                Siège social
                <input
                  value={identite.siege_social}
                  onChange={(e) => majIdentite("siege_social", e.target.value)}
                  disabled={lectureSeule}
                  maxLength={500}
                  autoComplete="street-address"
                />
              </label>
              <label>
                Commune
                <input
                  value={identite.commune}
                  onChange={(e) => majIdentite("commune", e.target.value)}
                  disabled={lectureSeule}
                  maxLength={120}
                  autoComplete="address-level2"
                />
              </label>
              <label>
                Centre des impôts
                <input
                  value={identite.centre_impots}
                  onChange={(e) => majIdentite("centre_impots", e.target.value)}
                  disabled={lectureSeule}
                  maxLength={200}
                  autoComplete="off"
                />
              </label>
              <label>
                Réf. DFE
                <input
                  value={identite.dfe}
                  onChange={(e) => majIdentite("dfe", e.target.value)}
                  disabled={lectureSeule}
                  maxLength={80}
                  spellCheck={false}
                  autoComplete="off"
                />
              </label>
            </div>
          </details>

          {estAdmin && (
            <div className="actions">
              <button
                type="submit"
                className="btn btn-primary"
                disabled={busy || !dirty}
              >
                Enregistrer
              </button>
            </div>
          )}
        </form>
      </section>

      <section className="panel dense compte-section" aria-labelledby="compte-abo">
        <h3 id="compte-abo" className="compte-section-title">
          Formule
        </h3>

        <div className="compte-formule">
          <div className="compte-formule-main">
            <p className="compte-abo-nom">
              {libellePalier(palierCourant)}
              {abo?.quota?.bloque && (
                <span className="surface-pill compte-pill-bloque">Épuisé</span>
              )}
            </p>
            {abo?.quota ? (
              <p className="compte-abo-detail">
                {missionsRestantes} mission
                {missionsRestantes !== 1 ? "s" : ""} restante
                {missionsRestantes !== 1 ? "s" : ""}
                {" · "}
                {abo.quota.missions_utilisees}/{abo.quota.missions_incluses}
              </p>
            ) : palierCourantRow?.missions_incluses != null ? (
              <p className="compte-abo-detail">
                {palierCourantRow.missions_incluses} missions / mois
              </p>
            ) : null}
            {abo?.quota && (
              <div
                className="compte-quota-bar"
                role="progressbar"
                aria-valuenow={quotaPct}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <div
                  className={`compte-quota-fill${abo.quota.bloque ? " is-bloque" : quotaPct >= 80 ? " is-alerte" : ""}`}
                  style={{ width: `${quotaPct}%` }}
                />
              </div>
            )}
          </div>
          {estAdmin && !demandeOuverte && (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setChangerOuvert((v) => !v)}
            >
              {changerOuvert ? "Fermer" : "Changer"}
            </button>
          )}
        </div>

        {demandeEnCours && (
          <div className="compte-demande-statut" role="status">
            <p className="compte-demande-statut-body">
              Demande en cours vers{" "}
              <strong>{libellePalier(demandeEnCours.palier_cible)}</strong>
              {onOuvrirFacturation && (
                <>
                  {" — "}
                  <button
                    type="button"
                    className="linkish"
                    onClick={onOuvrirFacturation}
                  >
                    Facturation
                  </button>
                </>
              )}
            </p>
          </div>
        )}

        {estAdmin && changerOuvert && !demandeOuverte && (
          <form
            className="form-stack compte-demande-form"
            onSubmit={(e) => void demanderPalier(e)}
          >
            <label>
              Formule souhaitée
              <select
                value={palierCible}
                onChange={(e) => setPalierCible(e.target.value)}
                disabled={busy}
              >
                {(abo?.paliers || [])
                  .filter((p) => !p.courant)
                  .map((p) => (
                    <option key={p.code} value={p.code}>
                      {libellePalier(p.code)}
                      {p.missions_incluses != null
                        ? ` — ${p.missions_incluses} missions`
                        : ""}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Motif (optionnel)
              <textarea
                value={motif}
                onChange={(e) => setMotif(e.target.value)}
                rows={2}
                maxLength={2000}
                disabled={busy}
              />
            </label>
            <div className="actions">
              <button
                type="submit"
                className="btn btn-primary"
                disabled={busy || !palierCible}
              >
                Envoyer la demande
              </button>
            </div>
          </form>
        )}

        <details
          className="compte-details"
          open={comparerOuvert}
          onToggle={(e) => setComparerOuvert((e.target as HTMLDetailsElement).open)}
        >
          <summary>Comparer les formules</summary>
          <div className="table-wrap compte-paliers">
            <table>
              <thead>
                <tr>
                  <th>Formule</th>
                  <th className="num">Missions</th>
                  <th className="num">Prix / mois</th>
                </tr>
              </thead>
              <tbody>
                {(abo?.paliers || []).map((p) => (
                  <tr
                    key={p.code}
                    className={p.courant ? "row-active" : undefined}
                  >
                    <td>
                      {libellePalier(p.code)}
                      {p.courant ? " · actuel" : ""}
                    </td>
                    <td className="num">{p.missions_incluses ?? "—"}</td>
                    <td className="num">
                      {p.prix_mensuel_xof
                        ? `${fmtMontant(p.prix_mensuel_xof)} XOF`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {abo?.tarifs_a_confirmer && (
            <p className="compte-note-discrete">Tarifs indicatifs.</p>
          )}
        </details>
      </section>
    </div>
  );
}
