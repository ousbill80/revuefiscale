import {
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { Field, SelectField } from "./Field";
import { InfoTip, Tooltip } from "./Tooltip";
import {
  FORMES_JURIDIQUES_PM,
  FORMES_PERSONNE,
  MOIS_CLOTURE,
  REGIMES_FISCAUX,
  SECTEURS_ACTIVITE,
  composerActivite,
  decomposerActivite,
  type FormePersonne,
} from "./legalite";
import {
  CODES_IMPOT_PIVOT,
  PERIMETRE_DONS_HINT,
  PERIMETRE_EXONERATIONS_HINT,
  tipImpot,
} from "./impotLabels";
import { PROCESS_TIPS } from "./processTips";
import type { ResumeRisques } from "./RegistreRisques";
import type { Contribuable } from "./App";

/** Cartes d'engagement — langage métier de la lettre de mission. */
const ENGAGEMENTS: Array<{ value: string; titre: string; desc: string }> = [
  {
    value: "preventive",
    titre: "Revue préventive",
    desc: "Sécuriser avant tout contrôle : détection des risques et chiffrage des expositions.",
  },
  {
    value: "cac",
    titre: "Commissariat aux comptes",
    desc: "Volet fiscal de la certification.",
  },
  {
    value: "due_diligence",
    titre: "Due diligence",
    desc: "Acquisition/cession : passif fiscal latent.",
  },
  {
    value: "assistance_controle",
    titre: "Assistance à contrôle",
    desc: "Réponse à une vérification en cours.",
  },
  {
    value: "autre",
    titre: "Autre",
    desc: "Cadrage libre — précisé dans la lettre de mission.",
  },
];

function fmtFcfa(v: string): string {
  const n = Number(v.replace(/\s/g, "").replace(",", "."));
  if (!Number.isFinite(n) || n <= 0) return "";
  return `${n.toLocaleString("fr-FR")} FCFA`;
}

export type CadrageMissionVueProps = {
  busy: boolean;
  quotaBloque: boolean;
  missionStatus: { msg: string; err: boolean } | null;
  /* ------- Qui : portefeuille + fiche contribuable ------- */
  clients: Contribuable[];
  contribIdExistant: number | null;
  contribNom: string;
  setContribNom: (v: string) => void;
  contribNcc: string;
  setContribNcc: (v: string) => void;
  contribForme: FormePersonne;
  setContribForme: (v: FormePersonne) => void;
  contribRccm: string;
  setContribRccm: (v: string) => void;
  contribDfe: string;
  setContribDfe: (v: string) => void;
  contribSiege: string;
  setContribSiege: (v: string) => void;
  contribCommune: string;
  setContribCommune: (v: string) => void;
  contribCentreImpots: string;
  setContribCentreImpots: (v: string) => void;
  contribCapital: string;
  setContribCapital: (v: string) => void;
  contribMoisCloture: string;
  setContribMoisCloture: (v: string) => void;
  contribActivite: string;
  setContribActivite: (v: string) => void;
  contribDateImmat: string;
  setContribDateImmat: (v: string) => void;
  chargerContribuable: (c: Contribuable) => void;
  /** Repart sur une fiche vierge (désélectionne le client). */
  reinitialiserClient: () => void;
  apiMin: { ok: boolean; manquants: string[] };
  conflitFiche: {
    champ: string;
    valeur: string;
    client: Contribuable;
  } | null;
  /* ------- Quoi : engagement & exercice ------- */
  exercice: number;
  setExercice: (v: number) => void;
  typeEngagement: string;
  setTypeEngagement: (v: string) => void;
  regime: string;
  setRegime: (v: string) => void;
  forme: string;
  setForme: (v: string) => void;
  setSecteur: (v: string) => void;
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
  /* ------- Comment : périmètre & affinage ------- */
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
 * Cadrage de mission — « on ne remplit pas un formulaire, on cadre une
 * lettre de mission » : Qui / Quoi / Comment + lettre récapitulative sticky.
 */
export function CadrageMissionVue(props: CadrageMissionVueProps) {
  const {
    busy,
    quotaBloque,
    missionStatus,
    clients,
    contribIdExistant,
    apiMin,
    conflitFiche,
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
  const [modeCreation, setModeCreation] = useState(false);

  const anneeCourante = new Date().getFullYear();
  const clientChoisi = contribIdExistant != null;

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
    return liste.slice(0, 12);
  }, [clients, recherche]);

  /** Le bloc « Qui » est acquis : client existant ou fiche neuve valide. */
  const quiOk = contribIdExistant != null || (apiMin.ok && !conflitFiche);
  const quoiOk = !!typeEngagement && !exerciceFutur;

  const manquants: string[] = [];
  if (contribIdExistant == null && !apiMin.ok) {
    manquants.push(`client (${apiMin.manquants.join(", ")})`);
  }
  if (conflitFiche) {
    manquants.push(`doublon ${conflitFiche.champ} à résoudre`);
  }
  if (!typeEngagement) manquants.push("type d'engagement");
  if (exerciceFutur) manquants.push("exercice clos (année achevée)");
  if (exercicePrescrit && !prescriptionConfirmee) {
    manquants.push("confirmation exercice prescrit");
  }
  const pretACreer = manquants.length === 0 && !busy && !quotaBloque;

  const regimeLabel =
    REGIMES_FISCAUX.find((r) => r.value === regime)?.label ?? regime;
  const engagement = ENGAGEMENTS.find((e) => e.value === typeEngagement);
  const formeAffichee = props.contribForme === "pp" ? "EI" : forme;
  const objectifsRemplis = objectifsLibelles
    .map((o) => o.trim())
    .filter(Boolean);
  const seuilAffiche = fmtFcfa(seuilSignification);
  const activiteDecomposee = decomposerActivite(props.contribActivite);

  const renderFicheClient = () => (
    <div className="cadrage-fiche">
      <div
        className="persona-toggle"
        role="group"
        aria-label="Type de contribuable"
      >
        {FORMES_PERSONNE.map((p) => (
          <Tooltip key={p.value} label={p.hint} side="bottom">
            <button
              type="button"
              className={`persona-btn${props.contribForme === p.value ? " active" : ""}`}
              onClick={() => {
                props.setContribForme(p.value);
                if (p.value === "pp") props.setForme("EI");
                else if (forme === "EI") props.setForme("SA");
              }}
            >
              <strong>{p.label}</strong>
              <small>
                {p.value === "pm"
                  ? "Entreprise · RCCM + NCC"
                  : "Individuel · fiche allégée"}
              </small>
            </button>
          </Tooltip>
        ))}
      </div>
      <div className="field-grid field-grid-2">
        <Field
          id="cadrage-nom"
          label={
            props.contribForme === "pm"
              ? "Dénomination / raison sociale"
              : "Nom du contribuable"
          }
          value={props.contribNom}
          onChange={(e) => props.setContribNom(e.target.value)}
          required
          autoComplete="organization"
        />
        <Field
          id="cadrage-ncc"
          label="NCC"
          value={props.contribNcc}
          onChange={(e) => props.setContribNcc(e.target.value)}
          required
          spellCheck={false}
          tip={PROCESS_TIPS.ncc}
        />
        {props.contribForme === "pm" && (
          <>
            <Field
              id="cadrage-rccm"
              label="RCCM"
              value={props.contribRccm}
              onChange={(e) => props.setContribRccm(e.target.value)}
              required
              spellCheck={false}
            />
            <Field
              id="cadrage-dfe"
              label="Réf. DFE (optionnel)"
              value={props.contribDfe}
              onChange={(e) => props.setContribDfe(e.target.value)}
              spellCheck={false}
              tip={PROCESS_TIPS.dfe}
            />
            <Field
              id="cadrage-capital"
              label="Capital social"
              type="number"
              inputMode="decimal"
              min={0}
              step="1"
              value={props.contribCapital}
              onChange={(e) => props.setContribCapital(e.target.value)}
              required
              trailing="XOF"
            />
          </>
        )}
        <SelectField
          id="cadrage-cloture"
          label="Clôture d'exercice"
          value={props.contribMoisCloture}
          onChange={(e) => props.setContribMoisCloture(e.target.value)}
          options={MOIS_CLOTURE}
          required
        />
        <SelectField
          id="cadrage-secteur"
          label="Secteur d'activité"
          value={activiteDecomposee.secteur}
          onChange={(e) => {
            const next = composerActivite(
              e.target.value,
              activiteDecomposee.precision,
            );
            props.setContribActivite(next);
            props.setSecteur(next);
          }}
          options={SECTEURS_ACTIVITE}
          required
          tip={PROCESS_TIPS.secteur}
        />
        <Field
          id="cadrage-activite-prec"
          label="Précision d'activité"
          value={activiteDecomposee.precision}
          onChange={(e) => {
            const next = composerActivite(
              activiteDecomposee.secteur,
              e.target.value,
            );
            props.setContribActivite(next);
            props.setSecteur(next);
          }}
        />
        <Field
          id="cadrage-immat"
          label="Date d'immatriculation"
          type="date"
          value={props.contribDateImmat}
          onChange={(e) => props.setContribDateImmat(e.target.value)}
        />
        <Field
          id="cadrage-commune"
          label="Ville / commune"
          value={props.contribCommune}
          onChange={(e) => props.setContribCommune(e.target.value)}
          required
          tip={PROCESS_TIPS.siegeEffectif}
        />
        <Field
          id="cadrage-siege"
          label="Adresse / quartier"
          value={props.contribSiege}
          onChange={(e) => props.setContribSiege(e.target.value)}
          required={props.contribForme === "pm"}
        />
        <Field
          id="cadrage-centre"
          label="Centre des impôts"
          value={props.contribCentreImpots}
          onChange={(e) => props.setContribCentreImpots(e.target.value)}
          required
          tip={PROCESS_TIPS.centreImpots}
        />
      </div>
      {conflitFiche && (
        <div className="conflit-fiche" role="alert">
          <p className="conflit-fiche-titre">
            Cette entreprise existe déjà : «{" "}
            {conflitFiche.client.denomination} » (#{conflitFiche.client.id})
          </p>
          <p className="conflit-fiche-detail">
            Le {conflitFiche.champ} « {conflitFiche.valeur} » est déjà
            rattaché à cette fiche de votre portefeuille — utilisez la fiche
            existante, le cadrage saisi est conservé.
          </p>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => {
              props.chargerContribuable(conflitFiche.client);
              setModeCreation(false);
            }}
          >
            Utiliser la fiche existante
          </button>
        </div>
      )}
    </div>
  );

  return (
    <div className="cadrage">
      <div className="cadrage-main">
        {/* ------------------------------------------------ Bloc 1 — Qui */}
        <section className="cadrage-bloc" aria-labelledby="cadrage-qui">
          <header className="cadrage-bloc-head">
            <span className="cadrage-bloc-n" aria-hidden="true">
              1
            </span>
            <div>
              <h3 id="cadrage-qui">Qui — le client</h3>
              <p>
                La mission commence par le contribuable : cherchez-le dans le
                portefeuille ou créez sa fiche.
              </p>
            </div>
          </header>

          {clientChoisi ? (
            <div className="cadrage-client-resume" role="status">
              <div>
                <strong>{props.contribNom || "—"}</strong>
                <span>
                  {props.contribForme.toUpperCase()}
                  {props.contribNcc.trim()
                    ? ` · NCC ${props.contribNcc.trim()}`
                    : ""}
                  {` · ${regimeLabel} · ${formeAffichee}`}
                </span>
              </div>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  props.reinitialiserClient();
                  setModeCreation(false);
                  setRecherche("");
                }}
              >
                Changer
              </button>
            </div>
          ) : (
            <>
              {clients.length > 0 && !modeCreation && (
                <>
                  <input
                    type="search"
                    className="field-input cadrage-search"
                    placeholder="Rechercher un contribuable — nom, NCC, RCCM…"
                    aria-label="Rechercher un contribuable"
                    value={recherche}
                    onChange={(e) => setRecherche(e.target.value)}
                  />
                  <div className="cadrage-clients" role="list">
                    {resultats.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        role="listitem"
                        className="cadrage-client-card"
                        onClick={() => {
                          props.chargerContribuable(c);
                          setModeCreation(false);
                        }}
                      >
                        <strong>{c.denomination}</strong>
                        <span>
                          {(c.forme || "pm").toUpperCase()}
                          {c.ncc ? ` · NCC ${c.ncc}` : ""}
                          {c.regime_fiscal
                            ? ` · ${
                                REGIMES_FISCAUX.find(
                                  (r) => r.value === c.regime_fiscal,
                                )?.label ?? c.regime_fiscal
                              }`
                            : ""}
                          {c.forme_juridique ? ` · ${c.forme_juridique}` : ""}
                        </span>
                      </button>
                    ))}
                    {resultats.length === 0 && (
                      <p className="empty-state">
                        Aucun contribuable ne correspond à « {recherche} ».
                      </p>
                    )}
                  </div>
                </>
              )}
              <button
                type="button"
                className="linkish cadrage-creer-lien"
                onClick={() => {
                  if (!modeCreation) props.reinitialiserClient();
                  setModeCreation(!modeCreation);
                }}
              >
                {modeCreation
                  ? "← Revenir à la recherche"
                  : "Créer un nouveau client"}
              </button>
              {(modeCreation || clients.length === 0) && renderFicheClient()}
            </>
          )}
        </section>

        {/* ----------------------------------------------- Bloc 2 — Quoi */}
        <section
          className={`cadrage-bloc${quiOk ? "" : " is-locked"}`}
          aria-labelledby="cadrage-quoi"
          aria-disabled={!quiOk}
        >
          <header className="cadrage-bloc-head">
            <span className="cadrage-bloc-n" aria-hidden="true">
              2
            </span>
            <div>
              <h3 id="cadrage-quoi" className="label-with-tip">
                Quoi — l&apos;engagement
                <InfoTip
                  label={PROCESS_TIPS.typeEngagement}
                  ariaLabel="Aide : type d'engagement"
                />
              </h3>
              <p>
                Ce que le cabinet s&apos;engage à faire — figé dès le passage
                de la mission en cours.
              </p>
            </div>
          </header>

          <div
            className="engagement-cards"
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
                  className={`engagement-card${on ? " is-on" : ""}`}
                  onClick={() => props.setTypeEngagement(e.value)}
                >
                  <strong>{e.titre}</strong>
                  <span>{e.desc}</span>
                </button>
              );
            })}
          </div>

          <div className="cadrage-exercice">
            <p className="label-with-tip cadrage-sous-titre">
              Exercice contrôlé
              <InfoTip
                label={PROCESS_TIPS.exercice}
                ariaLabel="Aide : exercice"
              />
            </p>
            <div className="cadrage-exercice-row">
              {[1, 2, 3].map((delta) => {
                const annee = anneeCourante - delta;
                return (
                  <button
                    key={annee}
                    type="button"
                    className={`exercice-btn${exercice === annee ? " is-on" : ""}`}
                    onClick={() => {
                      props.setExercice(annee);
                      props.setPrescriptionConfirmee(false);
                    }}
                  >
                    {annee}
                    <small>N-{delta}</small>
                  </button>
                );
              })}
              <input
                type="number"
                className="field-input exercice-libre"
                aria-label="Exercice — saisie libre"
                value={exercice}
                onChange={(e) => {
                  props.setExercice(Number(e.target.value));
                  props.setPrescriptionConfirmee(false);
                }}
              />
            </div>
            {exerciceFutur && (
              <p className="status err" role="alert">
                L&apos;exercice {exercice} n&apos;est pas encore clos — une
                revue fiscale porte sur un exercice achevé.
              </p>
            )}
            {exercicePrescrit && (
              <label className="check check-card exercice-prescrit">
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
                    Confirmez que la revue est volontaire (contentieux,
                    contrôle en cours…).
                  </small>
                </span>
              </label>
            )}
          </div>

          <div className="field-grid field-grid-2 cadrage-profil">
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
              hint="Prérempli depuis la fiche client — modifiable."
            />
            {props.contribForme === "pm" ? (
              <SelectField
                id="cadrage-forme-jur"
                label="Forme juridique"
                value={forme}
                onChange={(e) => props.setForme(e.target.value)}
                options={FORMES_JURIDIQUES_PM}
                required
                tip={PROCESS_TIPS.formeJuridique}
                hint="Prérempli depuis la fiche client — modifiable."
              />
            ) : (
              <div className="field">
                <p className="field-hint cadrage-forme-pp">
                  Personne physique — forme juridique EI (entreprise
                  individuelle).
                </p>
              </div>
            )}
          </div>

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

        {/* -------------------------------------------- Bloc 3 — Comment */}
        <section
          className={`cadrage-bloc${quiOk && quoiOk ? "" : " is-locked"}`}
          aria-labelledby="cadrage-comment"
          aria-disabled={!(quiOk && quoiOk)}
        >
          <header className="cadrage-bloc-head">
            <span className="cadrage-bloc-n" aria-hidden="true">
              3
            </span>
            <div>
              <h3 id="cadrage-comment" className="label-with-tip">
                Comment — le périmètre
                <InfoTip
                  label={PROCESS_TIPS.perimetreImpots}
                  ariaLabel="Aide : périmètre impôts"
                />
              </h3>
              <p>
                Par défaut, revue complète : tous les impôts du référentiel.
                Activez des chips pour restreindre le périmètre.
              </p>
            </div>
          </header>

          <div
            className="impot-chips"
            role="group"
            aria-label="Codes impôts du périmètre"
          >
            {CODES_IMPOT_PIVOT.map((code) => {
              const checked = perimetreImpots.includes(code);
              return (
                <Tooltip key={code} label={tipImpot(code)} side="bottom">
                  <label className={`impot-chip${checked ? " is-on" : ""}`}>
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
          <p className="field-hint">
            {perimetreImpots.length > 0 ? (
              <>
                Revue <strong>partielle</strong> —{" "}
                {perimetreImpots.join(", ")}.
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

          <details className="cadrage-affiner">
            <summary>Affiner le cadrage (optionnel)</summary>
            <div className="cadrage-affiner-corps">
              <div className="field-grid field-grid-2">
                <Field
                  id="cadrage-seuil"
                  label="Seuil de signification (FCFA)"
                  type="number"
                  min={0}
                  step="1"
                  value={seuilSignification}
                  onChange={(e) =>
                    props.setSeuilSignification(e.target.value)
                  }
                  tip={PROCESS_TIPS.seuilSignification}
                  hint="Matérialité cabinet — optionnel."
                />
                <Field
                  id="cadrage-type-entite"
                  label="Type d'entité"
                  value={props.typeEntite}
                  onChange={(e) => props.setTypeEntite(e.target.value)}
                  tip={PROCESS_TIPS.typeEntite}
                  hint="Optionnel — précise le profil pour le moteur."
                />
              </div>
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
              <div className="field">
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
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
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
                        Retirer
                      </button>
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
              <div className="field">
                <label
                  className="field-label-static"
                  htmlFor="cadrage-exclusions"
                >
                  Exclusions déclarées
                </label>
                <textarea
                  id="cadrage-exclusions"
                  className="field-input field-textarea"
                  rows={2}
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

      {/* ------------------------------- Panneau latéral — lettre vivante */}
      <aside className="lettre-panel" aria-label="Lettre de mission — récapitulatif">
        <p className="lettre-kicker">Lettre de mission</p>
        <div className="lettre-corps">
          <p className={`lettre-ligne${props.contribNom.trim() ? " ok" : ""}`}>
            <span className="lettre-k">Client</span>
            {props.contribNom.trim() ? (
              <>
                {props.contribNom.trim()}
                {props.contribNcc.trim()
                  ? ` (NCC ${props.contribNcc.trim()})`
                  : ""}
                , {formeAffichee} au régime {regimeLabel.toLowerCase()}
                {props.contribCommune.trim()
                  ? `, ${props.contribCommune.trim()}`
                  : ""}
                .
              </>
            ) : (
              <em>à désigner…</em>
            )}
          </p>
          <p className={`lettre-ligne${!exerciceFutur ? " ok" : ""}`}>
            <span className="lettre-k">Exercice</span>
            {exerciceFutur ? (
              <em>exercice {exercice} non clos — à corriger…</em>
            ) : (
              <>
                Exercice {exercice}
                {exercicePrescrit
                  ? prescriptionConfirmee
                    ? " (prescrit — revue volontaire confirmée)"
                    : " (a priori prescrit — à confirmer)"
                  : ""}
                .
              </>
            )}
          </p>
          <p className={`lettre-ligne${engagement ? " ok" : ""}`}>
            <span className="lettre-k">Engagement</span>
            {engagement ? (
              <>
                {engagement.titre} — {engagement.desc}
              </>
            ) : (
              <em>à choisir…</em>
            )}
          </p>
          <p className="lettre-ligne ok">
            <span className="lettre-k">Périmètre</span>
            {perimetreImpots.length > 0
              ? `Revue partielle limitée à : ${perimetreImpots.join(", ")}.`
              : "Revue complète — tous les impôts du référentiel."}
          </p>
          {seuilAffiche && (
            <p className="lettre-ligne ok">
              <span className="lettre-k">Seuil</span>
              Seuil de signification : {seuilAffiche}.
            </p>
          )}
          {objectifsRemplis.length > 0 && (
            <p className="lettre-ligne ok">
              <span className="lettre-k">Objectifs</span>
              {objectifsRemplis.join(" · ")}
            </p>
          )}
          {exclusionsDeclarees.trim() && (
            <p className="lettre-ligne ok">
              <span className="lettre-k">Exclusions</span>
              {exclusionsDeclarees.trim()}
            </p>
          )}
          {props.crossBorder && (
            <p className="lettre-ligne ok">
              <span className="lettre-k">Cross-border</span>
              Contrôles des flux internationaux activés.
            </p>
          )}
        </div>

        {quotaBloque && (
          <p className="status err" role="alert">
            Quota missions atteint — la création est bloquée.
          </p>
        )}
        {missionStatus?.err && (
          <p className="status err" role="alert">
            {missionStatus.msg}
          </p>
        )}
        {missionStatus && !missionStatus.err && (
          <p className="status" role="status">
            {missionStatus.msg}
          </p>
        )}

        <button
          type="button"
          className="btn btn-primary lettre-creer"
          disabled={!pretACreer}
          onClick={props.onCreerMission}
        >
          {busy ? "Création…" : "Créer la mission"}
        </button>
        {manquants.length > 0 && (
          <p className="lettre-manque" role="status">
            Manque : {manquants.join(" · ")}.
          </p>
        )}
      </aside>
    </div>
  );
}
