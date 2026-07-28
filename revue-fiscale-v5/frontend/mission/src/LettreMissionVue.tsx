import { useState } from "react";
import { api } from "./api";

/** Lettre de mission imprimable (GET /missions/{id}/lettre).
 *
 * Au CADRAGE, le fiscaliste génère la lettre de mission — document
 * contractuel remis au client avant de démarrer : en-tête cabinet /
 * client, objet, périmètre (principales obligations du régime, sans
 * dates), limites (revue consultative — ni audit ni certification),
 * obligations réciproques, confidentialité, honoraires et signatures.
 * Impression navigateur → PDF : la classe « impression-lettre » posée
 * sur <body> autour de window.print() masque le reste de l'app
 * (@media print dans styles.css), seule la section .lettre-print sort.
 */

type IdentiteLettre = {
  mission_id: number;
  exercice: number;
  statut: string;
  cabinet: string;
  contribuable: string;
  ncc: string | null;
  regime: string | null;
  honoraires: string | null;
};

type ObligationLettre = {
  impot: string;
  obligation: string;
};

type SignatureLettre = {
  titre: string;
  denomination: string;
};

type LettreOut = {
  identite: IdentiteLettre;
  objet: string;
  perimetre: {
    texte: string;
    regime: string | null;
    obligations: ObligationLettre[];
  };
  limites: string;
  obligations_reciproques: string;
  confidentialite: string;
  honoraires: { montant: string | null; texte: string };
  signatures: {
    cabinet: SignatureLettre;
    client: SignatureLettre;
    mention: string;
  };
  genere_le: string;
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

const REGIMES_FR: Record<string, string> = {
  reel: "Réel normal d'imposition (RNI)",
  reel_simplifie: "Réel simplifié d'imposition (RSI)",
  tee: "Taxe de l'entreprenant (TEE)",
  ime: "Impôt des microentreprises (IME)",
};

/** ISO datetime → « JJ/MM/AAAA » (heure locale) — fallback brut. */
function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const jj = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  return `${jj}/${mm}/${d.getFullYear()}`;
}

/** Montant str Decimal → « 1 234 567 FCFA » — fallback brut. */
function formatMontant(brut: string | null): string {
  if (brut == null || brut === "") return "—";
  const n = Number(brut);
  if (Number.isNaN(n)) return `${brut} FCFA`;
  return `${n.toLocaleString("fr-FR")} FCFA`;
}

/** Impression : masque le reste de l'app via une classe sur <body>. */
function imprimerLettre(): void {
  const body = document.body;
  body.classList.add("impression-lettre");
  let fait = false;
  const fin = () => {
    if (fait) return;
    fait = true;
    body.classList.remove("impression-lettre");
    window.removeEventListener("afterprint", fin);
  };
  window.addEventListener("afterprint", fin);
  try {
    window.print();
  } finally {
    // Filet : certains navigateurs n'émettent pas afterprint.
    window.setTimeout(fin, 1500);
  }
}

export function LettreMissionVue({ missionId, jeton }: Props) {
  const [lettre, setLettre] = useState<LettreOut | null>(null);
  const [ouvert, setOuvert] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function ouvrir() {
    if (ouvert) {
      setOuvert(false);
      return;
    }
    if (!jeton || !missionId) return;
    setBusy(true);
    setErr(null);
    try {
      const out = await api<LettreOut>(
        `/api/v1/missions/${missionId}/lettre`,
        { jeton },
      );
      setLettre(out);
      setOuvert(true);
    } catch (e) {
      setLettre(null);
      setErr(e instanceof Error ? e.message : "lettre indisponible");
    } finally {
      setBusy(false);
    }
  }

  const ident = lettre?.identite ?? null;

  return (
    <div className="lettre-mission">
      <div className="lettre-actions">
        <button
          type="button"
          className={`btn btn-ghost btn-sm lettre-btn${ouvert ? " is-actif" : ""}`}
          onClick={() => void ouvrir()}
          disabled={busy || !jeton}
          aria-expanded={ouvert}
        >
          {busy ? "Lettre…" : "Lettre de mission"}
        </button>
        {ouvert && lettre && (
          <button
            type="button"
            className="btn btn-primary btn-sm lettre-imprimer-btn"
            onClick={imprimerLettre}
          >
            Imprimer
          </button>
        )}
        {err && (
          <span className="lettre-err" role="alert">
            Lettre indisponible : {err}
          </span>
        )}
      </div>

      {ouvert && lettre && ident && (
        <section className="lettre-print" aria-label="Lettre de mission">
          <header className="lettre-entete">
            <h2 className="lettre-titre">Lettre de mission</h2>
            <p className="lettre-sous-titre">
              Revue fiscale consultative — exercice {ident.exercice}
            </p>
            <table className="lettre-table lettre-table-identite">
              <tbody>
                <tr>
                  <th scope="row">Cabinet</th>
                  <td>{ident.cabinet || "—"}</td>
                </tr>
                <tr>
                  <th scope="row">Client</th>
                  <td>
                    {ident.contribuable || "—"}
                    {ident.ncc ? ` (NCC : ${ident.ncc})` : ""}
                  </td>
                </tr>
                <tr>
                  <th scope="row">Exercice revu</th>
                  <td>{ident.exercice}</td>
                </tr>
                <tr>
                  <th scope="row">Régime d'imposition</th>
                  <td>
                    {ident.regime
                      ? (REGIMES_FR[ident.regime] ?? ident.regime)
                      : "—"}
                  </td>
                </tr>
              </tbody>
            </table>
          </header>

          <section className="lettre-section">
            <h3 className="lettre-section-titre">1. Objet de la mission</h3>
            <p className="lettre-texte">{lettre.objet}</p>
          </section>

          <section className="lettre-section">
            <h3 className="lettre-section-titre">2. Périmètre de la revue</h3>
            <p className="lettre-texte">{lettre.perimetre.texte}</p>
            {lettre.perimetre.obligations.length > 0 && (
              <table className="lettre-table">
                <thead>
                  <tr>
                    <th>Impôt / taxe</th>
                    <th>Obligation</th>
                  </tr>
                </thead>
                <tbody>
                  {lettre.perimetre.obligations.map((o, i) => (
                    <tr key={`${o.impot}-${i}`}>
                      <td>{o.impot}</td>
                      <td>{o.obligation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="lettre-section">
            <h3 className="lettre-section-titre">3. Limites de la mission</h3>
            <p className="lettre-texte">{lettre.limites}</p>
          </section>

          <section className="lettre-section">
            <h3 className="lettre-section-titre">
              4. Obligations réciproques
            </h3>
            <p className="lettre-texte">{lettre.obligations_reciproques}</p>
          </section>

          <section className="lettre-section">
            <h3 className="lettre-section-titre">5. Confidentialité</h3>
            <p className="lettre-texte">{lettre.confidentialite}</p>
          </section>

          <section className="lettre-section">
            <h3 className="lettre-section-titre">6. Honoraires</h3>
            <p className="lettre-texte">{lettre.honoraires.texte}</p>
            {lettre.honoraires.montant != null && (
              <p className="lettre-honoraires-montant">
                Montant convenu : {formatMontant(lettre.honoraires.montant)}{" "}
                hors taxes.
              </p>
            )}
          </section>

          <section className="lettre-section">
            <h3 className="lettre-section-titre">7. Signatures</h3>
            <p className="lettre-texte">{lettre.signatures.mention}</p>
            <div className="lettre-signatures">
              <div className="lettre-signature-cadre">
                <p className="lettre-signature-titre">
                  {lettre.signatures.cabinet.titre}
                </p>
                <p className="lettre-signature-nom">
                  {lettre.signatures.cabinet.denomination || "—"}
                </p>
                <p className="lettre-signature-champ">
                  Nom et qualité : ______________________
                </p>
                <p className="lettre-signature-champ">
                  Date : ____ / ____ / ________
                </p>
                <div className="lettre-signature-zone" aria-hidden="true" />
              </div>
              <div className="lettre-signature-cadre">
                <p className="lettre-signature-titre">
                  {lettre.signatures.client.titre}
                </p>
                <p className="lettre-signature-nom">
                  {lettre.signatures.client.denomination || "—"}
                </p>
                <p className="lettre-signature-champ">
                  Nom et qualité : ______________________
                </p>
                <p className="lettre-signature-champ">
                  Date : ____ / ____ / ________
                </p>
                <div className="lettre-signature-zone" aria-hidden="true" />
              </div>
            </div>
          </section>

          <footer className="lettre-pied">
            <p className="lettre-note">{lettre.note}</p>
            <p className="lettre-genere">
              Lettre générée le {formatDate(lettre.genere_le)}.
            </p>
          </footer>
        </section>
      )}
    </div>
  );
}
