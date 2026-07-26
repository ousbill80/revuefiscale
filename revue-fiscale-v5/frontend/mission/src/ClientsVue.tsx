import {
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type FormEvent,
  type SetStateAction,
} from "react";
import { Field, SelectField } from "./Field";
import {
  FORMES_JURIDIQUES_PM,
  FORMES_PERSONNE,
  MOIS_CLOTURE,
  REGIMES_FISCAUX,
  SECTEURS_ACTIVITE,
  avertissementFormatNcc,
  avertissementFormatRccm,
  composerActivite,
  completudeIdentite,
  decomposerActivite,
  formaterCreationTrace,
  identiteApiMinimale,
  libelleMoisCloture,
  type FormePersonne,
  type IdentiteLegale,
} from "./legalite";
import { PROCESS_TIPS } from "./processTips";
import {
  PiecesContribuablePanel,
  nouvelleSessionUpload,
} from "./PiecesContribuable";
import { RegistreRisquesVue } from "./RegistreRisques";
import {
  estMissionActive,
  libelleStatut,
  type MissionRow,
} from "./MissionsVue";
import { Tooltip } from "./Tooltip";

export type ClientRow = {
  id: number;
  denomination: string;
  ncc?: string | null;
  rccm?: string | null;
  forme?: string | null;
  dfe?: string | null;
  regime_fiscal?: string | null;
  forme_juridique?: string | null;
  siege_social?: string | null;
  commune?: string | null;
  centre_impots?: string | null;
  capital_social?: number | string | null;
  mois_cloture?: number | null;
  activite_principale?: string | null;
  date_immatriculation?: string | null;
  cree_le?: string | null;
  cree_par?: number | null;
  cree_par_email?: string | null;
};

type Synthese = "tous" | "pm" | "pp" | "incomplets";
type FiltreForme = "" | "pm" | "pp";
type FiltreCompletude = "" | "complet" | "incomplet";

type Props = {
  clients: ClientRow[];
  missions: MissionRow[];
  estLecteur: boolean;
  onOuvrirClient: (id: number) => void;
  onNouveauClient: () => void;
  onNouvelleMission: (client: ClientRow) => void;
};

function normaliserRecherche(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "");
}

export function formePersonne(forme: string | null | undefined): FormePersonne {
  return forme === "pp" ? "pp" : "pm";
}

function capitalVersSaisie(
  v: number | string | null | undefined,
): string {
  if (v === null || v === undefined || v === "") return "";
  return String(v);
}

export function identiteDepuisClient(c: ClientRow): IdentiteLegale {
  const forme = formePersonne(c.forme);
  return {
    denomination: c.denomination ?? "",
    ncc: c.ncc ?? "",
    forme,
    rccm: c.rccm ?? "",
    dfe: c.dfe ?? "",
    // Mêmes défauts que l'état d'édition de la fiche (App.tsx setClientEdit /
    // etatInitialClientEdit) : régime "reel", forme juridique SA/EI, clôture 12.
    // Indispensable pour que completudeIdentite donne le même score N/11 en
    // liste et en fiche pour un même client.
    regime_fiscal: c.regime_fiscal || "reel",
    forme_juridique: c.forme_juridique || (forme === "pp" ? "EI" : "SA"),
    siege_social: c.siege_social ?? "",
    commune: c.commune ?? "",
    centre_impots: c.centre_impots ?? "",
    capital_social: capitalVersSaisie(c.capital_social),
    mois_cloture:
      c.mois_cloture != null && c.mois_cloture !== undefined
        ? String(c.mois_cloture)
        : "12",
    activite_principale: c.activite_principale ?? "",
    date_immatriculation: c.date_immatriculation
      ? String(c.date_immatriculation).slice(0, 10)
      : "",
  };
}

function libelleRegime(value: string | null | undefined): string {
  if (!value) return "—";
  return REGIMES_FISCAUX.find((r) => r.value === value)?.label ?? value;
}

function libelleFormeCourte(forme: FormePersonne): string {
  return forme === "pp" ? "PP" : "PM";
}

function formaterDateCourte(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function etatInitialClientEdit(
  forme: FormePersonne = "pm",
): ClientEditState {
  return {
    denomination: "",
    ncc: "",
    rccm: "",
    forme,
    dfe: "",
    regime_fiscal: "reel",
    forme_juridique: forme === "pp" ? "EI" : "SA",
    siege_social: "",
    commune: "",
    centre_impots: "",
    capital_social: "",
    mois_cloture: "12",
    activite_principale: "",
    date_immatriculation: "",
  };
}

type ClientEnrichi = ClientRow & {
  formeNorm: FormePersonne;
  completude: ReturnType<typeof completudeIdentite>;
  nbMissions: number;
};

export function ClientsVue({
  clients,
  missions,
  estLecteur,
  onOuvrirClient,
  onNouveauClient,
  onNouvelleMission,
}: Props) {
  const [recherche, setRecherche] = useState("");
  const [filtreForme, setFiltreForme] = useState<FiltreForme>("");
  const [filtreCompletude, setFiltreCompletude] =
    useState<FiltreCompletude>("");
  const [synthese, setSynthese] = useState<Synthese>("tous");

  const countsParClient = useMemo(() => {
    const map = new Map<number, number>();
    for (const m of missions) {
      map.set(m.contribuable_id, (map.get(m.contribuable_id) ?? 0) + 1);
    }
    return map;
  }, [missions]);

  const enrichis = useMemo<ClientEnrichi[]>(() => {
    return clients.map((c) => {
      const formeNorm = formePersonne(c.forme);
      const completude = completudeIdentite(identiteDepuisClient(c));
      return {
        ...c,
        formeNorm,
        completude,
        nbMissions: countsParClient.get(c.id) ?? 0,
      };
    });
  }, [clients, countsParClient]);

  const stats = useMemo(() => {
    let pm = 0;
    let pp = 0;
    let incomplets = 0;
    for (const c of enrichis) {
      if (c.formeNorm === "pp") pp += 1;
      else pm += 1;
      if (!c.completude.complet) incomplets += 1;
    }
    return { tous: enrichis.length, pm, pp, incomplets };
  }, [enrichis]);

  const liste = useMemo(() => {
    const q = normaliserRecherche(recherche);
    return enrichis
      .filter((c) => {
        if (synthese === "pm" && c.formeNorm !== "pm") return false;
        if (synthese === "pp" && c.formeNorm !== "pp") return false;
        if (synthese === "incomplets" && c.completude.complet) return false;
        if (filtreForme && c.formeNorm !== filtreForme) return false;
        if (filtreCompletude === "complet" && !c.completude.complet) return false;
        if (filtreCompletude === "incomplet" && c.completude.complet) return false;
        if (!q) return true;
        const hay = [
          c.denomination,
          c.ncc,
          c.rccm,
          c.dfe,
          c.forme_juridique,
          c.siege_social,
          c.commune,
          c.centre_impots,
          c.activite_principale,
          c.regime_fiscal,
        ]
          .map((x) => normaliserRecherche(String(x ?? "")))
          .join(" ");
        return hay.includes(q);
      })
      .sort((a, b) =>
        a.denomination.localeCompare(b.denomination, "fr", {
          sensitivity: "base",
        }),
      );
  }, [enrichis, recherche, synthese, filtreForme, filtreCompletude]);

  const filtresActifs =
    Boolean(recherche.trim()) ||
    Boolean(filtreForme) ||
    Boolean(filtreCompletude) ||
    synthese !== "tous";

  function reinitialiser() {
    setRecherche("");
    setFiltreForme("");
    setFiltreCompletude("");
    setSynthese("tous");
  }

  function choisirSynthese(s: Synthese) {
    setSynthese(s);
    if (s === "pm" || s === "pp") {
      setFiltreForme("");
    }
    if (s === "incomplets") {
      setFiltreCompletude("");
    }
  }

  const emptyTitle = clients.length
    ? "Aucun contribuable pour ces critères"
    : "Aucun client dans le portefeuille";
  const emptyBody = clients.length
    ? "Élargissez la recherche, changez les filtres ou réinitialisez la vue."
    : estLecteur
      ? "Les contribuables du cabinet apparaîtront ici dès qu’ils seront créés."
      : "Créez un premier contribuable pour démarrer une mission de revue fiscale.";

  return (
    <div className="page clients-vue">
      <header className="page-head clients-head">
        <div>
          <p className="page-eyebrow">Portefeuille</p>
          <h2 className="section-title">Clients</h2>
          <p className="section-sub">
            CRM cloisonné du cabinet — identité légale, complétude et missions
            liées.
          </p>
        </div>
        {!estLecteur && (
          <div className="page-actions">
            <Tooltip label="Ouvrir le formulaire d’identité légale (PM / PP).">
              <button
                type="button"
                className="btn btn-primary"
                onClick={onNouveauClient}
              >
                Nouveau client
              </button>
            </Tooltip>
          </div>
        )}
      </header>

      <div
        className="clients-synth"
        role="group"
        aria-label="Synthèse du portefeuille"
      >
        {(
          [
            {
              id: "tous" as const,
              label: "Total",
              value: stats.tous,
              tip: "Tous les contribuables du cabinet.",
            },
            {
              id: "pm" as const,
              label: "Personnes morales",
              value: stats.pm,
              tip: "Entreprises et sociétés (PM).",
            },
            {
              id: "pp" as const,
              label: "Personnes physiques",
              value: stats.pp,
              tip: "Entrepreneurs individuels / particuliers (PP).",
            },
            {
              id: "incomplets" as const,
              label: "Fiches incomplètes",
              value: stats.incomplets,
              tip: "Identité légale incomplète (NCC, RCCM, siège, régime…).",
            },
          ] as const
        ).map((item) => (
          <Tooltip key={item.id} label={item.tip}>
            <button
              type="button"
              className={`clients-synth-btn${synthese === item.id ? " is-active" : ""}${item.id === "incomplets" && item.value > 0 ? " is-warn" : ""}`}
              aria-pressed={synthese === item.id}
              onClick={() => choisirSynthese(item.id)}
            >
              <span className="clients-synth-value">{item.value}</span>
              <span className="clients-synth-label">{item.label}</span>
            </button>
          </Tooltip>
        ))}
      </div>

      <div className="clients-toolbar">
        <div className="clients-toolbar-search">
          <label htmlFor="clients-q">Recherche</label>
          <input
            id="clients-q"
            type="search"
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
            placeholder="NCC, dénomination, RCCM, commune…"
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        <div>
          <label htmlFor="clients-forme">Type</label>
          <select
            id="clients-forme"
            value={filtreForme}
            onChange={(e) => {
              setFiltreForme(e.target.value as FiltreForme);
              setSynthese("tous");
            }}
          >
            <option value="">PM et PP</option>
            <option value="pm">Personne morale</option>
            <option value="pp">Personne physique</option>
          </select>
        </div>
        <div>
          <label htmlFor="clients-completude">Identité</label>
          <select
            id="clients-completude"
            value={filtreCompletude}
            onChange={(e) => {
              setFiltreCompletude(e.target.value as FiltreCompletude);
              setSynthese("tous");
            }}
          >
            <option value="">Toutes les fiches</option>
            <option value="complet">Complètes</option>
            <option value="incomplet">Incomplètes</option>
          </select>
        </div>
        <div className="clients-toolbar-actions">
          <Tooltip label="Effacer recherche, synthèse et filtres.">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={reinitialiser}
              disabled={!filtresActifs}
            >
              Réinitialiser
            </button>
          </Tooltip>
        </div>
      </div>

      <div className="panel dense clients-panel">
        <div className="clients-panel-head">
          <p className="clients-count">
            {liste.length} contribuable{liste.length !== 1 ? "s" : ""}
            {filtresActifs ? " · filtrés" : ""}
          </p>
          <p className="clients-panel-hint">
            Ouvrir la fiche ou lancer une mission préremplie.
          </p>
        </div>

        {liste.length > 0 ? (
          <div
            className="clients-table"
            role="table"
            aria-label="Liste des contribuables"
          >
            <div className="clients-table-head" role="row">
              <span role="columnheader">Contribuable</span>
              <span role="columnheader">NCC</span>
              <span role="columnheader">Type / forme</span>
              <span role="columnheader">Identifiants</span>
              <span role="columnheader">Régime</span>
              <span role="columnheader">Missions</span>
              <span role="columnheader">Identité</span>
              <span role="columnheader" className="clients-col-action">
                Actions
              </span>
            </div>
            <ul className="clients-table-body">
              {liste.map((c) => {
                const tipMiss = c.completude.complet
                  ? "Identité légale complète"
                  : `Manque : ${c.completude.manquants.join(", ")}`;
                return (
                  <li key={c.id} role="row" className="clients-row-wrap">
                    <div className="clients-row">
                      <button
                        type="button"
                        className="clients-row-main"
                        onClick={() => onOuvrirClient(c.id)}
                      >
                        <span className="clients-cell-nom" role="cell">
                          <span className="clients-nom">{c.denomination}</span>
                          <span className="clients-meta">
                            {[
                              [c.commune, c.siege_social]
                                .map((x) => x?.trim())
                                .filter(Boolean)
                                .join(" · ") || `Fiche #${c.id}`,
                              (() => {
                                const quand = formaterCreationTrace(c.cree_le);
                                if (!quand && !c.cree_par_email) return null;
                                const qui = c.cree_par_email?.trim();
                                return [
                                  "Créé",
                                  qui ? `par ${qui}` : null,
                                  quand,
                                ]
                                  .filter(Boolean)
                                  .join(" ");
                              })(),
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                        </span>
                        <span className="clients-cell-ncc" role="cell">
                          {c.ncc?.trim() || "—"}
                        </span>
                        <span className="clients-cell-type" role="cell">
                          <span
                            className={`clients-badge clients-badge-${c.formeNorm}`}
                          >
                            {libelleFormeCourte(c.formeNorm)}
                          </span>
                          <span className="clients-forme-j">
                            {c.formeNorm === "pm"
                              ? c.forme_juridique?.trim() || "—"
                              : "EI"}
                          </span>
                        </span>
                        <span className="clients-cell-ids" role="cell">
                          {c.formeNorm === "pm" ? (
                            <>
                              <span>
                                <em>RCCM</em> {c.rccm?.trim() || "—"}
                              </span>
                              {c.centre_impots?.trim() ? (
                                <span>
                                  <em>Centre</em> {c.centre_impots.trim()}
                                </span>
                              ) : null}
                            </>
                          ) : (
                            <span className="clients-ids-pp">Fiche PP</span>
                          )}
                        </span>
                        <span className="clients-cell-regime" role="cell">
                          {libelleRegime(c.regime_fiscal)}
                        </span>
                        <span className="clients-cell-missions" role="cell">
                          <strong>{c.nbMissions}</strong>
                          <span>
                            mission{c.nbMissions !== 1 ? "s" : ""}
                          </span>
                        </span>
                        <span className="clients-cell-jauge" role="cell">
                          <Tooltip label={tipMiss} side="bottom">
                            <span
                              className={`clients-jauge${c.completude.complet ? " is-ok" : " is-warn"}`}
                              aria-label={`${c.completude.pct}% — ${tipMiss}`}
                            >
                              <span className="clients-jauge-meta">
                                {c.completude.ok}/{c.completude.total}
                              </span>
                              <span
                                className="clients-jauge-track"
                                aria-hidden="true"
                              >
                                <i style={{ width: `${c.completude.pct}%` }} />
                              </span>
                            </span>
                          </Tooltip>
                        </span>
                      </button>
                      <span className="clients-cell-action" role="cell">
                        <Tooltip label={`Ouvrir la fiche de ${c.denomination}`}>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            onClick={() => onOuvrirClient(c.id)}
                          >
                            Fiche
                          </button>
                        </Tooltip>
                        {!estLecteur && (
                          <Tooltip label="Nouvelle mission préremplie avec cette identité.">
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              onClick={() => onNouvelleMission(c)}
                            >
                              Mission
                            </button>
                          </Tooltip>
                        )}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : (
          <div className="clients-empty">
            <p className="clients-empty-title">{emptyTitle}</p>
            <p className="clients-empty-body">{emptyBody}</p>
            <div className="clients-empty-actions">
              {filtresActifs && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={reinitialiser}
                >
                  Réinitialiser les filtres
                </button>
              )}
              {!estLecteur && !clients.length && (
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={onNouveauClient}
                >
                  Nouveau client
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export type ClientEditState = {
  denomination: string;
  ncc: string;
  rccm: string;
  forme: FormePersonne;
  dfe: string;
  regime_fiscal: string;
  forme_juridique: string;
  siege_social: string;
  commune: string;
  centre_impots: string;
  capital_social: string;
  mois_cloture: string;
  activite_principale: string;
  date_immatriculation: string;
};

/** Payload API create/patch depuis l’état formulaire. */
export function payloadDepuisEdit(edit: ClientEditState): Record<
  string,
  string | number | null
> {
  const capitalRaw = edit.capital_social.trim().replace(/\s/g, "").replace(",", ".");
  let capital_social: number | null = null;
  if (capitalRaw) {
    const n = Number(capitalRaw);
    capital_social = Number.isFinite(n) ? n : null;
  }
  const mois = Number(edit.mois_cloture);
  return {
    denomination: edit.denomination.trim(),
    ncc: edit.ncc.trim() || null,
    rccm: edit.forme === "pm" ? edit.rccm.trim() || null : null,
    forme: edit.forme,
    dfe: edit.forme === "pm" ? edit.dfe.trim() || null : null,
    regime_fiscal: edit.regime_fiscal || null,
    forme_juridique:
      edit.forme === "pp" ? "EI" : edit.forme_juridique.trim() || null,
    siege_social: edit.siege_social.trim() || null,
    commune: edit.commune.trim() || null,
    centre_impots: edit.centre_impots.trim() || null,
    capital_social: edit.forme === "pm" ? capital_social : null,
    mois_cloture: Number.isFinite(mois) && mois >= 1 && mois <= 12 ? mois : 12,
    activite_principale: edit.activite_principale.trim() || null,
    date_immatriculation: edit.date_immatriculation.trim() || null,
  };
}

function identiteDepuisEdit(edit: ClientEditState): IdentiteLegale {
  return {
    denomination: edit.denomination,
    ncc: edit.ncc,
    forme: edit.forme,
    rccm: edit.rccm,
    dfe: edit.dfe,
    regime_fiscal: edit.regime_fiscal,
    forme_juridique: edit.forme_juridique,
    siege_social: edit.siege_social,
    commune: edit.commune,
    centre_impots: edit.centre_impots,
    capital_social: edit.capital_social,
    mois_cloture: edit.mois_cloture,
    activite_principale: edit.activite_principale,
    date_immatriculation: edit.date_immatriculation,
  };
}

type ClientDetail = ClientRow & {
  missions: MissionRow[];
  nb_missions: number;
};

type IdentiteFormProps = {
  prefix: string;
  edit: ClientEditState;
  setEdit: Dispatch<SetStateAction<ClientEditState>>;
  disabled?: boolean;
  /** Clés identité encore vides — bordure rouge + message. */
  champsManquants?: ReadonlySet<string> | ReadonlyArray<string>;
  /**
   * Mode création : le rouge « À compléter » n'apparaît qu'après blur du
   * champ (touched) ou tentative de soumission — formulaire vierge neutre.
   * En édition d'une fiche existante incomplète, le rouge reste immédiat.
   */
  creation?: boolean;
  /** Tentative de soumission — force l'affichage des manquants en création. */
  forcerManquants?: boolean;
  /** Portefeuille chargé — détection doublon NCC (avertissement doux). */
  clientsExistants?: ClientRow[];
};

function estChampManquant(
  cle: string,
  champs?: ReadonlySet<string> | ReadonlyArray<string>,
): boolean {
  if (!champs) return false;
  return "has" in champs ? champs.has(cle) : champs.includes(cle);
}

function IdentiteLegaleForm({
  prefix,
  edit,
  setEdit,
  disabled = false,
  champsManquants,
  creation = false,
  forcerManquants = false,
  clientsExistants,
}: IdentiteFormProps) {
  const { secteur, precision } = decomposerActivite(edit.activite_principale);
  const [touches, setTouches] = useState<ReadonlySet<string>>(
    () => new Set<string>(),
  );
  const toucher = (cle: string) =>
    setTouches((prev) =>
      prev.has(cle) ? prev : new Set(prev).add(cle),
    );
  const miss = (cle: string) =>
    estChampManquant(cle, champsManquants) &&
    (!creation || forcerManquants || touches.has(cle));

  // Validations douces au blur — non bloquantes, le backend reste juge.
  const [nccWarn, setNccWarn] = useState<string | null>(null);
  const [rccmWarn, setRccmWarn] = useState<string | null>(null);

  function verifierNcc() {
    toucher("ncc");
    const avert: string[] = [];
    const format = avertissementFormatNcc(edit.ncc);
    if (format) avert.push(format);
    const saisi = edit.ncc.trim().toUpperCase();
    if (creation && saisi && clientsExistants?.length) {
      const doublon = clientsExistants.find(
        (c) => (c.ncc ?? "").trim().toUpperCase() === saisi,
      );
      if (doublon) {
        avert.push(
          `Un client avec ce NCC existe déjà : ${doublon.denomination}.`,
        );
      }
    }
    setNccWarn(avert.length ? avert.join(" ") : null);
  }

  function majActivite(nextSecteur: string, nextPrecision: string) {
    setEdit((s) => ({
      ...s,
      activite_principale: composerActivite(nextSecteur, nextPrecision),
    }));
  }

  return (
    <>
      <div
        className="persona-toggle"
        role="group"
        aria-label="Type de contribuable"
      >
        {FORMES_PERSONNE.map((p) => (
          <Tooltip key={p.value} label={p.hint} side="bottom">
            <button
              type="button"
              className={`persona-btn${edit.forme === p.value ? " active" : ""}`}
              disabled={disabled}
              onClick={() =>
                setEdit((s) => ({
                  ...s,
                  forme: p.value,
                  forme_juridique:
                    p.value === "pp"
                      ? "EI"
                      : s.forme_juridique === "EI"
                        ? "SA"
                        : s.forme_juridique,
                }))
              }
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
          id={`${prefix}-denom`}
          label={
            edit.forme === "pm"
              ? "Dénomination / raison sociale"
              : "Nom du contribuable"
          }
          value={edit.denomination}
          disabled={disabled}
          onChange={(e) =>
            setEdit((s) => ({ ...s, denomination: e.target.value }))
          }
          onBlur={() => toucher("denomination")}
          required
          manquant={miss("denomination")}
          autoComplete="organization"
          hint={
            edit.forme === "pm"
              ? "Raison sociale telle qu’au RCCM."
              : "Nom et prénoms tels qu’à la DGI."
          }
        />
        <Field
          id={`${prefix}-ncc`}
          label="NCC"
          value={edit.ncc}
          disabled={disabled}
          onChange={(e) => setEdit((s) => ({ ...s, ncc: e.target.value }))}
          onBlur={verifierNcc}
          required
          manquant={miss("ncc")}
          avertissement={nccWarn}
          autoComplete="off"
          spellCheck={false}
          tip={PROCESS_TIPS.ncc}
          hint="N° de compte contribuable — figurant sur la DFE."
        />
      </div>

      {edit.forme === "pm" ? (
        <div className="legal-block">
          <div className="legal-block-head">
            <p className="picker-kicker">Identité d’entreprise</p>
            <p className="picker-hint">
              Pièces légales — le NCC (sur la DFE) et le RCCM suffisent.
            </p>
          </div>
          <div className="field-grid field-grid-2">
            <Field
              id={`${prefix}-rccm`}
              label="RCCM"
              value={edit.rccm}
              disabled={disabled}
              onChange={(e) =>
                setEdit((s) => ({ ...s, rccm: e.target.value }))
              }
              onBlur={() => {
                toucher("rccm");
                setRccmWarn(avertissementFormatRccm(edit.rccm));
              }}
              required
              manquant={miss("rccm")}
              avertissement={rccmWarn}
              spellCheck={false}
              hint="Registre de commerce et du crédit mobilier."
            />
            <SelectField
              id={`${prefix}-fj`}
              label="Forme juridique"
              value={edit.forme_juridique}
              disabled={disabled}
              onChange={(e) =>
                setEdit((s) => ({
                  ...s,
                  forme_juridique: e.target.value,
                }))
              }
              options={FORMES_JURIDIQUES_PM}
              onBlur={() => toucher("forme_juridique")}
              required
              manquant={miss("forme_juridique")}
              hint="Statut juridique — OHADA / pratique CI."
            />
            <SelectField
              id={`${prefix}-regime`}
              label="Régime fiscal"
              value={edit.regime_fiscal}
              disabled={disabled}
              onChange={(e) =>
                setEdit((s) => ({
                  ...s,
                  regime_fiscal: e.target.value,
                }))
              }
              options={REGIMES_FISCAUX.map((r) => ({
                value: r.value,
                label: r.label,
              }))}
              onBlur={() => toucher("regime_fiscal")}
              required
              manquant={miss("regime_fiscal")}
              hint="Régime déclaré — recopié dans le profil de mission."
            />
            <Field
              id={`${prefix}-capital`}
              label="Capital social"
              type="number"
              inputMode="decimal"
              min={0}
              step="1"
              value={edit.capital_social}
              disabled={disabled}
              onChange={(e) =>
                setEdit((s) => ({
                  ...s,
                  capital_social: e.target.value,
                }))
              }
              onBlur={() => toucher("capital_social")}
              required
              manquant={miss("capital_social")}
              trailing="XOF"
              hint="Capital social déclaré (statuts / RCCM) — cadrage revue, pas un seuil moteur."
            />
            <SelectField
              id={`${prefix}-cloture`}
              label="Clôture d’exercice"
              value={edit.mois_cloture || "12"}
              disabled={disabled}
              onChange={(e) =>
                setEdit((s) => ({
                  ...s,
                  mois_cloture: e.target.value,
                }))
              }
              options={MOIS_CLOTURE}
              onBlur={() => toucher("mois_cloture")}
              required
              manquant={miss("mois_cloture")}
              hint="Mois de clôture — exercice décalé vs année civile."
            />
            <SelectField
              id={`${prefix}-secteur`}
              label="Secteur d’activité"
              value={secteur}
              disabled={disabled}
              onChange={(e) => majActivite(e.target.value, precision)}
              options={SECTEURS_ACTIVITE}
              onBlur={() => toucher("activite_principale")}
              required
              manquant={miss("activite_principale")}
              hint="Cadrage revue — recopié dans le profil de mission."
            />
            <Field
              id={`${prefix}-activite-prec`}
              label="Précision d’activité"
              value={precision}
              disabled={disabled}
              onChange={(e) => majActivite(secteur, e.target.value)}
              hint="Libellé libre (ex. grossiste agro) — pas de NAF."
            />
            <Field
              id={`${prefix}-immat`}
              label="Date d’immatriculation"
              type="date"
              value={edit.date_immatriculation}
              disabled={disabled}
              onChange={(e) =>
                setEdit((s) => ({
                  ...s,
                  date_immatriculation: e.target.value,
                }))
              }
              hint="Date d’immatriculation DGI (identité)."
            />
          </div>
        </div>
      ) : (
        <div className="legal-block">
          <div className="legal-block-head">
            <p className="picker-kicker">Fiche personne physique</p>
            <p className="picker-hint">
              Identité allégée — RCCM non exigé pour une PP.
            </p>
          </div>
          <div className="field-grid field-grid-2">
            <SelectField
              id={`${prefix}-regime`}
              label="Régime fiscal"
              value={edit.regime_fiscal}
              disabled={disabled}
              onChange={(e) =>
                setEdit((s) => ({
                  ...s,
                  regime_fiscal: e.target.value,
                }))
              }
              options={REGIMES_FISCAUX.map((r) => ({
                value: r.value,
                label: r.label,
              }))}
              onBlur={() => toucher("regime_fiscal")}
              required
              manquant={miss("regime_fiscal")}
              hint="Régime déclaré — recopié dans le profil de mission."
            />
            <SelectField
              id={`${prefix}-cloture`}
              label="Clôture d’exercice"
              value={edit.mois_cloture || "12"}
              disabled={disabled}
              onChange={(e) =>
                setEdit((s) => ({
                  ...s,
                  mois_cloture: e.target.value,
                }))
              }
              options={MOIS_CLOTURE}
              onBlur={() => toucher("mois_cloture")}
              required
              manquant={miss("mois_cloture")}
              hint="Mois de clôture — exercice décalé vs année civile."
            />
            <SelectField
              id={`${prefix}-secteur`}
              label="Secteur d’activité"
              value={secteur}
              disabled={disabled}
              onChange={(e) => majActivite(e.target.value, precision)}
              options={SECTEURS_ACTIVITE}
              onBlur={() => toucher("activite_principale")}
              required
              manquant={miss("activite_principale")}
              hint="Cadrage revue — défaut profil mission."
            />
            <Field
              id={`${prefix}-activite-prec`}
              label="Précision d’activité"
              value={precision}
              disabled={disabled}
              onChange={(e) => majActivite(secteur, e.target.value)}
              hint="Libellé libre — pas de NAF."
            />
            <Field
              id={`${prefix}-immat`}
              label="Date d’immatriculation"
              type="date"
              value={edit.date_immatriculation}
              disabled={disabled}
              onChange={(e) =>
                setEdit((s) => ({
                  ...s,
                  date_immatriculation: e.target.value,
                }))
              }
              hint="Date d’immatriculation DGI (optionnel)."
            />
          </div>
        </div>
      )}

      <div className="legal-block">
        <div className="legal-block-head">
          <p className="picker-kicker">Siège effectif / domicile fiscal</p>
          <p className="picker-hint">
            Lieu réel d’exploitation — détermine le centre des impôts de
            rattachement. Justificatifs usuels : bail, facture CIE ou SODECI.
          </p>
        </div>
        <div className="field-grid field-grid-2">
          <Field
            id={`${prefix}-commune`}
            label="Ville / commune"
            value={edit.commune}
            disabled={disabled}
            onChange={(e) =>
              setEdit((s) => ({ ...s, commune: e.target.value }))
            }
            onBlur={() => toucher("commune")}
            required
            manquant={miss("commune")}
            tip={PROCESS_TIPS.siegeEffectif}
            hint="Commune du siège effectif (domicile fiscal)."
          />
          <Field
            id={`${prefix}-siege`}
            label="Adresse / quartier"
            value={edit.siege_social}
            disabled={disabled}
            onChange={(e) =>
              setEdit((s) => ({
                ...s,
                siege_social: e.target.value,
              }))
            }
            onBlur={() => toucher("siege_social")}
            required={edit.forme === "pm"}
            manquant={miss("siege_social")}
            hint="Quartier, voie, immeuble — siège effectif, pas un libellé vague."
          />
          <Field
            id={`${prefix}-centre`}
            label="Centre des impôts"
            value={edit.centre_impots}
            disabled={disabled}
            onChange={(e) =>
              setEdit((s) => ({
                ...s,
                centre_impots: e.target.value,
              }))
            }
            onBlur={() => toucher("centre_impots")}
            required
            manquant={miss("centre_impots")}
            tip={PROCESS_TIPS.centreImpots}
            hint="Figurant sur la DFE ou l’avis d’imposition (ex. CDI, CIME, DGE)."
          />
        </div>
      </div>
    </>
  );
}

function CompletudeBar({ edit }: { edit: ClientEditState }) {
  const completude = useMemo(
    () => completudeIdentite(identiteDepuisEdit(edit)),
    [edit],
  );

  return (
    <div
      className={`completude-bar${completude.complet ? " ok" : " is-incomplet"}`}
      role="status"
    >
      <div className="completude-meta">
        <span>
          Identité légale {completude.ok}/{completude.total}
        </span>
        <strong>{completude.pct}%</strong>
      </div>
      <div className="completude-track" aria-hidden="true">
        <i style={{ width: `${completude.pct}%` }} />
      </div>
      {!completude.complet && (
        <p className="completude-miss clients-manquants-liste">
          Manque :{" "}
          {completude.manquants.map((lib) => (
            <span key={lib} className="clients-manquant-pill">
              {lib}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}

type CreationProps = {
  jeton: string;
  busy: boolean;
  /** Portefeuille chargé — détection doublon NCC (avertissement doux). */
  clients?: ClientRow[];
  onRetour: () => void;
  onCreer: (
    payload: ClientEditState,
    sessionUpload: string,
  ) => Promise<void>;
  onCreerPuisMission: (
    payload: ClientEditState,
    sessionUpload: string,
  ) => Promise<void>;
};

export function ClientCreationVue({
  jeton,
  busy,
  clients,
  onRetour,
  onCreer,
  onCreerPuisMission,
}: CreationProps) {
  const [edit, setEdit] = useState<ClientEditState>(() =>
    etatInitialClientEdit("pm"),
  );
  const [sessionUpload] = useState(() => nouvelleSessionUpload());
  const [erreurLocale, setErreurLocale] = useState<string | null>(null);
  const [soumissionTentee, setSoumissionTentee] = useState(false);

  const completude = useMemo(
    () => completudeIdentite(identiteDepuisEdit(edit)),
    [edit],
  );
  const apiMin = useMemo(
    () => identiteApiMinimale(identiteDepuisEdit(edit)),
    [edit],
  );

  async function soumettre(
    e: FormEvent,
    suite: "fiche" | "mission",
  ) {
    e.preventDefault();
    setErreurLocale(null);
    if (!apiMin.ok) {
      setSoumissionTentee(true);
      setErreurLocale(
        `Identité minimale incomplète : ${apiMin.manquants.join(", ")}.`,
      );
      return;
    }
    if (suite === "mission") await onCreerPuisMission(edit, sessionUpload);
    else await onCreer(edit, sessionUpload);
  }

  return (
    <div className="page clients-fiche clients-creation">
      <header className="page-head clients-head">
        <div>
          <p className="page-eyebrow">Portefeuille · Nouveau</p>
          <h2 className="section-title">Créer un client</h2>
          <p className="section-sub">
            Pièces optionnelles pour préremplir, ou saisie manuelle. Les champs
            absents des pièces pourront être complétés après enregistrement.
          </p>
        </div>
        <div className="page-actions">
          <Tooltip label="Retour au portefeuille clients.">
            <button type="button" className="btn btn-ghost" onClick={onRetour}>
              Annuler
            </button>
          </Tooltip>
        </div>
      </header>

      <CompletudeBar edit={edit} />

      <PiecesContribuablePanel
        jeton={jeton}
        sessionUpload={sessionUpload}
        disabled={busy}
        edit={edit}
        setEdit={setEdit}
      />

      <form
        className="panel dense clients-fiche-panel"
        onSubmit={(e) => void soumettre(e, "fiche")}
      >
        <IdentiteLegaleForm
          prefix="new"
          edit={edit}
          setEdit={setEdit}
          disabled={busy}
          champsManquants={completude.clesManquantes}
          creation
          forcerManquants={soumissionTentee}
          clientsExistants={clients}
        />

        {erreurLocale && (
          <p className="clients-creation-error" role="alert">
            {erreurLocale}
          </p>
        )}

        <div className="cta-row clients-fiche-cta clients-creation-cta">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            Enregistrer le client
          </button>
          <Tooltip label="Créer la fiche puis ouvrir le wizard mission prérempli.">
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy}
              onClick={(e) => void soumettre(e, "mission")}
            >
              Enregistrer et lancer une mission
            </button>
          </Tooltip>
          {!apiMin.ok && (
            <span className="cta-hint cta-hint-manquants">
              Manque : {apiMin.manquants.join(" · ")}
            </span>
          )}
        </div>
        {!completude.complet && apiMin.ok && (
          <p className="clients-creation-hint-manquants">
            Après enregistrement, les champs encore vides (
            {completude.manquants.join(" · ")}) seront signalés en rouge sur la
            fiche pour complément manuel.
          </p>
        )}
      </form>
    </div>
  );
}

type FicheProps = {
  jeton: string;
  clientDetail: ClientDetail;
  clientEdit: ClientEditState;
  setClientEdit: Dispatch<SetStateAction<ClientEditState>>;
  estLecteur: boolean;
  busy: boolean;
  onRetour: () => void;
  onSauver: () => void;
  onOuvrirMission: (id: number) => void;
  onNouvelleMission: () => void;
};

type FiltreMissionsFiche = "toutes" | "actives" | "cloturees";
type FicheTab = "overview" | "missions";

function hashFicheTab(clientId: number, tab: FicheTab): string {
  return tab === "missions"
    ? `#fiche-${clientId}-missions`
    : `#fiche-${clientId}-overview`;
}

function tabDepuisHash(clientId: number): FicheTab {
  const h = window.location.hash;
  if (h === `#fiche-${clientId}-missions`) return "missions";
  return "overview";
}

export function ClientFicheVue({
  jeton,
  clientDetail,
  clientEdit,
  setClientEdit,
  estLecteur,
  busy,
  onRetour,
  onSauver,
  onOuvrirMission,
  onNouvelleMission,
}: FicheProps) {
  const [filtreMissions, setFiltreMissions] =
    useState<FiltreMissionsFiche>("toutes");
  const [modeEdition, setModeEdition] = useState(false);
  const [ficheTab, setFicheTab] = useState<FicheTab>(() =>
    tabDepuisHash(clientDetail.id),
  );

  useEffect(() => {
    setFicheTab(tabDepuisHash(clientDetail.id));
  }, [clientDetail.id]);

  useEffect(() => {
    const attendu = hashFicheTab(clientDetail.id, ficheTab);
    if (window.location.hash !== attendu) {
      window.history.replaceState(null, "", attendu);
    }
  }, [clientDetail.id, ficheTab]);

  useEffect(() => {
    function onHashChange() {
      setFicheTab(tabDepuisHash(clientDetail.id));
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [clientDetail.id]);

  function changerFicheTab(tab: FicheTab) {
    setFicheTab(tab);
    window.history.replaceState(null, "", hashFicheTab(clientDetail.id, tab));
  }

  const completude = useMemo(
    () => completudeIdentite(identiteDepuisEdit(clientEdit)),
    [clientEdit],
  );
  const apiMin = useMemo(
    () => identiteApiMinimale(identiteDepuisEdit(clientEdit)),
    [clientEdit],
  );

  const formeNorm = formePersonne(clientDetail.forme);
  const formeLbl = libelleFormeCourte(formeNorm);

  const missions = clientDetail.missions || [];
  const missionsFiltrees = useMemo(() => {
    return missions.filter((m) => {
      if (filtreMissions === "actives") return estMissionActive(m.statut);
      if (filtreMissions === "cloturees") return !estMissionActive(m.statut);
      return true;
    });
  }, [missions, filtreMissions]);

  const nbActives = missions.filter((m) => estMissionActive(m.statut)).length;

  const peutEditer = !estLecteur && modeEdition;

  const traceQuand = formaterCreationTrace(clientDetail.cree_le);
  const traceQui =
    clientDetail.cree_par_email?.trim() ||
    (clientDetail.cree_par != null ? `utilisateur #${clientDetail.cree_par}` : null);

  function ouvrirEditionManquants() {
    changerFicheTab("overview");
    setModeEdition(true);
    window.requestAnimationFrame(() => {
      const premiere = completude.clesManquantes[0];
      if (!premiere) return;
      const idMap: Record<string, string> = {
        denomination: "edit-denom",
        ncc: "edit-ncc",
        rccm: "edit-rccm",
        forme_juridique: "edit-fj",
        regime_fiscal: "edit-regime",
        capital_social: "edit-capital",
        mois_cloture: "edit-cloture",
        activite_principale: "edit-secteur",
        commune: "edit-commune",
        siege_social: "edit-siege",
        centre_impots: "edit-centre",
      };
      const el = document.getElementById(idMap[premiere] ?? "");
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
      if (el && "focus" in el) (el as HTMLElement).focus();
    });
  }

  function valeurResumeManquante(cle: string, remplie: boolean): boolean {
    return !remplie && completude.clesManquantes.includes(cle as keyof IdentiteLegale);
  }

  return (
    <div className="page clients-fiche">
      <header className="page-head clients-head">
        <div>
          <p className="page-eyebrow">Portefeuille · Fiche #{clientDetail.id}</p>
          <h2 className="section-title">{clientDetail.denomination}</h2>
          <p className="section-sub">
            {formeLbl}
            {clientDetail.forme_juridique
              ? ` · ${clientDetail.forme_juridique}`
              : ""}
            {clientDetail.ncc ? ` · NCC ${clientDetail.ncc}` : ""}
            {" · "}
            {clientDetail.nb_missions} mission
            {clientDetail.nb_missions !== 1 ? "s" : ""}
            {" · "}
            identité {completude.ok}/{completude.total}
          </p>
          {(traceQui || traceQuand) && (
            <p className="clients-fiche-audit" aria-label="Traçabilité de création">
              Créé
              {traceQui ? ` par ${traceQui}` : ""}
              {traceQuand ? ` · ${traceQuand}` : ""}
              <span className="clients-fiche-audit-tz"> (heure Abidjan)</span>
            </p>
          )}
        </div>
        <div className="page-actions">
          <Tooltip label="Retour au portefeuille clients.">
            <button type="button" className="btn btn-ghost" onClick={onRetour}>
              Retour liste
            </button>
          </Tooltip>
          {!estLecteur && (
            <Tooltip label="Lancer une mission préremplie avec cette fiche.">
              <button
                type="button"
                className="btn btn-primary"
                onClick={onNouvelleMission}
              >
                Nouvelle mission
              </button>
            </Tooltip>
          )}
        </div>
      </header>

      <div
        className="tabs clients-fiche-tabs"
        role="tablist"
        aria-label="Sections de la fiche client"
      >
        <button
          type="button"
          id={`fiche-${clientDetail.id}-tab-overview`}
          className={`tab${ficheTab === "overview" ? " active" : ""}`}
          role="tab"
          aria-selected={ficheTab === "overview"}
          aria-controls={`fiche-${clientDetail.id}-panel-overview`}
          tabIndex={ficheTab === "overview" ? 0 : -1}
          onClick={() => changerFicheTab("overview")}
        >
          Vue d’ensemble
        </button>
        <button
          type="button"
          id={`fiche-${clientDetail.id}-tab-missions`}
          className={`tab${ficheTab === "missions" ? " active" : ""}`}
          role="tab"
          aria-selected={ficheTab === "missions"}
          aria-controls={`fiche-${clientDetail.id}-panel-missions`}
          tabIndex={ficheTab === "missions" ? 0 : -1}
          onClick={() => changerFicheTab("missions")}
        >
          Missions
          {clientDetail.nb_missions > 0 ? (
            <span className="clients-fiche-tab-count" aria-hidden="true">
              {clientDetail.nb_missions}
            </span>
          ) : null}
        </button>
      </div>

      {ficheTab === "overview" ? (
        <div
          className="clients-fiche-tab-panel"
          id={`fiche-${clientDetail.id}-panel-overview`}
          role="tabpanel"
          aria-labelledby={`fiche-${clientDetail.id}-tab-overview`}
        >
          <div
            className={`completude-bar clients-fiche-completude${completude.complet ? " ok" : " is-incomplet"}`}
          >
            <div className="completude-meta">
              <span>
                Identité légale {completude.ok}/{completude.total}
              </span>
              <strong>{completude.pct}%</strong>
            </div>
            <div className="completude-track" aria-hidden="true">
              <i style={{ width: `${completude.pct}%` }} />
            </div>
            {!completude.complet && (
              <div className="clients-manquants-bandeau">
                <p className="completude-miss clients-manquants-liste">
                  Manquant :{" "}
                  {completude.manquants.map((lib) => (
                    <span key={lib} className="clients-manquant-pill">
                      {lib}
                    </span>
                  ))}
                </p>
                {!estLecteur && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm clients-manquants-cta"
                    disabled={busy}
                    onClick={ouvrirEditionManquants}
                  >
                    Compléter les infos manquantes
                  </button>
                )}
              </div>
            )}
          </div>

          <dl className="clients-identite-resume" aria-label="Résumé d’identité">
            <div>
              <dt>Type</dt>
              <dd>
                <span className={`clients-badge clients-badge-${formeNorm}`}>
                  {formeLbl}
                </span>
                {clientDetail.forme_juridique
                  ? ` ${clientDetail.forme_juridique}`
                  : ""}
              </dd>
            </div>
            <div
              className={
                valeurResumeManquante("ncc", !!clientDetail.ncc?.trim())
                  ? "is-manquant"
                  : undefined
              }
            >
              <dt>NCC</dt>
              <dd>{clientDetail.ncc?.trim() || "À compléter"}</dd>
            </div>
            {formeNorm === "pm" && (
              <div
                className={
                  valeurResumeManquante("rccm", !!clientDetail.rccm?.trim())
                    ? "is-manquant"
                    : undefined
                }
              >
                <dt>RCCM</dt>
                <dd>{clientDetail.rccm?.trim() || "À compléter"}</dd>
              </div>
            )}
            <div
              className={
                valeurResumeManquante(
                  "regime_fiscal",
                  !!clientDetail.regime_fiscal?.trim(),
                )
                  ? "is-manquant"
                  : undefined
              }
            >
              <dt>Régime</dt>
              <dd>
                {clientDetail.regime_fiscal?.trim()
                  ? libelleRegime(clientDetail.regime_fiscal)
                  : "À compléter"}
              </dd>
            </div>
            {formeNorm === "pm" && (
              <div
                className={
                  valeurResumeManquante(
                    "capital_social",
                    clientDetail.capital_social != null &&
                      clientDetail.capital_social !== "",
                  )
                    ? "is-manquant"
                    : undefined
                }
              >
                <dt>Capital</dt>
                <dd>
                  {clientDetail.capital_social != null &&
                  clientDetail.capital_social !== ""
                    ? `${Number(clientDetail.capital_social).toLocaleString("fr-FR")} XOF`
                    : "À compléter"}
                </dd>
              </div>
            )}
            <div>
              <dt>Clôture</dt>
              <dd>{libelleMoisCloture(clientDetail.mois_cloture ?? 12)}</dd>
            </div>
            <div
              className={
                valeurResumeManquante(
                  "activite_principale",
                  !!clientDetail.activite_principale?.trim(),
                )
                  ? "is-manquant"
                  : undefined
              }
            >
              <dt>Secteur / activité</dt>
              <dd>{clientDetail.activite_principale?.trim() || "À compléter"}</dd>
            </div>
            <div
              className={
                valeurResumeManquante("commune", !!clientDetail.commune?.trim())
                  ? "is-manquant"
                  : undefined
              }
            >
              <dt>Commune</dt>
              <dd>{clientDetail.commune?.trim() || "À compléter"}</dd>
            </div>
            <div
              className={
                valeurResumeManquante(
                  "siege_social",
                  !!clientDetail.siege_social?.trim(),
                )
                  ? "is-manquant"
                  : undefined
              }
            >
              <dt>Adresse</dt>
              <dd>{clientDetail.siege_social?.trim() || "À compléter"}</dd>
            </div>
            <div
              className={
                valeurResumeManquante(
                  "centre_impots",
                  !!clientDetail.centre_impots?.trim(),
                )
                  ? "is-manquant"
                  : undefined
              }
            >
              <dt>Centre des impôts</dt>
              <dd>{clientDetail.centre_impots?.trim() || "À compléter"}</dd>
            </div>
          </dl>

          <PiecesContribuablePanel
            jeton={jeton}
            contribuableId={clientDetail.id}
            disabled={estLecteur || busy}
            edit={clientEdit}
            setEdit={setClientEdit}
            modeConformite
          />

          <RegistreRisquesVue
            jeton={jeton}
            contribuableId={clientDetail.id}
            estLecteur={estLecteur}
          />

          <div className="panel dense clients-fiche-panel" id="clients-fiche-edition">
            <div className="clients-fiche-section-head">
              <div>
                <p className="picker-kicker">Identité légale</p>
                <p className="picker-hint">
                  {estLecteur
                    ? "Lecture seule — rôle lecteur."
                    : modeEdition
                      ? "Modifiez puis enregistrez — les champs rouges sont à compléter."
                      : "Consultez le résumé ou passez en édition."}
                </p>
              </div>
              {!estLecteur && (
                <Tooltip
                  label={
                    modeEdition
                      ? "Revenir au résumé (sans enregistrer)."
                      : "Modifier la fiche contribuable."
                  }
                >
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={busy}
                    onClick={() => setModeEdition((v) => !v)}
                  >
                    {modeEdition ? "Fermer l’édition" : "Éditer"}
                  </button>
                </Tooltip>
              )}
            </div>

            {peutEditer ? (
              <>
                <IdentiteLegaleForm
                  prefix="edit"
                  edit={clientEdit}
                  setEdit={setClientEdit}
                  disabled={busy}
                  champsManquants={completude.clesManquantes}
                />
                <div className="cta-row clients-fiche-cta">
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={busy || !apiMin.ok}
                    onClick={() => {
                      onSauver();
                      setModeEdition(false);
                    }}
                  >
                    Enregistrer
                  </button>
                  {!apiMin.ok && (
                    <span className="cta-hint cta-hint-manquants">
                      Manque : {apiMin.manquants.join(" · ")}
                    </span>
                  )}
                  {!completude.complet && apiMin.ok && (
                    <p className="clients-fiche-nudge clients-fiche-nudge-inline">
                      Vous pouvez enregistrer le minimum API ; les champs encore
                      vides resteront signalés en rouge.
                    </p>
                  )}
                </div>
              </>
            ) : (
              !completude.complet &&
              !estLecteur && (
                <p className="clients-fiche-nudge">
                  Fiche incomplète —{" "}
                  <button
                    type="button"
                    className="linkish"
                    onClick={ouvrirEditionManquants}
                  >
                    compléter les infos manquantes
                  </button>
                  .
                </p>
              )
            )}
          </div>
        </div>
      ) : (
        <div
          className="clients-fiche-tab-panel"
          id={`fiche-${clientDetail.id}-panel-missions`}
          role="tabpanel"
          aria-labelledby={`fiche-${clientDetail.id}-tab-missions`}
        >
          <div className="clients-fiche-missions-head">
            <div>
              <h3 className="section-title clients-fiche-missions-title">
                Missions du contribuable
              </h3>
              <p className="clients-panel-hint">
                {clientDetail.nb_missions} mission
                {clientDetail.nb_missions !== 1 ? "s" : ""}
                {nbActives > 0
                  ? ` · ${nbActives} active${nbActives > 1 ? "s" : ""}`
                  : ""}
              </p>
            </div>
            <div className="clients-fiche-missions-actions">
              {missions.length > 0 && (
                <div
                  className="clients-missions-filtres"
                  role="group"
                  aria-label="Filtrer les missions"
                >
                  {(
                    [
                      ["toutes", "Toutes"],
                      ["actives", "Actives"],
                      ["cloturees", "Clôturées"],
                    ] as const
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      className={`clients-missions-filtre${filtreMissions === id ? " is-active" : ""}`}
                      aria-pressed={filtreMissions === id}
                      onClick={() => setFiltreMissions(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
              {!estLecteur && missions.length > 0 && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={onNouvelleMission}
                >
                  Nouvelle mission
                </button>
              )}
            </div>
          </div>

          <div className="panel dense clients-panel">
            {missionsFiltrees.length > 0 ? (
              <ul className="clients-missions-list">
                {missionsFiltrees.map((m) => (
                  <li key={m.id}>
                    <Tooltip
                      label={`Ouvrir la mission #${m.id} · exercice ${m.exercice}`}
                      side="bottom"
                    >
                      <button
                        type="button"
                        className="clients-mission-row"
                        onClick={() => onOuvrirMission(m.id)}
                      >
                        <span className="clients-mission-id">#{m.id}</span>
                        <span className="clients-mission-ex">
                          Exercice {m.exercice}
                          <span className="clients-mission-date">
                            {formaterDateCourte(m.cree_le)}
                          </span>
                        </span>
                        <span className={`badge statut-${m.statut}`}>
                          {libelleStatut(m.statut)}
                        </span>
                        <span className="clients-mission-open">
                          Ouvrir <span aria-hidden="true">→</span>
                        </span>
                      </button>
                    </Tooltip>
                  </li>
                ))}
              </ul>
            ) : missions.length > 0 ? (
              <div className="clients-empty clients-empty-compact">
                <p className="clients-empty-title">Aucune mission pour ce filtre</p>
                <p className="clients-empty-body">
                  Changez le filtre ou lancez une nouvelle mission.
                </p>
              </div>
            ) : (
              <div className="clients-empty clients-empty-compact">
                <p className="clients-empty-title">Aucune mission pour ce client</p>
                <p className="clients-empty-body">
                  {estLecteur
                    ? "Les missions liées apparaîtront ici."
                    : "Un contribuable peut porter plusieurs missions (exercices, campagnes)."}
                </p>
                {!estLecteur && (
                  <div className="clients-empty-actions">
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={onNouvelleMission}
                    >
                      Nouvelle mission
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
