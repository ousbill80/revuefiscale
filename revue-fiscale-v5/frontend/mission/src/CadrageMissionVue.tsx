import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { Field, SelectField } from "./Field";
import { InfoTip, Tooltip } from "./Tooltip";
import {
  FORMES_JURIDIQUES_PM,
  MOIS_CLOTURE,
  REGIMES_FISCAUX,
} from "./legalite";
import {
  CODES_IMPOT_PIVOT,
  PERIMETRE_DONS_HINT,
  PERIMETRE_EXONERATIONS_HINT,
  tipImpot,
} from "./impotLabels";
import { PROCESS_TIPS } from "./processTips";
import { libelleStatut } from "./statuts";
import type { ResumeRisques } from "./RegistreRisques";
import type { Contribuable } from "./App";
import type { MissionRow } from "./MissionsVue";

/** Pills d'engagement — langage métier de la lettre de mission. */
const ENGAGEMENTS: Array<{ value: string; titre: string; desc: string }> = [
  {
    value: "preventive",
    titre: "Revue préventive",
    desc: "Sécuriser avant tout contrôle : détection des risques et chiffrage des expositions.",
  },
  {
    value: "cac",
    titre: "Commissariat aux comptes",
    desc: "Volet fiscal de la certification des comptes.",
  },
  {
    value: "due_diligence",
    titre: "Due diligence",
    desc: "Acquisition ou cession : évaluation du passif fiscal latent.",
  },
  {
    value: "assistance_controle",
    titre: "Assistance à contrôle",
    desc: "Réponse à une vérification de l'administration en cours.",
  },
  {
    value: "autre",
    titre: "Autre",
    desc: "Cadrage libre — précisé dans la lettre de mission.",
  },
];

/**
 * Codes impôts non applicables selon le régime du client — filtre simple et
 * déterministe : les régimes forfaitaires / de l'entreprenant (IME, TEE, TCE)
 * ne rendent pas le contribuable redevable de la TVA (cotisation synthétique).
 */
const CODES_MASQUES_PAR_REGIME: Record<string, readonly string[]> = {
  ime: ["TVA"],
  tee: ["TVA"],
  tce: ["TVA"],
};

/** Suggestions rondes du seuil de signification (FCFA). */
const SEUILS_SUGGERES = [500_000, 1_000_000, 5_000_000] as const;

function fmtFcfa(v: string): string {
  const n = Number(v.replace(/\s/g, "").replace(",", "."));
  if (!Number.isFinite(n) || n <= 0) return "";
  return `${n.toLocaleString("fr-FR")} FCFA`;
}

/**
 * Dernier exercice clos selon le mois de clôture du client : si la clôture de
 * l'année en cours est déjà passée, l'exercice N est clos ; sinon c'est N-1.
 * Ex. clôture décembre + juillet 2026 → exercice 2025 suggéré.
 */
function exerciceSuggere(moisCloture: number, maintenant = new Date()): number {
  const mois = maintenant.getMonth() + 1;
  const annee = maintenant.getFullYear();
  return mois > moisCloture ? annee : annee - 1;
}

/** Coordonnées réelles du cabinet (GET /api/v1/compte) — en-tête / pied de lettre. */
export type CabinetProfil = {
  siege_social: string | null;
  commune: string | null;
  ncc: string | null;
  rccm: string | null;
  email: string | null;
  telephone: string | null;
};

export type CadrageMissionVueProps = {
  busy: boolean;
  quotaBloque: boolean;
  missionStatus: { msg: string; err: boolean } | null;
  /** Dénomination du cabinet — en-tête du document d'engagement. */
  cabinet: string;
  /** Coordonnées du cabinet — optionnelles, enrichissent la lettre. */
  cabinetProfil?: CabinetProfil | null;
  /* ------- Client : liaison au portefeuille uniquement ------- */
  clients: Contribuable[];
  missions: MissionRow[];
  contribIdExistant: number | null;
  chargerContribuable: (c: Contribuable) => void;
  /** Désélectionne le client courant. */
  reinitialiserClient: () => void;
  /** Navigation vers l'onglet Clients (création de fiche hors cadrage). */
  onAllerClients: () => void;
  /** Ouvre une mission existante (bandeau doublon). */
  onOuvrirMission: (id: number) => void;
  /* ------- Engagement & exercice ------- */
  exercice: number;
  setExercice: (v: number) => void;
  typeEngagement: string;
  setTypeEngagement: (v: string) => void;
  regime: string;
  setRegime: (v: string) => void;
  forme: string;
  setForme: (v: string) => void;
  exerciceFutur: boolean;
  exercicePrescrit: boolean;
  prescriptionConfirmee: boolean;
  setPrescriptionConfirmee: (v: boolean) => void;
  resumeRisques: ResumeRisques | null;
  pointsOuverts: Array<{
    id: number;
    texte: string;
    statut: string;
    mission_source_id?: number | null;
  }>;
  /* ------- Périmètre & affinage ------- */
  perimetreImpots: string[];
  setPerimetreImpots: Dispatch<SetStateAction<string[]>>;
  seuilSignification: string;
  setSeuilSignification: (v: string) => void;
  exclusionsDeclarees: string;
  setExclusionsDeclarees: (v: string) => void;
  objectifsLibelles: string[];
  setObjectifsLibelles: Dispatch<SetStateAction<string[]>>;
  crossBorder: boolean;
  setCrossBorder: (v: boolean) => void;
  typeEntite: string;
  setTypeEntite: (v: string) => void;
  /* ------- Action ------- */
  onCreerMission: () => void;
};

/**
 * Cadrage de mission — « document d'engagement » : à gauche des sections
 * aérées (client lié, engagement, exercice, périmètre), à droite la lettre de
 * mission rendue comme un document papier qui se rédige en direct.
 */
export function CadrageMissionVue(props: CadrageMissionVueProps) {
  const {
    busy,
    quotaBloque,
    missionStatus,
    cabinet,
    clients,
    missions,
    contribIdExistant,
    exercice,
    typeEngagement,
    regime,
    forme,
    exerciceFutur,
    exercicePrescrit,
    prescriptionConfirmee,
    perimetreImpots,
    seuilSignification,
    exclusionsDeclarees,
    objectifsLibelles,
  } = props;

  const [recherche, setRecherche] = useState("");
  const [listeOuverte, setListeOuverte] = useState(false);
  /* Saisie libre d'exercice : masquée par défaut, révélée via « Autre… ». */
  const [anneeLibreOuverte, setAnneeLibreOuverte] = useState(false);
  const comboRef = useRef<HTMLDivElement | null>(null);

  const client = useMemo(
    () => clients.find((c) => c.id === contribIdExistant) ?? null,
    [clients, contribIdExistant],
  );

  /* Fermeture du dropdown au clic extérieur. */
  useEffect(() => {
    if (!listeOuverte) return;
    const fermer = (e: MouseEvent) => {
      if (comboRef.current && !comboRef.current.contains(e.target as Node)) {
        setListeOuverte(false);
      }
    };
    document.addEventListener("mousedown", fermer);
    return () => document.removeEventListener("mousedown", fermer);
  }, [listeOuverte]);

  const resultats = useMemo(() => {
    const q = recherche.trim().toLowerCase();
    const liste = q
      ? clients.filter(
          (c) =>
            c.denomination.toLowerCase().includes(q) ||
            (c.ncc ?? "").toLowerCase().includes(q) ||
            (c.rccm ?? "").toLowerCase().includes(q),
        )
      : clients;
    return liste.slice(0, 8);
  }, [clients, recherche]);

  /* ---- Exercice suggéré selon le mois de clôture du client ---- */
  const moisCloture = client?.mois_cloture ?? 12;
  const suggestion = exerciceSuggere(moisCloture);
  const moisClotureLabel =
    MOIS_CLOTURE.find((m) => m.value === String(moisCloture))?.label ??
    `mois ${moisCloture}`;

  /* À la sélection d'un client, propose automatiquement le dernier exercice clos. */
  const dernierClientSuggere = useRef<number | null>(null);
  useEffect(() => {
    if (contribIdExistant == null) {
      dernierClientSuggere.current = null;
      return;
    }
    if (dernierClientSuggere.current === contribIdExistant) return;
    dernierClientSuggere.current = contribIdExistant;
    props.setExercice(exerciceSuggere(client?.mois_cloture ?? 12));
    props.setPrescriptionConfirmee(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contribIdExistant, client?.mois_cloture]);

  /* ---- Périmètre filtré selon le régime ---- */
  const codesMasques = CODES_MASQUES_PAR_REGIME[regime] ?? [];
  const codesVisibles = CODES_IMPOT_PIVOT.filter(
    (c) => !codesMasques.includes(c),
  );
  useEffect(() => {
    if (codesMasques.length === 0) return;
    props.setPerimetreImpots((prev) => {
      const filtre = prev.filter((c) => !codesMasques.includes(c));
      return filtre.length === prev.length ? prev : filtre;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [regime]);

  /* ---- Doublon (client, exercice) sur les missions déjà chargées ---- */
  const missionExistante = useMemo(() => {
    if (contribIdExistant == null) return null;
    return (
      missions.find(
        (m) =>
          m.contribuable_id === contribIdExistant &&
          Number(m.exercice) === Number(exercice),
      ) ?? null
    );
  }, [missions, contribIdExistant, exercice]);

  /* ---- Complétude du cadrage ---- */
  const manquants: string[] = [];
  if (contribIdExistant == null) manquants.push("client du portefeuille");
  if (!typeEngagement) manquants.push("type d'engagement");
  if (exerciceFutur) manquants.push("exercice clos (année achevée)");
  if (exercicePrescrit && !prescriptionConfirmee) {
    manquants.push("confirmation exercice prescrit");
  }
  const brouillon = manquants.length > 0;
  const pretACreer = !brouillon && !busy && !quotaBloque;

  const regimeLabel =
    REGIMES_FISCAUX.find((r) => r.value === regime)?.label ?? regime;
  const engagement = ENGAGEMENTS.find((e) => e.value === typeEngagement);
  const estPP = client?.forme === "pp";
  const formeAffichee = estPP ? "EI" : forme;
  const objectifsRemplis = objectifsLibelles
    .map((o) => o.trim())
    .filter(Boolean);
  const seuilAffiche = fmtFcfa(seuilSignification);
  const dateDuJour = new Date().toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  const anneesProposees = [suggestion, suggestion - 1, suggestion - 2];

  /* ---- Branding cabinet — uniquement les données réellement disponibles ---- */
  const profil = props.cabinetProfil ?? null;
  const monogramme =
    (cabinet || "Cabinet")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((mot) => mot.charAt(0))
      .join("")
      .toUpperCase() || "C";
  const coordonneesCabinet = [
    profil?.siege_social,
    profil?.commune,
    profil?.email,
    profil?.telephone,
  ]
    .map((v) => (v ?? "").trim())
    .filter(Boolean)
    .join(" · ");
  const nccClientCourt = (client?.ncc ?? "")
    .replace(/\s/g, "")
    .slice(0, 6)
    .toUpperCase();
  const refLettre = `LM-${exercice}-${nccClientCourt || "XXX"}`;

  return (
    <div className="cadrage2">
      {/* ================================================= Formulaire */}
      <div className="cadrage2-form">
        {/* ---------------------------------------------------- Client */}
        <section className="cadrage2-section" aria-labelledby="cadrage2-client">
          <h3 className="cadrage2-titre" id="cadrage2-client">
            Le client
          </h3>
          <p className="cadrage2-note">
            La mission est rattachée à un contribuable du portefeuille.
          </p>

          {client ? (
            <div className="cadrage2-client-carte" role="status">
              <span className="cadrage2-client-initiale" aria-hidden="true">
                {client.denomination.trim().charAt(0).toUpperCase() || "?"}
              </span>
              <div className="cadrage2-client-infos">
                <strong>{client.denomination}</strong>
                <span>
                  {estPP ? "Personne physique" : "Personne morale"}
                  {client.ncc ? ` · NCC ${client.ncc}` : ""}
                  {client.rccm ? ` · RCCM ${client.rccm}` : ""}
                </span>
                <span>
                  {regimeLabel}
                  {client.commune ? ` · ${client.commune}` : ""}
                  {` · clôture ${moisClotureLabel.toLowerCase()}`}
                </span>
              </div>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  props.reinitialiserClient();
                  setRecherche("");
                  setListeOuverte(false);
                }}
              >
                Changer
              </button>
            </div>
          ) : (
            <div className="cadrage2-combo" ref={comboRef}>
              <input
                type="search"
                className="cadrage2-combo-input"
                role="combobox"
                aria-expanded={listeOuverte}
                aria-controls="cadrage2-combo-liste"
                aria-label="Rechercher un client du portefeuille"
                placeholder="Rechercher un client — nom, NCC, RCCM…"
                value={recherche}
                onChange={(e) => {
                  setRecherche(e.target.value);
                  setListeOuverte(true);
                }}
                onFocus={() => setListeOuverte(true)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") setListeOuverte(false);
                }}
              />
              {listeOuverte && (
                <div
                  className="cadrage2-combo-liste"
                  id="cadrage2-combo-liste"
                  role="listbox"
                  aria-label="Clients du portefeuille"
                >
                  {resultats.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      role="option"
                      aria-selected={false}
                      className="cadrage2-combo-item"
                      onClick={() => {
                        props.chargerContribuable(c);
                        setListeOuverte(false);
                        setRecherche("");
                      }}
                    >
                      <strong>{c.denomination}</strong>
                      <span>
                        {(c.forme === "pp" ? "PP" : "PM") +
                          (c.ncc ? ` · NCC ${c.ncc}` : "") +
                          (c.regime_fiscal
                            ? ` · ${
                                REGIMES_FISCAUX.find(
                                  (r) => r.value === c.regime_fiscal,
                                )?.label ?? c.regime_fiscal
                              }`
                            : "")}
                      </span>
                    </button>
                  ))}
                  {resultats.length === 0 && (
                    <p className="cadrage2-combo-vide">
                      {clients.length === 0
                        ? "Portefeuille vide — créez d'abord un client."
                        : `Aucun client ne correspond à « ${recherche} ».`}
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          <p className="cadrage2-lien-clients">
            Client absent du portefeuille ?{" "}
            <button
              type="button"
              className="linkish"
              onClick={props.onAllerClients}
            >
              Créez-le dans l&apos;onglet Clients
            </button>
          </p>
        </section>

        {/* ------------------------------------------------ Engagement */}
        <section
          className={`cadrage2-section${client ? "" : " is-locked"}`}
          aria-labelledby="cadrage2-engagement"
          aria-disabled={!client}
        >
          <h3 className="cadrage2-titre label-with-tip" id="cadrage2-engagement">
            L&apos;engagement
            <InfoTip
              label={PROCESS_TIPS.typeEngagement}
              ariaLabel="Aide : type d'engagement"
            />
          </h3>
          <p className="cadrage2-note">
            Ce que le cabinet s&apos;engage à faire — figé dès le passage de la
            mission en cours.
          </p>

          <div
            className="cadrage2-pills"
            role="radiogroup"
            aria-label="Type d'engagement"
          >
            {ENGAGEMENTS.map((e) => {
              const on = typeEngagement === e.value;
              return (
                <button
                  key={e.value}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  title={e.desc}
                  className={`cadrage2-pill${on ? " is-on" : ""}`}
                  onClick={() => props.setTypeEngagement(e.value)}
                >
                  {e.titre}
                </button>
              );
            })}
          </div>
          {engagement ? (
            <p className="cadrage2-pill-desc" role="status">
              {engagement.desc}
            </p>
          ) : (
            <p className="cadrage2-pill-desc is-vide">
              Choix obligatoire — survolez une pill pour sa description.
            </p>
          )}

          <div className="cadrage2-exercice">
            <p className="cadrage2-sous-titre label-with-tip">
              Exercice contrôlé
              <InfoTip
                label={PROCESS_TIPS.exercice}
                ariaLabel="Aide : exercice"
              />
            </p>
            <div className="cadrage2-exercice-row">
              {anneesProposees.map((annee) => {
                const suggere = annee === suggestion;
                return (
                  <button
                    key={annee}
                    type="button"
                    className={`cadrage2-annee${exercice === annee ? " is-on" : ""}`}
                    onClick={() => {
                      props.setExercice(annee);
                      props.setPrescriptionConfirmee(false);
                      setAnneeLibreOuverte(false);
                    }}
                  >
                    {annee}
                    {suggere && <small>suggéré</small>}
                  </button>
                );
              })}
              {anneeLibreOuverte || !anneesProposees.includes(exercice) ? (
                <input
                  type="number"
                  className="cadrage2-annee-libre"
                  aria-label="Exercice — saisie libre"
                  autoFocus={anneeLibreOuverte}
                  value={exercice}
                  onChange={(e) => {
                    props.setExercice(Number(e.target.value));
                    props.setPrescriptionConfirmee(false);
                  }}
                />
              ) : (
                <button
                  type="button"
                  className="cadrage2-annee cadrage2-annee-autre"
                  onClick={() => setAnneeLibreOuverte(true)}
                >
                  Autre…
                </button>
              )}
            </div>
            {client && (
              <p className="cadrage2-note">
                Clôture {moisClotureLabel.toLowerCase()} — dernier exercice clos
                : {suggestion}.
              </p>
            )}
            {exerciceFutur && (
              <p className="status err" role="alert">
                L&apos;exercice {exercice} n&apos;est pas encore clos — une
                revue fiscale porte sur un exercice achevé.
              </p>
            )}
            {exercicePrescrit && (
              <label className="check check-card cadrage2-prescrit">
                <input
                  type="checkbox"
                  checked={prescriptionConfirmee}
                  onChange={(e) =>
                    props.setPrescriptionConfirmee(e.target.checked)
                  }
                />
                <span>
                  <strong>
                    Exercice antérieur à N-3 : en principe prescrit (art. L171
                    s. LPF)
                  </strong>
                  <small>
                    Confirmez que la revue est volontaire (contentieux, contrôle
                    en cours…).
                  </small>
                </span>
              </label>
            )}
          </div>

          {missionExistante && (
            <div className="cadrage2-doublon" role="alert">
              <p>
                <strong>
                  Mission déjà ouverte pour ce client sur l&apos;exercice{" "}
                  {exercice}
                </strong>{" "}
                — #{missionExistante.id} ·{" "}
                {libelleStatut(missionExistante.statut)}. La création sera
                refusée (doublon).
              </p>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => props.onOuvrirMission(missionExistante.id)}
              >
                Ouvrir la mission existante
              </button>
            </div>
          )}

          <div className="field-grid field-grid-2 cadrage2-profil">
            <SelectField
              id="cadrage-regime"
              label="Régime fiscal"
              value={regime}
              onChange={(e) => props.setRegime(e.target.value)}
              options={REGIMES_FISCAUX.map((r) => ({
                value: r.value,
                label: r.label,
              }))}
              required
              tip={PROCESS_TIPS.regime}
            />
            {estPP ? (
              <div className="field">
                <p className="field-hint cadrage2-forme-pp">
                  Personne physique — forme juridique EI (entreprise
                  individuelle).
                </p>
              </div>
            ) : (
              <SelectField
                id="cadrage-forme-jur"
                label="Forme juridique"
                value={forme}
                onChange={(e) => props.setForme(e.target.value)}
                options={FORMES_JURIDIQUES_PM}
                required
                tip={PROCESS_TIPS.formeJuridique}
              />
            )}
          </div>
          <p className="field-hint cadrage2-profil-hint">
            Régime et forme préremplis depuis la fiche client — modifiables.
          </p>

          {props.resumeRisques && props.resumeRisques.total > 0 ? (
            <div
              className="points-ouverts-bandeau risques-resume-bandeau"
              role="status"
              aria-label="Résumé registre des risques N+1"
            >
              <p className="picker-kicker">Suivi N+1 — registre des risques</p>
              <p className="picker-hint">
                {props.resumeRisques.total} risque
                {props.resumeRisques.total > 1 ? "s" : ""},{" "}
                {props.resumeRisques.ouverts} ouvert
                {props.resumeRisques.ouverts > 1 ? "s" : ""} / en traitement,{" "}
                {props.resumeRisques.traites} traité
                {props.resumeRisques.traites > 1 ? "s" : ""},{" "}
                {props.resumeRisques.actions_en_retard} en retard,{" "}
                {props.resumeRisques.acceptes_client} accepté
                {props.resumeRisques.acceptes_client > 1 ? "s" : ""} client
                {props.resumeRisques.actions_refusees > 0
                  ? `, ${props.resumeRisques.actions_refusees} action(s) refusée(s)`
                  : ""}
                .
              </p>
            </div>
          ) : props.pointsOuverts.length > 0 ? (
            <div
              className="points-ouverts-bandeau"
              role="status"
              aria-label="Points ouverts legacy"
            >
              <p className="picker-kicker">
                Points ouverts legacy ({props.pointsOuverts.length})
              </p>
              <p className="picker-hint">
                Ancien pont inter-exercices — basculé vers le registre risques
                (R4). Lecture seule.
              </p>
              <ul className="points-ouverts-list">
                {props.pointsOuverts.map((p) => (
                  <li key={p.id}>
                    <span className="badge">ouvert</span>
                    {p.mission_source_id != null
                      ? ` Mission #${p.mission_source_id} — `
                      : " "}
                    {p.texte}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>

        {/* ------------------------------------------------- Périmètre */}
        <section
          className={`cadrage2-section${client && typeEngagement ? "" : " is-locked"}`}
          aria-labelledby="cadrage2-perimetre"
          aria-disabled={!(client && typeEngagement)}
        >
          <h3 className="cadrage2-titre label-with-tip" id="cadrage2-perimetre">
            Le périmètre
            <InfoTip
              label={PROCESS_TIPS.perimetreImpots}
              ariaLabel="Aide : périmètre impôts"
            />
          </h3>
          <p className="cadrage2-note">
            Par défaut, revue complète : tous les impôts du référentiel.
            Activez des chips pour restreindre le périmètre.
          </p>

          <div
            className="cadrage2-chips"
            role="group"
            aria-label="Codes impôts du périmètre"
          >
            {codesVisibles.map((code) => {
              const checked = perimetreImpots.includes(code);
              return (
                <Tooltip key={code} label={tipImpot(code)} side="bottom">
                  <label className={`cadrage2-chip${checked ? " is-on" : ""}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => {
                        props.setPerimetreImpots((prev) =>
                          checked
                            ? prev.filter((c) => c !== code)
                            : [...prev, code],
                        );
                      }}
                    />
                    {code}
                  </label>
                </Tooltip>
              );
            })}
          </div>
          {codesMasques.length > 0 && (
            <p className="cadrage2-note cadrage2-filtre-note" role="status">
              {codesMasques.join(", ")} masqué
              {codesMasques.length > 1 ? "s" : ""} — non applicable au régime{" "}
              {regimeLabel.toLowerCase()} (cotisation synthétique, hors champ
              TVA).
            </p>
          )}
          <p className="field-hint">
            {perimetreImpots.length > 0 ? (
              <>
                Revue <strong>partielle</strong> — {perimetreImpots.join(", ")}.
              </>
            ) : (
              "Aucune chip active = revue complète."
            )}
          </p>
          <p className="field-hint label-with-tip impot-ref-hints">
            {PERIMETRE_EXONERATIONS_HINT}
            <InfoTip
              label={PROCESS_TIPS.perimetreExonerations}
              ariaLabel="Aide : exonérations référentiel"
            />
          </p>
          <p className="field-hint label-with-tip impot-ref-hints">
            {PERIMETRE_DONS_HINT}
            <InfoTip
              label={PROCESS_TIPS.perimetreDons}
              ariaLabel="Aide : dons et libéralités"
            />
          </p>

          <div className="cadrage2-seuil">
            <Field
              id="cadrage-seuil"
              label="Seuil de signification (FCFA)"
              type="number"
              min={0}
              step="1"
              value={seuilSignification}
              onChange={(e) => props.setSeuilSignification(e.target.value)}
              tip={PROCESS_TIPS.seuilSignification}
              hint="Matérialité cabinet — optionnel."
            />
            <div
              className="cadrage2-seuil-suggestions"
              role="group"
              aria-label="Suggestions de seuil"
            >
              {SEUILS_SUGGERES.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`cadrage2-seuil-btn${
                    Number(seuilSignification) === s ? " is-on" : ""
                  }`}
                  onClick={() => props.setSeuilSignification(String(s))}
                >
                  {s.toLocaleString("fr-FR")}
                </button>
              ))}
            </div>
          </div>

          <details className="cadrage2-affiner">
            <summary>Affiner le cadrage (optionnel)</summary>
            <div className="cadrage2-affiner-corps">
              <Field
                id="cadrage-type-entite"
                label="Type d'entité"
                value={props.typeEntite}
                onChange={(e) => props.setTypeEntite(e.target.value)}
                tip={PROCESS_TIPS.typeEntite}
                hint="Optionnel — précise le profil pour le moteur."
              />
              <label className="check check-card">
                <input
                  type="checkbox"
                  checked={props.crossBorder}
                  onChange={(e) => props.setCrossBorder(e.target.checked)}
                />
                <span>
                  <strong className="label-with-tip">
                    Opérations cross-border
                    <InfoTip
                      label={PROCESS_TIPS.crossBorder}
                      ariaLabel="Aide : opérations cross-border"
                    />
                  </strong>
                  <small>
                    Active les contrôles liés aux flux internationaux.
                  </small>
                </span>
              </label>
              <div className="field cadrage2-affiner-pleine">
                <p className="label-with-tip impot-perimetre-lbl">
                  Objectifs de la mission
                  <InfoTip
                    label={PROCESS_TIPS.objectifsMission}
                    ariaLabel="Aide : objectifs mission"
                  />
                </p>
                <ul className="objectifs-edit-list">
                  {objectifsLibelles.map((lib, idx) => (
                    <li key={`obj-${idx}`}>
                      <input
                        className="field-input"
                        type="text"
                        value={lib}
                        maxLength={500}
                        placeholder={`Objectif ${idx + 1}`}
                        aria-label={`Objectif ${idx + 1}`}
                        onChange={(e) => {
                          const v = e.target.value;
                          props.setObjectifsLibelles((prev) =>
                            prev.map((x, i) => (i === idx ? v : x)),
                          );
                        }}
                      />
                      <Tooltip label={`Retirer l'objectif ${idx + 1}`}>
                        <button
                          type="button"
                          className="cadrage2-obj-retirer"
                          disabled={objectifsLibelles.length <= 1}
                          aria-label={`Retirer l'objectif ${idx + 1}`}
                          onClick={() => {
                            props.setObjectifsLibelles((prev) =>
                              prev.length <= 1
                                ? prev
                                : prev.filter((_, i) => i !== idx),
                            );
                          }}
                        >
                          ×
                        </button>
                      </Tooltip>
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  disabled={objectifsLibelles.length >= 50}
                  onClick={() =>
                    props.setObjectifsLibelles((prev) => [...prev, ""])
                  }
                >
                  Ajouter un objectif
                </button>
              </div>
              <div className="field cadrage2-affiner-pleine">
                <label
                  className="field-label-static"
                  htmlFor="cadrage-exclusions"
                >
                  Exclusions déclarées
                </label>
                <textarea
                  id="cadrage-exclusions"
                  className="field-input field-textarea cadrage2-exclusions"
                  rows={3}
                  value={exclusionsDeclarees}
                  onChange={(e) =>
                    props.setExclusionsDeclarees(e.target.value)
                  }
                  placeholder="Ex. hors contrôles sur place…"
                />
                <p className="field-hint">
                  {PROCESS_TIPS.exclusionsDeclarees}
                </p>
              </div>
            </div>
          </details>
        </section>
      </div>

      {/* ============================================ Document — lettre */}
      <aside
        className="cadrage2-doc-col"
        aria-label="Lettre de mission — document d'engagement"
      >
        <article className={`cadrage2-doc${brouillon ? " is-brouillon" : ""}`}>
          {brouillon && (
            <span className="cadrage2-filigrane" aria-hidden="true">
              Brouillon
            </span>
          )}
          <span className="cadrage2-doc-bande" aria-hidden="true" />
          <header className="cadrage2-doc-head">
            <div className="cadrage2-doc-identite">
              <span className="cadrage2-doc-monogramme" aria-hidden="true">
                {monogramme}
              </span>
              <div className="cadrage2-doc-cab">
                <p className="cadrage2-doc-cabinet">{cabinet || "Cabinet"}</p>
                {coordonneesCabinet && (
                  <p className="cadrage2-doc-coords">{coordonneesCabinet}</p>
                )}
              </div>
            </div>
            <p className="cadrage2-doc-ref">
              Réf. {refLettre} · Abidjan, le {dateDuJour}
            </p>
          </header>

          <p className="cadrage2-doc-objet">
            <span>
              Objet : Lettre de mission —{" "}
              {engagement ? engagement.titre : "engagement à préciser"} ·
              exercice {exercice}
            </span>
          </p>

          <div className="cadrage2-doc-corps">
            <p>
              Le cabinet <strong>{cabinet || "—"}</strong> est engagé par{" "}
              {client ? (
                <>
                  <strong>{client.denomination}</strong>
                  {client.ncc ? (
                    <>
                      {" "}
                      (NCC <strong>{client.ncc}</strong>)
                    </>
                  ) : null}
                  , {formeAffichee} relevant du régime{" "}
                  <strong>{regimeLabel.toLowerCase()}</strong>
                  {client.commune ? (
                    <>
                      , sise à <strong>{client.commune}</strong>
                    </>
                  ) : null}
                  ,
                </>
              ) : (
                <em className="cadrage2-doc-blanc">
                  [client à lier au cadrage]
                </em>
              )}{" "}
              pour la réalisation d&apos;une mission de{" "}
              {engagement ? (
                <strong>{engagement.titre.toLowerCase()}</strong>
              ) : (
                <em className="cadrage2-doc-blanc">
                  [type d&apos;engagement à choisir]
                </em>
              )}
              .
            </p>
            <p>
              La mission porte sur l&apos;exercice clos{" "}
              {exerciceFutur ? (
                <em className="cadrage2-doc-blanc">
                  [exercice {exercice} non clos — à corriger]
                </em>
              ) : (
                <>
                  <strong>{exercice}</strong>
                  {exercicePrescrit &&
                    (prescriptionConfirmee
                      ? ", exercice en principe prescrit — revue volontaire confirmée par le cabinet"
                      : ", exercice en principe prescrit — confirmation requise")}
                </>
              )}
              .
            </p>
            <p>
              {perimetreImpots.length > 0 ? (
                <>
                  Le périmètre des travaux est limité aux impôts suivants :{" "}
                  <strong>{perimetreImpots.join(", ")}</strong>.
                </>
              ) : (
                <>
                  Les travaux couvrent l&apos;ensemble des impôts du
                  référentiel — <strong>revue complète</strong>.
                </>
              )}
              {codesMasques.length > 0 && (
                <>
                  {" "}
                  La {codesMasques.join(", ")} est hors champ compte tenu du
                  régime du client.
                </>
              )}
            </p>
            {seuilAffiche && (
              <p>
                Le seuil de signification retenu est fixé à{" "}
                <strong>{seuilAffiche}</strong>.
              </p>
            )}
            {objectifsRemplis.length > 0 && (
              <p>
                Les objectifs convenus sont les suivants :{" "}
                <strong>{objectifsRemplis.join(" ; ")}</strong>.
              </p>
            )}
            {exclusionsDeclarees.trim() && (
              <p>
                Sont expressément exclus des travaux :{" "}
                <strong>{exclusionsDeclarees.trim()}</strong>.
              </p>
            )}
            {props.crossBorder && (
              <p>
                Les contrôles portant sur les{" "}
                <strong>opérations cross-border</strong> (flux internationaux)
                sont inclus dans la mission.
              </p>
            )}
          </div>

          <footer className="cadrage2-doc-pied">
            {quotaBloque && (
              <p className="status err" role="alert">
                Quota missions atteint — la création est bloquée.
              </p>
            )}
            {missionStatus && (
              <p
                className={`status${missionStatus.err ? " err" : ""}`}
                role={missionStatus.err ? "alert" : "status"}
              >
                {missionStatus.msg}
              </p>
            )}
            <div className="cadrage2-doc-sign">
              <p className="cadrage2-doc-sign-pour">Pour le cabinet,</p>
              <p className="cadrage2-doc-sign-nom">{cabinet || "—"}</p>
              <span className="cadrage2-doc-sign-trait" aria-hidden="true" />
            </div>
            <div className="cadrage2-signature">
              <p className="cadrage2-signature-lieu">
                Fait pour valoir engagement de mission
              </p>
              <button
                type="button"
                className="btn btn-primary cadrage2-creer"
                disabled={!pretACreer}
                onClick={props.onCreerMission}
              >
                {busy ? "Création…" : "Créer la mission"}
              </button>
              {manquants.length > 0 && (
                <p className="cadrage2-manque" role="status">
                  Manque : {manquants.join(" · ")}.
                </p>
              )}
            </div>
            <p className="cadrage2-doc-footer">
              {[cabinet || "Cabinet", coordonneesCabinet]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </footer>
        </article>
      </aside>
    </div>
  );
}
