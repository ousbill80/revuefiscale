import { useState } from "react";
import { api, fmtPct } from "./api";

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

type RapprochementTvaDossier = {
  synthese: {
    statut: string;
    nb_periodes_declarees: number;
    nb_comptes_tva_balance: number;
    nb_ecarts_significatifs: number;
  } | null;
  seuil_signification: string | null;
  ecarts_significatifs: {
    nature: string | null;
    libelle: string | null;
    declare: string | null;
    comptabilise: string | null;
    ecart: string | null;
  }[];
  note: string | null;
};

type ControlesFiscauxDossier = {
  synthese: {
    statut: string;
    nb_evenements: number;
    nb_echeances_proches: number;
    nb_echeances_depassees: number;
    montant_total_en_jeu: string;
    dernier_evenement: {
      type_evenement: string;
      libelle: string;
      date_evenement: string;
    } | null;
  } | null;
  echeances_a_surveiller: {
    libelle: string | null;
    date_evenement: string | null;
    echeance: string | null;
    statut: string | null;
    jours_restants: number | null;
  }[];
  note: string | null;
};

type MaterialiteDossier = {
  synthese: {
    statut: string;
    nb_comptes_balance: number;
    nb_comptes_cibles: number;
    taux_couverture_global: string;
  } | null;
  seuil_retenu: {
    seuil_retenu: string;
    source: string;
    referentiel: string;
    commentaire: string;
    decide_par: string;
  } | null;
  couverture: {
    masse_totale: string | null;
    masse_ciblee: string | null;
    taux_global: string | null;
  } | null;
  note: string | null;
};

type AcomptesDossier = {
  synthese: {
    statut: string;
    nb_versements: number;
    nb_comptes_impot_balance: number;
    solde_important: boolean;
  } | null;
  position: {
    statut: string;
    libelle: string;
    montant: string;
    solde_signe: string;
    solde_important: boolean;
  } | null;
  totaux_verses: Record<string, string> | null;
  is_du_estime: string | null;
  note: string | null;
};

type RapprochementSalairesDossier = {
  synthese: {
    statut: string;
    nb_periodes_declarees: number;
    nb_comptes_66_balance: number;
    nb_ecarts_significatifs: number;
  } | null;
  seuil_signification: string | null;
  ecarts_significatifs: {
    nature: string | null;
    libelle: string | null;
    declare: string | null;
    comptabilise: string | null;
    ecart: string | null;
    commentaire: string | null;
  }[];
  note: string | null;
};

type PatenteDossier = {
  synthese: {
    statut: string | null;
    libelle_statut: string | null;
    nb_comptes_ca: number | null;
  } | null;
  estimation_totale_partielle: string | null;
  plancher_applique: boolean | null;
  note: string | null;
};

type ChargeFiscaleDossier = {
  synthese: {
    statut: string | null;
    libelle_statut: string | null;
    nb_composantes_disponibles: number | null;
    nb_composantes_suivies: number | null;
    total_partiel: boolean | null;
    tva_nette_declaree: string | null;
  } | null;
  total_charge_propre_estimee: string | null;
  composantes_incluses_total: string[];
  composantes_indisponibles: string[];
  note: string | null;
};

type ImpotCompletudeDossier = {
  statut: string | null;
  nb_manquantes: number | null;
  taux_couverture: string | null;
};

type CompletudeDeclarativeDossier = {
  exercice: number | null;
  synthese: {
    statut_global: string | null;
    nb_manquantes_total: number | null;
  } | null;
  impots: Record<string, ImpotCompletudeDossier> | null;
  note: string | null;
};

type CoherenceCaDossier = {
  statut: string | null;
  ca_comptable: string | null;
  ca_reconstitue: string | null;
  ecart: string | null;
  ecart_relatif_pct: string | null;
  approximation: boolean | null;
  note: string | null;
};

type RetenueLoyersDossier = {
  statut: string | null;
  loyers_bruts: string | null;
  taux_indicatif: string | null;
  retenue_theorique_max: string | null;
  repartition_calculable: boolean | null;
  note: string | null;
};

type RetenueHonorairesDossier = {
  statut: string | null;
  honoraires_bruts: string | null;
  taux_indicatif: string | null;
  retenue_theorique_max: string | null;
  repartition_calculable: boolean | null;
  note: string | null;
};

type QualiteBalanceDossier = {
  statut: string | null;
  equilibree: boolean | null;
  ecart_equilibre: string | null;
  nb_sens_inhabituels: number | null;
  nb_comptes_hors_plan: number | null;
  nb_observations: number | null;
  note: string | null;
};

type DeficitsReportablesDossier = {
  statut: string | null;
  nb_exercices: number | null;
  nb_deficits_constates: number | null;
  cumul_indicatif_final: string | null;
  approximation: boolean | null;
  imputation_reelle_calculable: boolean | null;
  note: string | null;
};

type RapprochementAcomptesDossier = {
  statut: string | null;
  is_theorique: string | null;
  total_acomptes_saisis: string | null;
  nb_versements: number | null;
  solde_indicatif: string | null;
  solde_signe: string | null;
  approximation: boolean | null;
  minimum_perception_calculable: boolean | null;
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
  rapprochement_tva: RapprochementTvaDossier | null;
  controles_fiscaux: ControlesFiscauxDossier | null;
  materialite: MaterialiteDossier | null;
  acomptes: AcomptesDossier | null;
  rapprochement_salaires: RapprochementSalairesDossier | null;
  patente: PatenteDossier | null;
  charge_fiscale: ChargeFiscaleDossier | null;
  completude_declarative: CompletudeDeclarativeDossier | null;
  coherence_ca: CoherenceCaDossier | null;
  retenue_loyers: RetenueLoyersDossier | null;
  deficits_reportables: DeficitsReportablesDossier | null;
  rapprochement_acomptes: RapprochementAcomptesDossier | null;
  retenue_honoraires: RetenueHonorairesDossier | null;
  qualite_balance: QualiteBalanceDossier | null;
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

const STATUTS_TVA_FR: Record<string, string> = {
  indisponible: "Indisponible (déclarations ou balance manquantes)",
  coherent: "Cohérent au seuil de signification",
  ecarts_a_expliquer: "Écarts à expliquer",
};

const STATUTS_CONTROLES_FR: Record<string, string> = {
  aucun_evenement: "Aucun événement consigné",
  a_jour: "À jour",
  echeances_proches: "Échéances proches",
  echeances_depassees: "Échéances dépassées",
};

const STATUTS_ECHEANCE_FR: Record<string, string> = {
  proche: "Proche",
  depassee: "Dépassée",
};

const STATUTS_ACOMPTES_FR: Record<string, string> = {
  indisponible: "Indisponible (IS dû estimé non saisi)",
  solde_a_payer: "Solde d'IS à payer",
  credit_a_reporter: "Crédit d'impôt à reporter",
  equilibre: "Position équilibrée",
};

const STATUTS_SALAIRES_FR: Record<string, string> = {
  indisponible: "Indisponible (déclarations ou balance manquantes)",
  coherent: "Cohérent au seuil de signification",
  ecarts_a_expliquer: "Écarts à expliquer",
};

const STATUTS_PATENTE_FR: Record<string, string> = {
  indisponible:
    "Estimation indisponible — importez la balance (comptes 70x)",
  estimation_partielle:
    "Estimation partielle (droit sur le chiffre d'affaires seul)",
};

const STATUTS_CHARGE_FISCALE_FR: Record<string, string> = {
  indisponible:
    "Panorama indisponible — importez la balance et saisissez les déclarations",
  partiel: "Panorama partiel — certaines composantes sont indisponibles",
  complet: "Panorama complet — toutes les composantes suivies sont estimées",
};

const COMPOSANTES_CHARGE_FISCALE_FR: Record<string, string> = {
  is: "IS théorique",
  patente: "patente (partielle)",
  salaires: "impôts sur salaires déclarés",
  tva: "TVA nette déclarée",
  acomptes: "position d'acomptes",
};

const STATUTS_COMPLETUDE_DECLARATIVE_FR: Record<string, string> = {
  complet: "Complet — toutes les périodes échues sont couvertes",
  lacunaire: "Lacunaire — des périodes échues sont sans déclaration saisie",
  aucune_saisie: "Aucune saisie — aucune période échue n'est couverte",
  sans_periode_echue: "Sans période échue sur l'exercice",
};

const LIBELLES_IMPOT_COMPLETUDE_FR: Record<string, string> = {
  tva: "TVA (déclaration mensuelle)",
  salaires: "Impôts sur salaires (déclaration mensuelle)",
};

const STATUTS_COHERENCE_CA_FR: Record<string, string> = {
  indisponible:
    "Croisement indisponible — importez la balance (comptes 70x) et saisissez au moins une déclaration de TVA",
  coherent: "Cohérent — écart relatif dans le seuil indicatif",
  ecart_a_expliquer: "Écart à expliquer — l'humain apprécie",
};

const STATUTS_RETENUE_LOYERS_FR: Record<string, string> = {
  indisponible:
    "Vue indisponible — importez la balance (comptes 622x « locations et charges locatives »)",
  a_qualifier:
    "Retenue théorique maximale indicative — qualité des bailleurs à qualifier par l'humain",
};

const STATUTS_RETENUE_HONORAIRES_FR: Record<string, string> = {
  indisponible:
    "Vue indisponible — importez la balance (comptes 632x « rémunérations d'intermédiaires et de conseils »)",
  a_qualifier:
    "Retenue théorique maximale indicative — régime des prestataires à qualifier par l'humain",
};

const STATUTS_QUALITE_BALANCE_FR: Record<string, string> = {
  indisponible:
    "Vue indisponible — importez la balance pour contrôler sa qualité",
  equilibree_sans_observation:
    "Balance équilibrée, aucune observation — l'humain reste juge de la fiabilité",
  observations_a_examiner:
    "Observations à examiner — chacune peut être justifiée, l'humain conclut",
};

const STATUTS_DEFICITS_REPORTABLES_FR: Record<string, string> = {
  indisponible:
    "Suivi indisponible — aucun exercice du client ne porte de résultat fiscal théorique chiffrable",
  aucun_deficit:
    "Aucun déficit constaté sur les exercices suivis (résultats fiscaux théoriques)",
  deficits_a_suivre:
    "Déficits à suivre — l'humain rapproche les liasses déposées",
};

const STATUTS_RAPPROCHEMENT_ACOMPTES_FR: Record<string, string> = {
  indisponible:
    "Rapprochement indisponible — l'IS théorique du tableau de passage ne se chiffre pas",
  solde_a_payer_indicatif:
    "Reste à payer indicatif — à rapprocher des quittances",
  excedent_indicatif:
    "Crédit d'impôt indicatif / excédent à faire valoir — à rapprocher des quittances",
  equilibre_indicatif:
    "Position équilibrée indicative — acomptes saisis égaux à l'IS théorique",
};

const STATUTS_MATERIALITE_FR: Record<string, string> = {
  indisponible: "Indisponible (balance non importée)",
  seuil_a_retenir: "Seuil à retenir",
  travaux_cibles: "Travaux ciblés",
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
                  {fmtPct(dossier.completude.synthese?.taux_completude ?? "—")} % (
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

          {dossier.rapprochement_tva != null && (
            <section className="dossier-section">
              <h3 className="dossier-section-titre">Rapprochement TVA</h3>
              <p>
                Statut :{" "}
                {dossier.rapprochement_tva.synthese
                  ? (STATUTS_TVA_FR[
                      dossier.rapprochement_tva.synthese.statut
                    ] ?? dossier.rapprochement_tva.synthese.statut)
                  : "—"}{" "}
                — {dossier.rapprochement_tva.synthese
                  ?.nb_periodes_declarees ?? 0}{" "}
                période(s) déclarée(s),{" "}
                {dossier.rapprochement_tva.synthese
                  ?.nb_ecarts_significatifs ?? 0}{" "}
                écart(s) significatif(s) (seuil :{" "}
                {formatMontant(dossier.rapprochement_tva.seuil_signification)}
                ).
              </p>
              {dossier.rapprochement_tva.ecarts_significatifs.length > 0 && (
                <table className="dossier-table">
                  <thead>
                    <tr>
                      <th>Nature</th>
                      <th>Déclaré</th>
                      <th>Comptabilisé</th>
                      <th>Écart</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dossier.rapprochement_tva.ecarts_significatifs.map(
                      (e, i) => (
                        <tr key={e.nature ?? i}>
                          <td>{e.libelle ?? e.nature ?? "—"}</td>
                          <td>{formatMontant(e.declare)}</td>
                          <td>{formatMontant(e.comptabilise)}</td>
                          <td>{formatMontant(e.ecart)}</td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              )}
            </section>
          )}

          {dossier.controles_fiscaux != null && (
            <section className="dossier-section">
              <h3 className="dossier-section-titre">
                Contrôles fiscaux et contentieux
              </h3>
              <p>
                Statut :{" "}
                {dossier.controles_fiscaux.synthese
                  ? (STATUTS_CONTROLES_FR[
                      dossier.controles_fiscaux.synthese.statut
                    ] ?? dossier.controles_fiscaux.synthese.statut)
                  : "—"}{" "}
                — {dossier.controles_fiscaux.synthese?.nb_evenements ?? 0}{" "}
                événement(s) consigné(s), montant total en jeu :{" "}
                {formatMontant(
                  dossier.controles_fiscaux.synthese?.montant_total_en_jeu ??
                    null,
                )}
                .
              </p>
              {dossier.controles_fiscaux.synthese?.dernier_evenement && (
                <p>
                  Dernier acte :{" "}
                  {dossier.controles_fiscaux.synthese.dernier_evenement
                    .libelle}{" "}
                  du{" "}
                  {formatDate(
                    dossier.controles_fiscaux.synthese.dernier_evenement
                      .date_evenement,
                  )}
                  .
                </p>
              )}
              {dossier.controles_fiscaux.echeances_a_surveiller.length >
                0 && (
                <table className="dossier-table">
                  <thead>
                    <tr>
                      <th>Acte</th>
                      <th>Date de l'acte</th>
                      <th>Échéance de riposte</th>
                      <th>Statut</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dossier.controles_fiscaux.echeances_a_surveiller.map(
                      (e, i) => (
                        <tr key={i}>
                          <td>{e.libelle ?? "—"}</td>
                          <td>
                            {e.date_evenement
                              ? formatDate(e.date_evenement)
                              : "—"}
                          </td>
                          <td>{e.echeance ? formatDate(e.echeance) : "—"}</td>
                          <td>
                            {e.statut
                              ? (STATUTS_ECHEANCE_FR[e.statut] ?? e.statut)
                              : "—"}
                            {e.jours_restants != null
                              ? ` (${e.jours_restants} jour(s))`
                              : ""}
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              )}
            </section>
          )}

          {dossier.materialite != null && (
            <section className="dossier-section">
              <h3 className="dossier-section-titre">
                Seuil de matérialité et ciblage des travaux
              </h3>
              <p>
                Statut :{" "}
                {dossier.materialite.synthese
                  ? (STATUTS_MATERIALITE_FR[
                      dossier.materialite.synthese.statut
                    ] ?? dossier.materialite.synthese.statut)
                  : "—"}{" "}
                — seuil retenu :{" "}
                {dossier.materialite.seuil_retenu
                  ? formatMontant(
                      dossier.materialite.seuil_retenu.seuil_retenu,
                    )
                  : "aucun"}
                .
              </p>
              {dossier.materialite.synthese && (
                <p>
                  {dossier.materialite.synthese.nb_comptes_cibles} compte(s)
                  ciblé(s) sur{" "}
                  {dossier.materialite.synthese.nb_comptes_balance} en balance
                  — couverture globale des masses :{" "}
                  {dossier.materialite.couverture?.taux_global ?? "—"} %.
                </p>
              )}
            </section>
          )}

          {dossier.acomptes != null && (
            <section className="dossier-section">
              <h3 className="dossier-section-titre">
                Acomptes IS et position de solde
              </h3>
              <p>
                Position :{" "}
                {dossier.acomptes.position
                  ? (STATUTS_ACOMPTES_FR[dossier.acomptes.position.statut] ??
                    dossier.acomptes.position.libelle)
                  : "—"}
                {dossier.acomptes.position &&
                dossier.acomptes.position.statut !== "indisponible"
                  ? ` : ${formatMontant(dossier.acomptes.position.montant)}`
                  : ""}
                {dossier.acomptes.position?.solde_important
                  ? " (solde important)"
                  : ""}
                {" — "}
                {dossier.acomptes.synthese?.nb_versements ?? 0} versement(s)
                saisi(s).
              </p>
              <p>
                Total versé :{" "}
                {formatMontant(dossier.acomptes.totaux_verses?.total ?? null)}{" "}
                — IS dû estimé :{" "}
                {dossier.acomptes.is_du_estime != null
                  ? formatMontant(dossier.acomptes.is_du_estime)
                  : "non saisi"}
                .
              </p>
            </section>
          )}

          {dossier.rapprochement_salaires != null && (
            <section className="dossier-section">
              <h3 className="dossier-section-titre">
                Rapprochement des impôts sur salaires
              </h3>
              <p>
                Statut :{" "}
                {dossier.rapprochement_salaires.synthese
                  ? (STATUTS_SALAIRES_FR[
                      dossier.rapprochement_salaires.synthese.statut
                    ] ?? dossier.rapprochement_salaires.synthese.statut)
                  : "—"}{" "}
                — {dossier.rapprochement_salaires.synthese
                  ?.nb_periodes_declarees ?? 0}{" "}
                période(s) déclarée(s),{" "}
                {dossier.rapprochement_salaires.synthese
                  ?.nb_ecarts_significatifs ?? 0}{" "}
                écart(s) significatif(s) (seuil :{" "}
                {formatMontant(
                  dossier.rapprochement_salaires.seuil_signification,
                )}
                ).
              </p>
              {dossier.rapprochement_salaires.ecarts_significatifs.length >
                0 && (
                <table className="dossier-table">
                  <thead>
                    <tr>
                      <th>Nature</th>
                      <th>Déclaré</th>
                      <th>Comptabilisé</th>
                      <th>Écart</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dossier.rapprochement_salaires.ecarts_significatifs.map(
                      (e, i) => (
                        <tr key={e.nature ?? i}>
                          <td>{e.libelle ?? e.nature ?? "—"}</td>
                          <td>{formatMontant(e.declare)}</td>
                          <td>{formatMontant(e.comptabilise)}</td>
                          <td>{formatMontant(e.ecart)}</td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              )}
              {dossier.rapprochement_salaires.ecarts_significatifs.some(
                (e) => e.commentaire,
              ) && (
                <p className="dossier-note">
                  {
                    dossier.rapprochement_salaires.ecarts_significatifs.find(
                      (e) => e.commentaire,
                    )?.commentaire
                  }
                </p>
              )}
            </section>
          )}

          {dossier.patente != null && (
            <section className="dossier-section">
              <h3 className="dossier-section-titre">
                Contribution des patentes estimée
              </h3>
              <p>
                Statut :{" "}
                {dossier.patente.synthese?.statut
                  ? (STATUTS_PATENTE_FR[dossier.patente.synthese.statut] ??
                    dossier.patente.synthese.libelle_statut ??
                    dossier.patente.synthese.statut)
                  : "—"}{" "}
                — {dossier.patente.synthese?.nb_comptes_ca ?? 0} compte(s)
                70x lu(s) en balance.
              </p>
              {dossier.patente.synthese?.statut === "estimation_partielle" && (
                <p>
                  Estimation totale partielle (droit sur le chiffre
                  d'affaires seul) :{" "}
                  {formatMontant(dossier.patente.estimation_totale_partielle)}
                  {dossier.patente.plancher_applique
                    ? " — plancher de 300 000 FCFA appliqué"
                    : ""}
                  . Le droit sur la valeur locative n'est pas calculable
                  depuis la balance.
                </p>
              )}
            </section>
          )}

          {dossier.charge_fiscale != null && (
            <section className="dossier-section">
              <h3 className="dossier-section-titre">
                Charge fiscale estimée
              </h3>
              <p>
                Statut :{" "}
                {dossier.charge_fiscale.synthese?.statut
                  ? (STATUTS_CHARGE_FISCALE_FR[
                      dossier.charge_fiscale.synthese.statut
                    ] ??
                    dossier.charge_fiscale.synthese.libelle_statut ??
                    dossier.charge_fiscale.synthese.statut)
                  : "—"}{" "}
                —{" "}
                {dossier.charge_fiscale.synthese
                  ?.nb_composantes_disponibles ?? 0}
                /
                {dossier.charge_fiscale.synthese?.nb_composantes_suivies ??
                  0}{" "}
                composante(s) estimée(s).
              </p>
              {dossier.charge_fiscale.synthese?.statut !==
                "indisponible" && (
                <p>
                  Total de charge propre estimé (partiel, hors TVA et hors
                  position d'acomptes) :{" "}
                  {formatMontant(
                    dossier.charge_fiscale.total_charge_propre_estimee,
                  )}
                  {dossier.charge_fiscale.composantes_incluses_total
                    .length > 0
                    ? ` — composantes incluses : ${dossier.charge_fiscale.composantes_incluses_total
                        .map(
                          (c) => COMPOSANTES_CHARGE_FISCALE_FR[c] ?? c,
                        )
                        .join(", ")}`
                    : ""}
                  .
                  {dossier.charge_fiscale.synthese?.tva_nette_declaree !=
                  null
                    ? ` TVA nette déclarée (présentée séparément) : ${formatMontant(
                        dossier.charge_fiscale.synthese.tva_nette_declaree,
                      )}.`
                    : ""}
                </p>
              )}
              {dossier.charge_fiscale.composantes_indisponibles.length >
                0 && (
                <p className="dossier-note">
                  Composantes indisponibles :{" "}
                  {dossier.charge_fiscale.composantes_indisponibles
                    .map((c) => COMPOSANTES_CHARGE_FISCALE_FR[c] ?? c)
                    .join(", ")}
                  .
                </p>
              )}
            </section>
          )}

          {dossier.completude_declarative != null && (
            <section className="dossier-section">
              <h3 className="dossier-section-titre">
                Complétude déclarative
              </h3>
              <p>
                Statut :{" "}
                {dossier.completude_declarative.synthese?.statut_global
                  ? (STATUTS_COMPLETUDE_DECLARATIVE_FR[
                      dossier.completude_declarative.synthese.statut_global
                    ] ?? dossier.completude_declarative.synthese.statut_global)
                  : "—"}{" "}
                —{" "}
                {dossier.completude_declarative.synthese
                  ?.nb_manquantes_total ?? 0}{" "}
                période(s) échue(s) sans déclaration saisie sur l'exercice{" "}
                {dossier.completude_declarative.exercice ?? "—"}.
              </p>
              {dossier.completude_declarative.impots != null && (
                <table className="dossier-table">
                  <thead>
                    <tr>
                      <th>Impôt mensuel</th>
                      <th>Statut</th>
                      <th>Périodes manquantes</th>
                      <th>Taux de couverture</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(
                      dossier.completude_declarative.impots,
                    ).map(([cle, impot]) => (
                      <tr key={cle}>
                        <td>{LIBELLES_IMPOT_COMPLETUDE_FR[cle] ?? cle}</td>
                        <td>
                          {impot.statut
                            ? (STATUTS_COMPLETUDE_DECLARATIVE_FR[
                                impot.statut
                              ] ?? impot.statut)
                            : "—"}
                        </td>
                        <td>{impot.nb_manquantes ?? "—"}</td>
                        <td>
                          {impot.taux_couverture != null
                            ? `${fmtPct(impot.taux_couverture)} %`
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className="dossier-note">
                La saisie dans l'outil ne prouve pas le dépôt effectif à la
                DGI : seuls les quittances et accusés de dépôt font foi.
              </p>
            </section>
          )}

          {dossier.coherence_ca != null && (
            <section className="dossier-section">
              <h3 className="dossier-section-titre">Cohérence CA / TVA</h3>
              <p>
                Statut :{" "}
                {dossier.coherence_ca.statut
                  ? (STATUTS_COHERENCE_CA_FR[dossier.coherence_ca.statut] ??
                    dossier.coherence_ca.statut)
                  : "—"}
                .
              </p>
              {dossier.coherence_ca.statut !== "indisponible" && (
                <p>
                  CA comptable (comptes 70x) :{" "}
                  {formatMontant(dossier.coherence_ca.ca_comptable)} — CA
                  reconstitué depuis la TVA collectée déclarée :{" "}
                  {formatMontant(dossier.coherence_ca.ca_reconstitue)} —
                  écart : {formatMontant(dossier.coherence_ca.ecart)}
                  {dossier.coherence_ca.ecart_relatif_pct != null
                    ? ` (${dossier.coherence_ca.ecart_relatif_pct} %)`
                    : ""}
                  .
                </p>
              )}
              {dossier.coherence_ca.approximation && (
                <p className="dossier-note">
                  Approximation assumée : reconstitution au seul taux normal
                  de 18 % — exonérations, taux réduits et opérations hors
                  champ ignorés. Un écart s'explique, il ne se conclut pas.
                </p>
              )}
            </section>
          )}

          {dossier.retenue_loyers != null && (
            <section className="dossier-section">
              <h3 className="dossier-section-titre">
                Retenue à la source sur loyers
              </h3>
              <p>
                Statut :{" "}
                {dossier.retenue_loyers.statut
                  ? (STATUTS_RETENUE_LOYERS_FR[
                      dossier.retenue_loyers.statut
                    ] ?? dossier.retenue_loyers.statut)
                  : "—"}
                .
              </p>
              {dossier.retenue_loyers.statut !== "indisponible" && (
                <p>
                  Loyers bruts (comptes 622x) :{" "}
                  {formatMontant(dossier.retenue_loyers.loyers_bruts)} —
                  retenue théorique maximale indicative (15 %) :{" "}
                  {formatMontant(
                    dossier.retenue_loyers.retenue_theorique_max,
                  )}
                  .
                </p>
              )}
              {dossier.retenue_loyers.repartition_calculable === false && (
                <p className="dossier-note">
                  La qualité du bailleur (personne physique ou morale,
                  régime) conditionne la retenue et n'est pas connue de la
                  balance : la répartition n'est pas calculée — seul
                  l'humain qualifie les bailleurs. Un écart s'explique, il
                  ne se conclut pas.
                </p>
              )}
            </section>
          )}

          {dossier.retenue_honoraires != null && (
            <section className="dossier-section">
              <h3 className="dossier-section-titre">
                Retenue à la source sur honoraires
              </h3>
              <p>
                Statut :{" "}
                {dossier.retenue_honoraires.statut
                  ? (STATUTS_RETENUE_HONORAIRES_FR[
                      dossier.retenue_honoraires.statut
                    ] ?? dossier.retenue_honoraires.statut)
                  : "—"}
                .
              </p>
              {dossier.retenue_honoraires.statut !== "indisponible" && (
                <p>
                  Honoraires bruts (comptes 632x) :{" "}
                  {formatMontant(dossier.retenue_honoraires.honoraires_bruts)}{" "}
                  — retenue théorique maximale indicative (7,5 %) :{" "}
                  {formatMontant(
                    dossier.retenue_honoraires.retenue_theorique_max,
                  )}
                  .
                </p>
              )}
              {dossier.retenue_honoraires.repartition_calculable ===
                false && (
                <p className="dossier-note">
                  Le régime du prestataire (résident ou non, immatriculé
                  ou non) conditionne la retenue et n'est pas connu de la
                  balance : la répartition n'est pas calculée — seul
                  l'humain qualifie les prestataires, les justificatifs
                  de retenue et quittances font foi. Un écart s'explique,
                  il ne se conclut pas.
                </p>
              )}
            </section>
          )}

          {dossier.qualite_balance != null && (
            <section className="dossier-section">
              <h3 className="dossier-section-titre">
                Contrôle qualité de la balance importée
              </h3>
              <p>
                Statut :{" "}
                {dossier.qualite_balance.statut
                  ? (STATUTS_QUALITE_BALANCE_FR[
                      dossier.qualite_balance.statut
                    ] ?? dossier.qualite_balance.statut)
                  : "—"}
                .
              </p>
              {dossier.qualite_balance.statut !== "indisponible" && (
                <p>
                  Équilibre débits/crédits :{" "}
                  {dossier.qualite_balance.equilibree
                    ? "équilibrée"
                    : `écart de ${formatMontant(
                        dossier.qualite_balance.ecart_equilibre,
                      )} — à examiner`}
                  {" — "}soldes de sens inhabituel :{" "}
                  {dossier.qualite_balance.nb_sens_inhabituels ?? "—"} —
                  comptes hors plan :{" "}
                  {dossier.qualite_balance.nb_comptes_hors_plan ?? "—"}.
                </p>
              )}
              {(dossier.qualite_balance.nb_observations ?? 0) > 0 && (
                <p className="dossier-note">
                  Ces observations orientent la revue — un sens
                  inhabituel peut être justifié (découvert bancaire,
                  avoirs, acomptes fournisseurs…) : le détail
                  s'examine dans la vue dédiée, seul l'humain conclut.
                </p>
              )}
            </section>
          )}

          {dossier.deficits_reportables != null && (
            <section className="dossier-section">
              <h3 className="dossier-section-titre">
                Déficits reportables (suivi pluriannuel)
              </h3>
              <p>
                Statut :{" "}
                {dossier.deficits_reportables.statut
                  ? (STATUTS_DEFICITS_REPORTABLES_FR[
                      dossier.deficits_reportables.statut
                    ] ?? dossier.deficits_reportables.statut)
                  : "—"}
                .
              </p>
              {dossier.deficits_reportables.statut !== "indisponible" && (
                <p>
                  {dossier.deficits_reportables.nb_exercices ?? 0} exercice
                  {(dossier.deficits_reportables.nb_exercices ?? 0) > 1
                    ? "s"
                    : ""}{" "}
                  suivi
                  {(dossier.deficits_reportables.nb_exercices ?? 0) > 1
                    ? "s"
                    : ""}{" "}
                  — {dossier.deficits_reportables.nb_deficits_constates ?? 0}{" "}
                  déficit
                  {(dossier.deficits_reportables.nb_deficits_constates ??
                    0) > 1
                    ? "s"
                    : ""}{" "}
                  constaté
                  {(dossier.deficits_reportables.nb_deficits_constates ??
                    0) > 1
                    ? "s"
                    : ""}{" "}
                  — cumul indicatif des déficits non imputés :{" "}
                  {formatMontant(
                    dossier.deficits_reportables.cumul_indicatif_final,
                  )}
                  .
                </p>
              )}
              {dossier.deficits_reportables.approximation && (
                <p className="dossier-note">
                  Approximation assumée : cumul à imputation théorique
                  maximale — les imputations réellement pratiquées dans
                  les liasses déposées ne sont pas connues de l'outil,
                  seules les liasses font foi. Le délai de report dépend
                  du CGI applicable : l'humain vérifie et décide.
                </p>
              )}
            </section>
          )}

          {dossier.rapprochement_acomptes != null && (
            <section className="dossier-section">
              <h3 className="dossier-section-titre">
                Rapprochement acomptes / IS théorique
              </h3>
              <p>
                Statut :{" "}
                {dossier.rapprochement_acomptes.statut
                  ? (STATUTS_RAPPROCHEMENT_ACOMPTES_FR[
                      dossier.rapprochement_acomptes.statut
                    ] ?? dossier.rapprochement_acomptes.statut)
                  : "—"}
                .
              </p>
              {dossier.rapprochement_acomptes.statut !== "indisponible" && (
                <p>
                  IS théorique repris du tableau de passage :{" "}
                  {formatMontant(
                    dossier.rapprochement_acomptes.is_theorique,
                  )}{" "}
                  — acomptes saisis (
                  {dossier.rapprochement_acomptes.nb_versements ?? 0}{" "}
                  versement
                  {(dossier.rapprochement_acomptes.nb_versements ?? 0) > 1
                    ? "s"
                    : ""}
                  ) :{" "}
                  {formatMontant(
                    dossier.rapprochement_acomptes.total_acomptes_saisis,
                  )}{" "}
                  — solde indicatif de liquidation :{" "}
                  {formatMontant(
                    dossier.rapprochement_acomptes.solde_indicatif,
                  )}
                  .
                </p>
              )}
              {dossier.rapprochement_acomptes.approximation && (
                <p className="dossier-note">
                  Approximation assumée : l'outil ne connaît que les
                  acomptes saisis — les quittances font foi des
                  versements réellement effectués. Le minimum de
                  perception n'est pas calculé : le solde indicatif
                  s'explique et se rapproche, il ne se conclut pas —
                  l'humain liquide et décide.
                </p>
              )}
            </section>
          )}

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
