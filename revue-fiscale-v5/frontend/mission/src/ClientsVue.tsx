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
  libelleSecteur,
  type FormePersonne,
  type IdentiteLegale,
} from "./legalite";
import { api } from "./api";
import { LIBELLES_IMPOT } from "./impotLabels";
import { PROCESS_TIPS } from "./processTips";
import {
  PiecesContribuablePanel,
  nouvelleSessionUpload,
} from "./PiecesContribuable";
import { DataRoomPanel } from "./DataRoomPanel";
import { HistoriqueContribuablePanel } from "./HistoriqueContribuable";
import {
  RegistreRisquesVue,
  tipInterpretationScoreRisque,
  type ResumeRisques,
  type ScoreRisque as ScoreRisqueContribuable,
} from "./RegistreRisques";
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

/** Échéance déclarative indicative (GET /contribuables/{id}/echeancier). */
export type EcheanceFiscale = {
  code: string;
  libelle: string;
  periodicite: string;
  impots: string[];
  date_limite: string; // ISO aaaa-mm-jj
  jours_restants: number;
  statut: "a_venir" | "imminente" | "depassee";
};

export type EcheancierContribuable = {
  contribuable_id: number;
  regime: string | null;
  mois_cloture?: number | null;
  reference: string;
  horizon_jours: number;
  indicatif: boolean;
  echeances: EcheanceFiscale[];
};

const ECHEANCE_BADGES: Record<
  EcheanceFiscale["statut"],
  { label: string; cls: string }
> = {
  a_venir: { label: "À venir", cls: "a-venir" },
  imminente: { label: "Imminent", cls: "imminent" },
  depassee: { label: "Dépassé", cls: "depasse" },
};

/** ISO aaaa-mm-jj → jj/mm/aaaa (affichage FR). */
function formaterDateEcheance(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso;
}

/** ISO aaaa-mm-jj → jj/mm (chip compact du bandeau). */
function formaterJourMois(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? `${m[3]}/${m[2]}` : iso;
}

/** Échéance de l'agenda fiscal cabinet (GET /cabinet/agenda-fiscal?jours=N). */
type EcheanceAgendaCabinet = {
  date_limite: string; // ISO aaaa-mm-jj
  impot: string;
  obligation: string;
  periode: string;
  mission_id: number;
  client: string;
  statut: "couverte" | "a_preparer";
};

type AgendaFiscalCabinetOut = {
  echeances: EcheanceAgendaCabinet[];
  note?: string;
};

function libelleImpotAgenda(code: string): string {
  return (LIBELLES_IMPOT as Record<string, string>)[code] ?? code;
}

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

/** Doublon NCC/RCCM dans le portefeuille — bloque l'enregistrement. */
function doublonIdentifiants(
  clients: ClientRow[] | undefined,
  edit: ClientEditState,
  exclureId?: number,
): string | null {
  if (!clients?.length) return null;
  const norm = (v: string | null | undefined) =>
    (v ?? "").trim().toUpperCase();
  const ncc = norm(edit.ncc);
  const rccm = norm(edit.rccm);
  for (const c of clients) {
    if (exclureId != null && c.id === exclureId) continue;
    if (ncc && norm(c.ncc) === ncc) {
      return `Doublon interdit : le NCC « ${edit.ncc.trim()} » est déjà utilisé par « ${c.denomination} ».`;
    }
    if (rccm && norm(c.rccm) === rccm) {
      return `Doublon interdit : le RCCM « ${edit.rccm.trim()} » est déjà utilisé par « ${c.denomination} ».`;
    }
  }
  return null;
}

/** Action du plan marquée « retenue » et pas encore « faite ». */
type ActionRetenueRow = {
  mission_id: number;
  exercice: number;
  cle_action: string;
  libelle_risque: string;
  impot: string;
  /** Exposition (montant + pénalités) en FCFA — null si non chiffrée. */
  exposition: string | null;
  /** Risque clos (ou purgé) depuis la décision — mention affichée. */
  risque_clos: boolean;
  decision_note: string | null;
  maj_le: string | null;
};

type ClientDetail = ClientRow & {
  missions: MissionRow[];
  nb_missions: number;
  /** Suivi demande de renseignements — missions non clôturées du client. */
  items_en_attente?: number;
  items_a_relancer?: number;
  /** Actions retenues en cours (plan d'actions) — toutes missions. */
  actions_retenues?: {
    items: ActionRetenueRow[];
    synthese: { total: number };
  };
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
          `Doublon interdit — ce NCC est déjà utilisé par « ${doublon.denomination} ». L'enregistrement sera refusé.`,
        );
      }
    }
    setNccWarn(avert.length ? avert.join(" ") : null);
  }

  function verifierRccm() {
    toucher("rccm");
    const avert: string[] = [];
    const format = avertissementFormatRccm(edit.rccm);
    if (format) avert.push(format);
    const saisi = edit.rccm.trim().toUpperCase();
    if (creation && saisi && clientsExistants?.length) {
      const doublon = clientsExistants.find(
        (c) => (c.rccm ?? "").trim().toUpperCase() === saisi,
      );
      if (doublon) {
        avert.push(
          `Doublon interdit — ce RCCM est déjà utilisé par « ${doublon.denomination} ». L'enregistrement sera refusé.`,
        );
      }
    }
    setRccmWarn(avert.length ? avert.join(" ") : null);
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
              onBlur={verifierRccm}
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
    const doublon = doublonIdentifiants(clients, edit);
    if (doublon) {
      setErreurLocale(doublon);
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
type FicheTab = "overview" | "risques" | "missions" | "historique" | "dataroom";

const FICHE_TABS: ReadonlyArray<{ id: FicheTab; label: string }> = [
  { id: "overview", label: "Vue d’ensemble" },
  { id: "risques", label: "Risques" },
  { id: "missions", label: "Missions" },
  { id: "historique", label: "Historique" },
  { id: "dataroom", label: "Data Room" },
];

function hashFicheTab(clientId: number, tab: FicheTab): string {
  return `#fiche-${clientId}-${tab}`;
}

function tabDepuisHash(clientId: number): FicheTab {
  const m = new RegExp(
    `^#fiche-${clientId}-(overview|identite|pieces|risques|missions|historique|dataroom)$`,
  ).exec(window.location.hash || "");
  const brut = m?.[1];
  // Rétro-compat : identité et pièces vivent dans la vue d'ensemble.
  if (
    brut === "risques" ||
    brut === "missions" ||
    brut === "historique" ||
    brut === "dataroom"
  )
    return brut;
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

  // Compteurs pièces / risques (informatifs — masqués si l'API échoue).
  // Chargés au niveau fiche : alimentent le bandeau sticky et la synthèse Risques.
  const [nbPieces, setNbPieces] = useState<number | null>(null);
  const [resumeRisques, setResumeRisques] = useState<ResumeRisques | null>(
    null,
  );
  // Score registre (déterministe, API existante) — header fiche.
  const [scoreRisque, setScoreRisque] =
    useState<ScoreRisqueContribuable | null>(null);

  useEffect(() => {
    let annule = false;
    void (async () => {
      try {
        const s = await api<ScoreRisqueContribuable>(
          `/api/v1/contribuables/${clientDetail.id}/risques/score`,
          { jeton },
        );
        if (!annule)
          setScoreRisque(s && typeof s.score === "number" ? s : null);
      } catch {
        if (!annule) setScoreRisque(null);
      }
    })();
    return () => {
      annule = true;
    };
  }, [clientDetail.id, jeton]);

  // Échéancier déclaratif indicatif (Vue d'ensemble uniquement).
  const [echeancier, setEcheancier] =
    useState<EcheancierContribuable | null>(null);

  useEffect(() => {
    if (ficheTab !== "overview") return;
    let annule = false;
    void (async () => {
      try {
        const e = await api<EcheancierContribuable>(
          `/api/v1/contribuables/${clientDetail.id}/echeancier`,
          { jeton },
        );
        if (!annule)
          setEcheancier(e && Array.isArray(e.echeances) ? e : null);
      } catch {
        if (!annule) setEcheancier(null); // Encart masqué si l'API échoue.
      }
    })();
    return () => {
      annule = true;
    };
  }, [clientDetail.id, jeton, ficheTab]);

  // Obligations à venir — agenda fiscal cabinet (90 j) filtré sur les
  // missions du client. Alimente le bloc de la vue d'ensemble et le chip
  // « Prochaine échéance » du bandeau (chargé au niveau fiche).
  const [agendaClient, setAgendaClient] =
    useState<AgendaFiscalCabinetOut | null>(null);
  const [agendaBusy, setAgendaBusy] = useState(false);
  const [agendaErr, setAgendaErr] = useState<string | null>(null);

  useEffect(() => {
    let annule = false;
    setAgendaBusy(true);
    setAgendaErr(null);
    void (async () => {
      try {
        const out = await api<AgendaFiscalCabinetOut>(
          "/api/v1/cabinet/agenda-fiscal?jours=90",
          { jeton },
        );
        if (!annule)
          setAgendaClient(out && Array.isArray(out.echeances) ? out : null);
      } catch {
        if (!annule) {
          setAgendaClient(null);
          setAgendaErr("Échéances indisponibles pour le moment.");
        }
      } finally {
        if (!annule) setAgendaBusy(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, [clientDetail.id, jeton]);

  useEffect(() => {
    let annule = false;
    void (async () => {
      try {
        const pieces = await api<unknown[]>(
          `/api/v1/pieces-contribuable?contribuable_id=${clientDetail.id}`,
          { jeton },
        );
        if (!annule) setNbPieces(Array.isArray(pieces) ? pieces.length : null);
      } catch {
        /* compteur indisponible — on n'affiche pas de chiffre */
      }
    })();
    void (async () => {
      try {
        const resume = await api<ResumeRisques>(
          `/api/v1/contribuables/${clientDetail.id}/risques/resume`,
          { jeton },
        );
        if (!annule)
          setResumeRisques(
            resume && typeof resume.total === "number" ? resume : null,
          );
      } catch {
        /* compteur indisponible */
      }
    })();
    return () => {
      annule = true;
    };
  }, [clientDetail.id, jeton]);

  // Alerte douce : TEE (régime de l'entreprenant) atypique pour une personne morale.
  const alerteRegimeTee =
    formeNorm === "pm" && clientDetail.regime_fiscal?.trim() === "tee";

  // Secteur / activité : « secteur — précision » quand les deux existent.
  const secteurAffiche = useMemo(() => {
    const brut = clientDetail.activite_principale?.trim() || "";
    if (!brut) return "";
    const { secteur, precision } = decomposerActivite(brut);
    if (!secteur) return brut;
    if (!precision) return libelleSecteur(secteur);
    return `${libelleSecteur(secteur)} — ${precision}`;
  }, [clientDetail.activite_principale]);

  const missions = clientDetail.missions || [];
  const missionsFiltrees = useMemo(() => {
    return missions.filter((m) => {
      if (filtreMissions === "actives") return estMissionActive(m.statut);
      if (filtreMissions === "cloturees") return !estMissionActive(m.statut);
      return true;
    });
  }, [missions, filtreMissions]);

  const nbActives = missions.filter((m) => estMissionActive(m.statut)).length;

  // Suivi de la demande de renseignements (missions non clôturées) —
  // compteurs fournis par la fiche (même définition que le tableau de
  // bord cabinet : à relancer = en attente avec relance échue).
  const itemsEnAttente = clientDetail.items_en_attente ?? 0;
  const itemsARelancer = clientDetail.items_a_relancer ?? 0;

  // Actions du plan d'actions marquées « retenue » et pas encore
  // « faites » — toutes missions du client (fournies par la fiche).
  const actionsRetenues = clientDetail.actions_retenues?.items ?? [];
  const totalActionsRetenues =
    clientDetail.actions_retenues?.synthese?.total ?? 0;

  // Échéances agenda du cabinet restreintes aux missions du client (max 8,
  // triées par date — le backend n'inclut que les missions actives).
  const echeancesClient = useMemo(() => {
    const ids = new Set(missions.map((m) => m.id));
    return (agendaClient?.echeances ?? [])
      .filter((e) => ids.has(e.mission_id))
      .slice()
      .sort((a, b) => a.date_limite.localeCompare(b.date_limite))
      .slice(0, 8);
  }, [agendaClient, missions]);

  const prochaineEcheanceClient = echeancesClient[0]?.date_limite ?? null;

  /** Chip bandeau → vue d'ensemble + scroll vers le bloc des obligations. */
  function allerAuxEcheances() {
    changerFicheTab("overview");
    window.requestAnimationFrame(() => {
      document
        .getElementById(`fiche-${clientDetail.id}-echeances`)
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  // Dernier exercice revu — la plus récente année portée par une mission.
  const dernierExercice = useMemo(() => {
    let max = 0;
    for (const m of missions) {
      if (typeof m.exercice === "number" && m.exercice > max) max = m.exercice;
    }
    return max > 0 ? max : null;
  }, [missions]);

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

  // Barre de complétude — affichée dans Vue d'ensemble et Identité uniquement
  // (le sous-titre d'en-tête n'affiche plus le score : pas de doublon).
  const barreCompletude = (
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
  );

  /** Ligne clé-valeur d'un bloc de la vue d'ensemble (fiche2). */
  function propFiche(
    label: string,
    valeur: string,
    opts: { cle?: string; remplie?: boolean; decisif?: boolean } = {},
  ) {
    const remplie = opts.remplie ?? valeur.trim().length > 0;
    const manquant = opts.cle ? valeurResumeManquante(opts.cle, remplie) : false;
    return (
      <div
        className={[
          manquant ? "is-manquant" : "",
          opts.decisif ? "fiche2-prop-cle" : "",
        ]
          .filter(Boolean)
          .join(" ") || undefined}
      >
        <dt>{label}</dt>
        <dd>{remplie ? valeur : "À compléter"}</dd>
      </div>
    );
  }

  const resumeIdentite = (
    <>
      <div className="fiche2-blocs" aria-label="Résumé d’identité">
        <section className="fiche2-bloc" aria-label="Identité légale">
          <p className="fiche2-bloc-titre">Identité légale</p>
          <dl className="fiche2-props">
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
            {propFiche("NCC", clientDetail.ncc?.trim() || "", { cle: "ncc" })}
            {formeNorm === "pm" &&
              propFiche("RCCM", clientDetail.rccm?.trim() || "", {
                cle: "rccm",
              })}
            {formeNorm === "pm" &&
              propFiche(
                "Capital",
                clientDetail.capital_social != null &&
                  clientDetail.capital_social !== ""
                  ? `${Number(clientDetail.capital_social).toLocaleString("fr-FR")} XOF`
                  : "",
                {
                  cle: "capital_social",
                  remplie:
                    clientDetail.capital_social != null &&
                    clientDetail.capital_social !== "",
                },
              )}
            {propFiche(
              "Immatriculation",
              formaterDateCourte(clientDetail.date_immatriculation),
            )}
          </dl>
        </section>

        <section className="fiche2-bloc" aria-label="Coordonnées fiscales">
          <p className="fiche2-bloc-titre">Coordonnées fiscales</p>
          <dl className="fiche2-props">
            {propFiche(
              "Centre des impôts",
              clientDetail.centre_impots?.trim() || "",
              { cle: "centre_impots", decisif: true },
            )}
            {propFiche("Commune", clientDetail.commune?.trim() || "", {
              cle: "commune",
            })}
            {propFiche("Adresse", clientDetail.siege_social?.trim() || "", {
              cle: "siege_social",
            })}
          </dl>
        </section>

        <section className="fiche2-bloc" aria-label="Paramètres fiscaux">
          <p className="fiche2-bloc-titre">Paramètres</p>
          <dl className="fiche2-props">
            {propFiche(
              "Régime fiscal",
              clientDetail.regime_fiscal?.trim()
                ? libelleRegime(clientDetail.regime_fiscal)
                : "",
              { cle: "regime_fiscal", decisif: true },
            )}
            {propFiche(
              "Clôture d’exercice",
              libelleMoisCloture(clientDetail.mois_cloture ?? 12),
              { decisif: true },
            )}
            {propFiche("Secteur / activité", secteurAffiche, {
              cle: "activite_principale",
            })}
          </dl>
        </section>
      </div>
      {alerteRegimeTee && (
        <p className="field-averti-msg clients-fiche-averti" role="note">
          Régime TEE inhabituel pour une{" "}
          {clientDetail.forme_juridique || "personne morale"} — vérifier le
          régime déclaré.
        </p>
      )}
      {(traceQui || traceQuand) && (
        <p className="fiche2-audit" aria-label="Traçabilité de création">
          Créé
          {traceQui ? ` par ${traceQui}` : ""}
          {traceQuand ? ` · ${traceQuand}` : ""}
          <span className="fiche2-audit-tz"> (heure Abidjan)</span>
        </p>
      )}
    </>
  );

  return (
    <div className="page clients-fiche">
      <div className="fiche2-sticky">
        <header className="fiche2-bandeau" aria-label="Synthèse du client">
          <div className="fiche2-bandeau-id">
            <span className="fiche2-mark" aria-hidden="true" />
            <h2 className="fiche2-nom">{clientDetail.denomination}</h2>
            <span className={`clients-badge clients-badge-${formeNorm}`}>
              {formeLbl}
            </span>
            {clientDetail.forme_juridique?.trim() ? (
              <span className="fiche2-badge">
                {clientDetail.forme_juridique.trim()}
              </span>
            ) : null}
            {clientDetail.regime_fiscal?.trim() ? (
              <span className="fiche2-badge">
                {libelleRegime(clientDetail.regime_fiscal)}
              </span>
            ) : null}
            <span className="fiche2-bandeau-meta">
              {clientDetail.ncc?.trim()
                ? `NCC ${clientDetail.ncc.trim()}`
                : `Fiche #${clientDetail.id}`}
            </span>
          </div>

          <div
            className="fiche2-bandeau-indics"
            role="group"
            aria-label="Indicateurs du client"
          >
            <Tooltip label="Voir les missions du contribuable.">
              <button
                type="button"
                className="fiche2-indic"
                onClick={() => changerFicheTab("missions")}
              >
                <strong>{clientDetail.nb_missions}</strong>
                mission{clientDetail.nb_missions !== 1 ? "s" : ""}
                {nbActives > 0 ? ` · ${nbActives} en cours` : ""}
              </button>
            </Tooltip>
            <Tooltip label="Ouvrir le registre des risques.">
              <button
                type="button"
                className={`fiche2-indic${(resumeRisques?.ouverts ?? 0) > 0 ? " is-alerte" : ""}`}
                onClick={() => changerFicheTab("risques")}
              >
                <strong>{resumeRisques ? resumeRisques.ouverts : "—"}</strong>
                risque{(resumeRisques?.ouverts ?? 0) !== 1 ? "s" : ""} ouvert
                {(resumeRisques?.ouverts ?? 0) !== 1 ? "s" : ""}
              </button>
            </Tooltip>
            <Tooltip label="Ouvrir la Data Room (pièces, mémoire, timeline).">
              <button
                type="button"
                className="fiche2-indic"
                onClick={() => changerFicheTab("dataroom")}
              >
                <strong>{nbPieces ?? "—"}</strong>
                pièce{(nbPieces ?? 0) !== 1 ? "s" : ""}
              </button>
            </Tooltip>
            {dernierExercice != null && (
              <Tooltip label="Exercice le plus récent couvert par une mission.">
                <span className="fiche2-indic fiche2-indic-passif">
                  Dernier exercice <strong>{dernierExercice}</strong>
                </span>
              </Tooltip>
            )}
            <Tooltip label="Voir les obligations à venir (90 jours) sur les missions actives du client.">
              <button
                type="button"
                className="fiche2-indic"
                onClick={allerAuxEcheances}
              >
                Prochaine échéance{" "}
                <strong>
                  {prochaineEcheanceClient
                    ? formaterJourMois(prochaineEcheanceClient)
                    : "—"}
                </strong>
              </button>
            </Tooltip>
            {itemsEnAttente + itemsARelancer > 0 && (
              <Tooltip label="Items de la demande de renseignements en attente sur les missions non clôturées du client — voir l’onglet Missions.">
                <button
                  type="button"
                  className={`fiche2-indic${itemsARelancer > 0 ? " is-alerte" : ""}`}
                  onClick={() => changerFicheTab("missions")}
                >
                  <strong>{itemsEnAttente}</strong>
                  en attente · {itemsARelancer} à relancer
                </button>
              </Tooltip>
            )}
            {scoreRisque && (
              <Tooltip
                className="tip-score-risque"
                label={tipInterpretationScoreRisque(scoreRisque)}
              >
                <button
                  type="button"
                  className={`fiche2-indic fiche2-indic-score niveau-${scoreRisque.niveau}`}
                  aria-label={
                    scoreRisque.score === 0
                      ? scoreRisque.libelle_niveau
                      : scoreRisque.plage
                        ? `Score risque ${scoreRisque.score} sur 100 — ${scoreRisque.libelle_niveau} (${scoreRisque.plage})`
                        : `Score risque ${scoreRisque.score} sur 100 — ${scoreRisque.libelle_niveau}`
                  }
                  onClick={() => changerFicheTab("risques")}
                >
                  {scoreRisque.score === 0 ? (
                    scoreRisque.libelle_niveau
                  ) : (
                    <>
                      Score <strong>{scoreRisque.score}/100</strong>
                      {` · ${scoreRisque.libelle_niveau}`}
                    </>
                  )}
                </button>
              </Tooltip>
            )}
          </div>

          <div className="fiche2-bandeau-actions">
            <Tooltip label="Retour au portefeuille clients.">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={onRetour}
              >
                Retour liste
              </button>
            </Tooltip>
            {!estLecteur && (
              <Tooltip label="Lancer une mission préremplie avec cette fiche.">
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
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
          {FICHE_TABS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              id={`fiche-${clientDetail.id}-tab-${id}`}
              className={`tab${ficheTab === id ? " active" : ""}`}
              role="tab"
              aria-selected={ficheTab === id}
              aria-controls={`fiche-${clientDetail.id}-panel-${id}`}
              tabIndex={ficheTab === id ? 0 : -1}
              onClick={() => changerFicheTab(id)}
            >
              {label}
              {id === "missions" && clientDetail.nb_missions > 0 ? (
                <span className="clients-fiche-tab-count" aria-hidden="true">
                  {clientDetail.nb_missions}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      </div>

      {ficheTab === "overview" && (
        <div
          className="clients-fiche-tab-panel"
          id={`fiche-${clientDetail.id}-panel-overview`}
          role="tabpanel"
          aria-labelledby={`fiche-${clientDetail.id}-tab-overview`}
        >
          {barreCompletude}

          {echeancier && (
            <section
              className="panel dense echeancier-encart"
              aria-label="Échéancier déclaratif indicatif"
            >
              <div className="echeancier-head">
                <p className="picker-kicker">
                  Échéancier déclaratif (indicatif)
                </p>
                <p className="picker-hint">
                  {echeancier.regime?.trim()
                    ? `Régime ${libelleRegime(echeancier.regime)} — prochaines obligations sur ${echeancier.horizon_jours} jours.`
                    : "Renseignez le régime fiscal pour projeter les obligations."}
                </p>
              </div>
              {echeancier.echeances.length === 0 ? (
                <p className="echeancier-vide">
                  {echeancier.regime?.trim()
                    ? "Aucune échéance connue sur l'horizon."
                    : "Aucune échéance — régime fiscal non renseigné."}
                </p>
              ) : (
                <ul className="echeancier-liste">
                  {echeancier.echeances.map((e) => {
                    const badge = ECHEANCE_BADGES[e.statut] ?? {
                      label: e.statut,
                      cls: "a-venir",
                    };
                    return (
                      <li
                        key={`${e.code}-${e.date_limite}`}
                        className="echeancier-ligne"
                      >
                        <span className="echeancier-date">
                          {formaterDateEcheance(e.date_limite)}
                        </span>
                        <span className="echeancier-libelle">
                          {e.libelle}
                        </span>
                        <span
                          className={`echeancier-badge ${badge.cls}`}
                          title={
                            e.jours_restants >= 0
                              ? `Dans ${e.jours_restants} jour${e.jours_restants > 1 ? "s" : ""}`
                              : `En retard de ${-e.jours_restants} jour${-e.jours_restants > 1 ? "s" : ""}`
                          }
                        >
                          {badge.label}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
              <p className="echeancier-note" role="note">
                Référentiel indicatif — vérifier le calendrier officiel DGI.
              </p>
            </section>
          )}

          <section
            className="panel dense fiche2-echeances"
            id={`fiche-${clientDetail.id}-echeances`}
            aria-label="Obligations à venir sur les missions du client"
          >
            <div className="fiche2-echeances-head">
              <h3 className="fiche2-titre">Obligations à venir</h3>
              <span className="fiche2-echeances-hint">
                90 jours · missions actives
              </span>
            </div>

            {agendaBusy && !agendaClient && (
              <p className="agenda2-vide">Chargement des échéances…</p>
            )}
            {agendaErr && !agendaBusy && (
              <p className="agenda2-err">{agendaErr}</p>
            )}

            {agendaClient &&
              (echeancesClient.length > 0 ? (
                <ul className="agenda2-liste">
                  {echeancesClient.map((e, i) => (
                    <li key={`${e.date_limite}-${e.mission_id}-${e.impot}-${i}`}>
                      <button
                        type="button"
                        className="agenda2-row"
                        title={`Ouvrir la mission #${e.mission_id}`}
                        onClick={() => onOuvrirMission(e.mission_id)}
                      >
                        <span className="fiche2-echeances-date">
                          {formaterDateEcheance(e.date_limite)}
                        </span>
                        <span
                          className="agenda2-impot"
                          title={libelleImpotAgenda(e.impot)}
                        >
                          {e.impot}
                        </span>
                        <span className="agenda2-obligation">
                          {e.obligation}
                        </span>
                        <span className="agenda2-meta">{e.periode}</span>
                        <span
                          className={`agenda2-badge ${
                            e.statut === "couverte" ? "couverte" : "preparer"
                          }`}
                        >
                          {e.statut === "couverte" ? "Couverte" : "À préparer"}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="agenda2-vide">
                  Aucune échéance dans les 90 prochains jours sur les missions
                  actives.
                </p>
              ))}

            <p className="agenda2-note" role="note">
              Agenda consultatif — vérifier le calendrier officiel DGI.
            </p>
          </section>

          {totalActionsRetenues > 0 && (
            <section
              className="panel dense fiche2-echeances"
              id={`fiche-${clientDetail.id}-actions-retenues`}
              aria-label="Actions retenues en cours sur les missions du client"
            >
              <div className="fiche2-echeances-head">
                <h3 className="fiche2-titre">Actions retenues en cours</h3>
                <span className="fiche2-echeances-hint">
                  {totalActionsRetenues} à mettre en œuvre · toutes missions
                  {totalActionsRetenues > actionsRetenues.length
                    ? ` · ${actionsRetenues.length} affichées`
                    : ""}
                </span>
              </div>
              <ul className="agenda2-liste">
                {actionsRetenues.map((a) => (
                  <li key={`${a.mission_id}-${a.cle_action}`}>
                    <button
                      type="button"
                      className="agenda2-row"
                      title={`Ouvrir la mission #${a.mission_id}`}
                      onClick={() => onOuvrirMission(a.mission_id)}
                    >
                      <span
                        className="agenda2-impot"
                        title={libelleImpotAgenda(a.impot)}
                      >
                        {a.impot || "—"}
                      </span>
                      <span className="agenda2-obligation">
                        {a.libelle_risque || a.cle_action}
                        {a.risque_clos ? " (risque clos depuis)" : ""}
                      </span>
                      <span className="agenda2-meta">
                        Exercice {a.exercice}
                        {a.exposition != null
                          ? ` · ${Number(a.exposition).toLocaleString("fr-FR")} FCFA`
                          : ""}
                        {a.decision_note?.trim()
                          ? ` · ${a.decision_note.trim()}`
                          : ""}
                      </span>
                      <span className="agenda2-badge preparer">Retenue</span>
                    </button>
                  </li>
                ))}
              </ul>
              <p className="agenda2-note" role="note">
                Suivi consultatif du plan d'actions — décisions du cabinet, le
                client reste seul décideur de la mise en œuvre.
              </p>
            </section>
          )}

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
              <>
                {resumeIdentite}
                {!completude.complet && !estLecteur && (
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
                )}
              </>
            )}
          </div>

          <div id={`fiche-${clientDetail.id}-panel-pieces`}>
            <PiecesContribuablePanel
              jeton={jeton}
              contribuableId={clientDetail.id}
              disabled={estLecteur || busy}
              edit={clientEdit}
              setEdit={setClientEdit}
              modeConformite
            />
          </div>
        </div>
      )}

      {ficheTab === "risques" && (
        <div
          className="clients-fiche-tab-panel"
          id={`fiche-${clientDetail.id}-panel-risques`}
          role="tabpanel"
          aria-labelledby={`fiche-${clientDetail.id}-tab-risques`}
        >
          <div className="fiche2-sec-head">
            <h3 className="fiche2-titre">Registre des risques</h3>
          </div>
          {resumeRisques && resumeRisques.total > 0 && (
            <div
              className="fiche2-risques-synthese"
              role="group"
              aria-label="Synthèse du registre des risques"
            >
              <span
                className={`fiche2-synthese-item${resumeRisques.ouverts > 0 ? " is-alerte" : ""}`}
              >
                <strong>{resumeRisques.ouverts}</strong>
                ouvert{resumeRisques.ouverts !== 1 ? "s" : ""}
              </span>
              <span className="fiche2-synthese-item is-ok">
                <strong>{resumeRisques.traites}</strong>
                traité{resumeRisques.traites !== 1 ? "s" : ""}
              </span>
              <span
                className={`fiche2-synthese-item${resumeRisques.actions_en_retard > 0 ? " is-alerte" : ""}`}
              >
                <strong>{resumeRisques.actions_en_retard}</strong>
                action{resumeRisques.actions_en_retard !== 1 ? "s" : ""} en
                retard
              </span>
              {resumeRisques.acceptes_client > 0 && (
                <span className="fiche2-synthese-item">
                  <strong>{resumeRisques.acceptes_client}</strong>
                  accepté{resumeRisques.acceptes_client !== 1 ? "s" : ""} client
                </span>
              )}
            </div>
          )}
          <RegistreRisquesVue
            jeton={jeton}
            contribuableId={clientDetail.id}
            estLecteur={estLecteur}
          />
        </div>
      )}

      {ficheTab === "historique" && (
        <div
          className="clients-fiche-tab-panel"
          id={`fiche-${clientDetail.id}-panel-historique`}
          role="tabpanel"
          aria-labelledby={`fiche-${clientDetail.id}-tab-historique`}
        >
          <div className="fiche2-sec-head">
            <h3 className="fiche2-titre">Historique du contribuable</h3>
          </div>
          <HistoriqueContribuablePanel
            jeton={jeton}
            contribuableId={clientDetail.id}
            onOuvrirMission={onOuvrirMission}
          />
        </div>
      )}

      {ficheTab === "dataroom" && (
        <div
          className="clients-fiche-tab-panel"
          id={`fiche-${clientDetail.id}-panel-dataroom`}
          role="tabpanel"
          aria-labelledby={`fiche-${clientDetail.id}-tab-dataroom`}
        >
          <div className="fiche2-sec-head">
            <h3 className="fiche2-titre">Data Room</h3>
          </div>
          <DataRoomPanel
            jeton={jeton}
            contribuableId={clientDetail.id}
            estLecteur={estLecteur}
          />
        </div>
      )}

      {ficheTab === "missions" && (
        <div
          className="clients-fiche-tab-panel"
          id={`fiche-${clientDetail.id}-panel-missions`}
          role="tabpanel"
          aria-labelledby={`fiche-${clientDetail.id}-tab-missions`}
        >
          <div className="fiche2-sec-head">
            <div>
              <h3 className="fiche2-titre">Missions du contribuable</h3>
              <p className="clients-panel-hint">
                {clientDetail.nb_missions} mission
                {clientDetail.nb_missions !== 1 ? "s" : ""}
                {nbActives > 0
                  ? ` · ${nbActives} active${nbActives > 1 ? "s" : ""}`
                  : ""}
              </p>
            </div>
            <div className="fiche2-sec-actions">
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
              <ul className="fiche2-missions">
                {missionsFiltrees.map((m) => (
                  <li key={m.id}>
                    <Tooltip
                      label={`Ouvrir la mission #${m.id} · exercice ${m.exercice}`}
                      side="bottom"
                    >
                      <button
                        type="button"
                        className="fiche2-mission-carte"
                        onClick={() => onOuvrirMission(m.id)}
                      >
                        <span className="fiche2-mission-haut">
                          <span className="fiche2-mission-id">#{m.id}</span>
                          <span className={`badge statut-${m.statut}`}>
                            {libelleStatut(m.statut)}
                          </span>
                        </span>
                        <span className="fiche2-mission-badges">
                          <span className="fiche2-badge fiche2-badge-exercice">
                            Exercice {m.exercice}
                          </span>
                          {m.type_engagement_libelle?.trim() ? (
                            <span className="fiche2-badge">
                              {m.type_engagement_libelle.trim()}
                            </span>
                          ) : null}
                        </span>
                        <span className="fiche2-mission-pied">
                          <span className="fiche2-mission-date">
                            {formaterDateCourte(m.cree_le)}
                          </span>
                          <span className="fiche2-mission-ouvrir">
                            Ouvrir <span aria-hidden="true">→</span>
                          </span>
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
