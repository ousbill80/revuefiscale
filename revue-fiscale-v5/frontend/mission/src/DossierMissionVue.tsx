import { useState } from "react";
import { api } from "./api";

/** Dossier de synthèse imprimable (GET /missions/{id}/dossier).
 *
 * En fin de mission, le fiscaliste remet au client (ou archive) un
 * document UNIQUE : identité du dossier, synthèse des risques, civisme
 * fiscal, complétude data room, points convenus, compte-rendu et
 * délais. Impression navigateur → PDF : la classe « impression-dossier »
 * posée sur <body> autour de window.print() masque le reste de l'app
 * (@media print dans styles.css), seule la section .dossier-print sort.
 */

type IdentiteDossier = {
  mission_id: number;
  exercice: number;
  statut: string;
  cabinet: string;
  contribuable: string;
  ncc: string | null;
  regime: string | null;
  honoraires: string | null;
};

type RisqueDossier = {
  risque_id: number | null;
  libelle: string;
  impot: string;
  exercice_origine: number | null;
  priorite: string;
  exposition: string | null;
};

type RisquesDossier = {
  risques: RisqueDossier[];
  exposition_totale: string | null;
  note: string | null;
};

type CivismeDossier = {
  taux_civisme: string | null;
  couvertes: number | null;
  en_attente: number | null;
  manquantes: number | null;
  note: string | null;
};

type CompletudeDossier = {
  regime: string | null;
  synthese: {
    attendues: number;
    presentes: number;
    essentielles_manquantes: number;
    taux_completude: string;
  } | null;
  manquantes: { code: string | null; libelle: string | null }[];
  note: string | null;
};

type PointConvenuDossier = {
  id: number;
  libelle: string;
  statut: string;
  date_cible: string | null;
  en_retard: boolean;
};

type PointsConvenusDossier = {
  points: PointConvenuDossier[];
  synthese: Record<string, number> | null;
  note: string | null;
};

type CompteRenduDossier = {
  date_reunion: string;
  participants: string;
  points_convenus: string;
};

type DelaisDossier = {
  jalons: { code: string; libelle: string; date: string | null }[];
  duree_totale_jours: string | null;
  note: string | null;
};

type DossierOut = {
  identite: IdentiteDossier | null;
  risques: RisquesDossier | null;
  civisme: CivismeDossier | null;
  completude: CompletudeDossier | null;
  points_convenus: PointsConvenusDossier | null;
  compte_rendu: CompteRenduDossier | null;
  delais: DelaisDossier | null;
  blocs_disponibles: number;
  genere_le: string;
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

const STATUTS_MISSION_FR: Record<string, string> = {
  cadrage: "Cadrage",
  en_cours: "En cours",
  cloturee: "Clôturée",
};

const STATUTS_POINT_FR: Record<string, string> = {
  a_faire: "À faire",
  fait: "Fait",
  abandonne: "Abandonné",
};

const PRIORITES_FR: Record<string, string> = {
  haute: "Haute",
  moyenne: "Moyenne",
  basse: "Basse",
};

/** ISO « AAAA-MM-JJ… » → « JJ/MM/AAAA » — fallback brut. */
function formatDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso;
}

/** ISO datetime → « JJ/MM/AAAA HH:MM » (heure locale) — fallback brut. */
function formatDateHeure(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const jj = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${jj}/${mm}/${d.getFullYear()} ${hh}:${mi}`;
}

/** Montant str Decimal → « 1 234 567 FCFA » — fallback brut. */
function formatMontant(brut: string | null): string {
  if (brut == null || brut === "") return "—";
  const n = Number(brut);
  if (Number.isNaN(n)) return `${brut} FCFA`;
  return `${n.toLocaleString("fr-FR")} FCFA`;
}

/** Impression : masque le reste de l'app via une classe sur <body>. */
function imprimerDossier(): void {
  const body = document.body;
  body.classList.add("impression-dossier");
  let fait = false;
  const fin = () => {
    if (fait) return;
    fait = true;
    body.classList.remove("impression-dossier");
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

export function DossierMissionVue({ missionId, jeton }: Props) {
  const [dossier, setDossier] = useState<DossierOut | null>(null);
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
      const out = await api<DossierOut>(
        `/api/v1/missions/${missionId}/dossier`,
        { jeton },
      );
      setDossier(out);
      setOuvert(true);
    } catch (e) {
      setDossier(null);
      setErr(e instanceof Error ? e.message : "dossier indisponible");
    } finally {
      setBusy(false);
    }
  }

  const ident = dossier?.identite ?? null;

  return (
    <div className="dossier-synthese">
      <div className="dossier-actions">
        <button
          type="button"
          className={`btn btn-ghost btn-sm dossier-btn${ouvert ? " is-actif" : ""}`}
          onClick={() => void ouvrir()}
          disabled={busy || !jeton}
          aria-expanded={ouvert}
        >
          {busy ? "Dossier…" : "Dossier de synthèse"}
        </button>
        {ouvert && dossier && (
          <button
            type="button"
            className="btn btn-primary btn-sm dossier-imprimer-btn"
            onClick={imprimerDossier}
          >
            Imprimer
          </button>
        )}
        {err && (
          <span className="dossier-err" role="alert">
            Dossier indisponible : {err}
          </span>
        )}
      </div>

      {ouvert && dossier && (
        <section
          className="dossier-print"
          aria-label="Dossier de synthèse de la mission"
        >
          <header className="dossier-entete">
            <h2 className="dossier-titre">
              Dossier de synthèse — mission de revue fiscale
            </h2>
            <table className="dossier-table dossier-table-identite">
              <tbody>
                <tr>
                  <th scope="row">Cabinet</th>
                  <td>{ident?.cabinet || "—"}</td>
                </tr>
                <tr>
                  <th scope="row">Client</th>
                  <td>
                    {ident?.contribuable || "—"}
                    {ident?.ncc ? ` (NCC : ${ident.ncc})` : ""}
                  </td>
                </tr>
                <tr>
                  <th scope="row">Exercice</th>
                  <td>{ident?.exercice ?? "—"}</td>
                </tr>
                <tr>
                  <th scope="row">Régime</th>
                  <td>{ident?.regime || "—"}</td>
                </tr>
                <tr>
                  <th scope="row">Statut de la mission</th>
                  <td>
                    {ident
                      ? (STATUTS_MISSION_FR[ident.statut] ?? ident.statut)
                      : "—"}
                  </td>
                </tr>
                {ident?.honoraires != null && (
                  <tr>
                    <th scope="row">Honoraires convenus</th>
                    <td>{formatMontant(ident.honoraires)}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </header>

          <section className="dossier-section">
            <h3 className="dossier-section-titre">Synthèse des risques</h3>
            {dossier.risques == null ? (
              <p className="dossier-vide">Bloc indisponible.</p>
            ) : dossier.risques.risques.length === 0 ? (
              <p className="dossier-vide">
                Aucun risque ouvert au jour de la génération.
              </p>
            ) : (
              <>
                <table className="dossier-table">
                  <thead>
                    <tr>
                      <th>Risque</th>
                      <th>Impôt</th>
                      <th>Exercice</th>
                      <th>Priorité</th>
                      <th>Exposition</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dossier.risques.risques.map((r, i) => (
                      <tr key={r.risque_id ?? i}>
                        <td>{r.libelle}</td>
                        <td>{r.impot}</td>
                        <td>{r.exercice_origine ?? "—"}</td>
                        <td>{PRIORITES_FR[r.priorite] ?? r.priorite}</td>
                        <td>{formatMontant(r.exposition)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="dossier-total">
                  Exposition totale estimée :{" "}
                  {formatMontant(dossier.risques.exposition_totale)}
                </p>
              </>
            )}
          </section>

          <section className="dossier-section">
            <h3 className="dossier-section-titre">Civisme déclaratif</h3>
            {dossier.civisme == null ? (
              <p className="dossier-vide">Bloc indisponible.</p>
            ) : (
              <p>
                Taux de civisme : {dossier.civisme.taux_civisme ?? "—"} % —{" "}
                {dossier.civisme.couvertes ?? 0} échéance(s) couverte(s),{" "}
                {dossier.civisme.en_attente ?? 0} en attente,{" "}
                {dossier.civisme.manquantes ?? 0} manquante(s).
              </p>
            )}
          </section>

          <section className="dossier-section">
            <h3 className="dossier-section-titre">
              Complétude de la data room
            </h3>
            {dossier.completude == null ? (
              <p className="dossier-vide">Bloc indisponible.</p>
            ) : (
              <>
                <p>
                  Taux de complétude :{" "}
                  {dossier.completude.synthese?.taux_completude ?? "—"} % (
                  {dossier.completude.synthese?.presentes ?? 0}/
                  {dossier.completude.synthese?.attendues ?? 0} pièce(s)
                  attendues présentes).
                </p>
                {dossier.completude.manquantes.length > 0 && (
                  <ul className="dossier-liste">
                    {dossier.completude.manquantes.map((m, i) => (
                      <li key={m.code ?? i}>
                        Pièce essentielle manquante : {m.libelle ?? m.code}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </section>

          <section className="dossier-section">
            <h3 className="dossier-section-titre">Points convenus</h3>
            {dossier.points_convenus == null ? (
              <p className="dossier-vide">Bloc indisponible.</p>
            ) : dossier.points_convenus.points.length === 0 ? (
              <p className="dossier-vide">Aucun point convenu consigné.</p>
            ) : (
              <table className="dossier-table">
                <thead>
                  <tr>
                    <th>Point convenu</th>
                    <th>Statut</th>
                    <th>Échéance</th>
                  </tr>
                </thead>
                <tbody>
                  {dossier.points_convenus.points.map((p) => (
                    <tr key={p.id}>
                      <td>{p.libelle}</td>
                      <td>
                        {STATUTS_POINT_FR[p.statut] ?? p.statut}
                        {p.en_retard ? " — en retard" : ""}
                      </td>
                      <td>{p.date_cible ? formatDate(p.date_cible) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="dossier-section">
            <h3 className="dossier-section-titre">
              Compte-rendu de restitution
            </h3>
            {dossier.compte_rendu == null ? (
              <p className="dossier-vide">
                Aucun compte-rendu de réunion consigné.
              </p>
            ) : (
              <>
                <p>
                  Réunion du {formatDate(dossier.compte_rendu.date_reunion)}
                </p>
                <p className="dossier-pre">
                  Participants : {dossier.compte_rendu.participants}
                </p>
                <p className="dossier-pre">
                  Points convenus : {dossier.compte_rendu.points_convenus}
                </p>
              </>
            )}
          </section>

          <section className="dossier-section">
            <h3 className="dossier-section-titre">Délais de la mission</h3>
            {dossier.delais == null ? (
              <p className="dossier-vide">Bloc indisponible.</p>
            ) : (
              <>
                <table className="dossier-table">
                  <thead>
                    <tr>
                      <th>Jalon</th>
                      <th>Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dossier.delais.jalons.map((j) => (
                      <tr key={j.code}>
                        <td>{j.libelle}</td>
                        <td>{j.date ? formatDateHeure(j.date) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {dossier.delais.duree_totale_jours != null && (
                  <p className="dossier-total">
                    Durée totale observée :{" "}
                    {dossier.delais.duree_totale_jours} jour(s)
                  </p>
                )}
              </>
            )}
          </section>

          <footer className="dossier-pied">
            <p className="dossier-note">{dossier.note}</p>
            <p className="dossier-genere">
              Dossier généré le {formatDateHeure(dossier.genere_le)}.
            </p>
          </footer>
        </section>
      )}
    </div>
  );
}
