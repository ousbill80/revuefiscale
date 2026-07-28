import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  AUTH_EXPIREE_EVENT,
  ApiError,
  api,
  apiUpload,
  fmtMontant,
  telecharger,
} from "./api";
import {
  analyserBalanceCsv,
  analyserBalanceJson,
  checklistControleurAvantLancement,
  fmtXof,
  type BalanceAnalyse,
  type ChecklistItem,
} from "./balanceAnalyse";
import { Logo, LogoMark } from "./Logo";
import {
  REGIMES_FISCAUX,
  composerActivite,
  completudeIdentite,
  identiteApiMinimale,
  type FormePersonne,
} from "./legalite";
import {
  ClientCreationVue,
  ClientFicheVue,
  ClientsVue,
  etatInitialClientEdit,
  payloadDepuisEdit,
  type ClientEditState,
} from "./ClientsVue";
import {
  MissionsVue,
  estMissionActive,
  libelleStatut,
  type MissionRow,
} from "./MissionsVue";
import {
  CadrageMissionVue,
  type CabinetProfil,
} from "./CadrageMissionVue";
import { CompteVue } from "./CompteVue";
import { AgendaFiscalVue } from "./AgendaFiscalVue";
import { CentreAlertesVue } from "./CentreAlertesVue";
import { EcheancesCabinetVue } from "./EcheancesCabinetVue";
import { MonTableauVue } from "./MonTableauVue";
import { RelancesCabinetVue } from "./RelancesCabinetVue";
import { ActionsCabinetVue } from "./ActionsCabinetVue";
import { RentabiliteCabinetVue } from "./RentabiliteCabinetVue";
import { DelaisCabinetVue } from "./DelaisCabinetVue";
import { ClotureCabinetVue } from "./ClotureCabinetVue";
import { PointsConvenusCabinetVue } from "./PointsConvenusCabinetVue";
import { CompletudeDataRoomVue } from "./CompletudeDataRoomVue";
import { EquipeVue } from "./EquipeVue";
import { FacturationVue } from "./FacturationVue";
import {
  TYPES_PIECE_CONTRIBUABLE,
  type PieceContribuable,
} from "./PiecesContribuable";
import { PhoneField } from "./PhoneField";
import { PROCESS_TIPS } from "./processTips";
import { PointsAnterieursVue } from "./PointsAnterieursVue";
import { ControlesFiscauxVue } from "./ControlesFiscauxVue";
import { RapprochementTvaVue } from "./RapprochementTvaVue";
import { CompletudeDeclarativeVue } from "./CompletudeDeclarativeVue";
import { CoherenceCaVue } from "./CoherenceCaVue";
import { RetenueLoyersVue } from "./RetenueLoyersVue";
import { RetenueHonorairesVue } from "./RetenueHonorairesVue";
import { DeficitsReportablesVue } from "./DeficitsReportablesVue";
import { RapprochementAcomptesVue } from "./RapprochementAcomptesVue";
import { DeductibiliteVue } from "./DeductibiliteVue";
import { RapprochementSalairesVue } from "./RapprochementSalairesVue";
import { AcomptesVue } from "./AcomptesVue";
import { ResultatFiscalVue } from "./ResultatFiscalVue";
import { PatenteVue } from "./PatenteVue";
import { ChargeFiscaleVue } from "./ChargeFiscaleVue";
import { PanoramaConformiteVue } from "./PanoramaConformiteVue";
import { MaterialiteVue } from "./MaterialiteVue";
import { ProgrammeProposeVue } from "./ProgrammeProposeVue";
import { RestitutionVue } from "./RestitutionVue";
import { DossierMissionVue } from "./DossierMissionVue";
import { FilConducteurVue } from "./FilConducteurVue";
import { LettreMissionVue } from "./LettreMissionVue";
import type { ResumeRisques } from "./RegistreRisques";
import { InfoTip, Tooltip } from "./Tooltip";
import type { AuditJournal, Restitution, SessionAuth } from "./types";

/** Balance synthétique — montants FICTIFS, non opposables. */
const BALANCE_DEMO = `{
  "avertissement": "[DÉMO FICTIF] Balance synthétique — montants non réels, non opposables. Source : fixtures/balance_demo.json",
  "lignes": [
    {"compte": "7011", "libelle": "[FICTIF] Ventes", "debit": "0", "credit": "1000000000"},
    {"compte": "6582", "libelle": "[FICTIF] Dons", "debit": "150000000", "credit": "0"},
    {"compte": "622", "libelle": "[FICTIF] Honoraires", "debit": "50000000", "credit": "0"},
    {"compte": "6011", "libelle": "[FICTIF] Achats", "debit": "600000000", "credit": "0"},
    {"compte": "5121", "libelle": "[FICTIF] Banque", "debit": "200000000", "credit": "0"}
  ]
}`;

const BALANCE_COMMERCE = `{
  "avertissement": "[DÉMO FICTIF] Balance commerce synthétique — montants non réels, non opposables.",
  "lignes": [
    {"compte": "101", "libelle": "[FICTIF] Capital social", "debit": "0", "credit": "200000000"},
    {"compte": "211", "libelle": "[FICTIF] Terrains", "debit": "80000000", "credit": "0"},
    {"compte": "244", "libelle": "[FICTIF] Materiel", "debit": "120000000", "credit": "0"},
    {"compte": "4011", "libelle": "[FICTIF] Fournisseurs", "debit": "0", "credit": "90000000"},
    {"compte": "4111", "libelle": "[FICTIF] Clients", "debit": "150000000", "credit": "0"},
    {"compte": "521", "libelle": "[FICTIF] Banque", "debit": "190000000", "credit": "0"},
    {"compte": "6011", "libelle": "[FICTIF] Achats", "debit": "450000000", "credit": "0"},
    {"compte": "7011", "libelle": "[FICTIF] Ventes", "debit": "0", "credit": "800000000"},
    {"compte": "622", "libelle": "[FICTIF] Honoraires", "debit": "40000000", "credit": "0"},
    {"compte": "6582", "libelle": "[FICTIF] Dons", "debit": "60000000", "credit": "0"}
  ]
}`;

const BALANCE_SERVICES = `{
  "avertissement": "[DÉMO FICTIF] Balance services synthétique — montants non réels, non opposables.",
  "lignes": [
    {"compte": "101", "libelle": "[FICTIF] Capital", "debit": "0", "credit": "50000000"},
    {"compte": "4111", "libelle": "[FICTIF] Clients", "debit": "25000000", "credit": "0"},
    {"compte": "5121", "libelle": "[FICTIF] Banque", "debit": "75000000", "credit": "0"},
    {"compte": "622", "libelle": "[FICTIF] Honoraires", "debit": "30000000", "credit": "0"},
    {"compte": "641", "libelle": "[FICTIF] Remunerations", "debit": "80000000", "credit": "0"},
    {"compte": "7061", "libelle": "[FICTIF] Prestations", "debit": "0", "credit": "160000000"}
  ]
}`;

const JEUX_BALANCE = [
  {
    id: "demo",
    label: "Démo standard",
    hint: "5 lignes — calage rapide",
    json: BALANCE_DEMO,
  },
  {
    id: "commerce",
    label: "Commerce",
    hint: "Achats / ventes marchandises",
    json: BALANCE_COMMERCE,
  },
  {
    id: "services",
    label: "Services",
    hint: "Prestations & charges",
    json: BALANCE_SERVICES,
  },
] as const;

const STEPS = [
  { n: 1, lbl: "Cadrage", desc: "Lettre de mission" },
  { n: 2, lbl: "Sources", desc: "Data room & import" },
  { n: 3, lbl: "Résultat", desc: "Restitution" },
] as const;

const TYPES_ENGAGEMENT = [
  { value: "preventive", label: "Revue préventive" },
  { value: "cac", label: "Commissariat aux comptes" },
  { value: "due_diligence", label: "Due diligence" },
  { value: "assistance_controle", label: "Assistance à contrôle" },
  { value: "autre", label: "Autre" },
] as const;

/** Source primaire alimentant solde_compte — une seule à l’import. */
type SourceComptableKind =
  | "balance"
  | "etats-financiers"
  | "grand-livre"
  | "fec";

type TypePieceApi =
  | "balance"
  | "etats_financiers"
  | "grand_livre"
  | "fec"
  | "autre";

/** Pièce déposée dans la data room de la mission (GET /missions/{id}/pieces). */
type PieceMission = {
  id: number;
  nom_fichier: string;
  role: string;
  type_piece?: string;
  cree_le?: string | null;
};

/** Pièce tabulaire du Data Room (FEC/CSV/XLSX) utilisable comme source. */
type PieceTabulaire = {
  id: number;
  nom_fichier: string;
  format: "fec" | "csv" | "xlsx" | string;
  taille_octets: number;
  cree_le?: string | null;
};

function fmtTaillePiece(octets: number): string {
  if (octets >= 1024 * 1024) {
    return `${(octets / (1024 * 1024)).toFixed(1)} Mo`;
  }
  return `${Math.max(1, Math.round(octets / 1024))} Ko`;
}

function typePieceDepuisSource(kind: SourceComptableKind): TypePieceApi {
  switch (kind) {
    case "balance":
      return "balance";
    case "etats-financiers":
      return "etats_financiers";
    case "grand-livre":
      return "grand_livre";
    case "fec":
      return "fec";
  }
}

/** Types de pièce acceptés par le dépôt data room (backend socle). */
const TYPES_PIECE_MISSION: Array<{ id: TypePieceApi; label: string }> = [
  { id: "balance", label: "Balance" },
  { id: "etats_financiers", label: "États financiers" },
  { id: "grand_livre", label: "Grand livre" },
  { id: "fec", label: "FEC" },
  { id: "autre", label: "Autre" },
];

const SOURCES_COMPTABLES: Array<{
  id: SourceComptableKind;
  label: string;
  short: string;
  hint: string;
  accept: string;
  route: string;
  prioritaire?: boolean;
}> = [
  {
    id: "balance",
    label: "Balance SYSCOHADA",
    short: "Balance",
    hint: "Défaut recommandé — JSON, CSV ou Excel. Contrôle d’équilibre local puis import serveur.",
    accept: ".csv,.tsv,.txt,.json,.xlsx,.xlsm",
    route: "balance",
    prioritaire: true,
  },
  {
    id: "etats-financiers",
    label: "États financiers",
    short: "EF",
    hint: "Alternative — postes → soldes dérivés (sans exiger l’équilibre). JSON ou CSV.",
    accept: ".csv,.tsv,.txt,.json",
    route: "etats-financiers",
  },
  {
    id: "grand-livre",
    label: "Grand livre",
    short: "GL",
    hint: "Alternative — écritures agrégées par compte vers solde_compte. CSV uniquement.",
    accept: ".csv,.tsv,.txt",
    route: "grand-livre",
  },
  {
    id: "fec",
    label: "FEC",
    short: "FEC",
    hint: "Alternative — fichier d’écritures (| / tab / csv), agrégé par CompteNum.",
    accept: ".txt,.csv,.tsv",
    route: "fec",
  },
];

type Vue =
  | "dashboard"
  | "clients"
  | "client"
  | "client-nouveau"
  | "missions"
  | "nouvelle"
  | "equipe"
  | "facturation"
  | "compte";

export type Contribuable = {
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

type ContribuableDetail = Contribuable & {
  missions: MissionRow[];
  nb_missions: number;
  /** Suivi demande de renseignements — missions non clôturées du client. */
  items_en_attente?: number;
  items_a_relancer?: number;
};

type QuotaResume = {
  missions_incluses: number;
  missions_utilisees: number;
  ratio: number;
  alerte_80: boolean;
  bloque: boolean;
};

/** Réponse GET /api/v1/pilotage — cockpit portefeuille de l'associé. */
type PilotagePortefeuille = {
  exposition_par_client: Array<{
    contribuable_id: number;
    denomination: string;
    exposition_ouverte: string;
    nb_risques_ouverts: number;
    score: number;
    niveau: string;
  }>;
  missions_a_cloturer: Array<{
    mission_id: number;
    contribuable_id: number;
    denomination: string;
    exercice: number;
    derniere_execution_le: string | null;
    jours_inactivite: number;
  }>;
  alertes_source: Array<{
    mission_id: number;
    contribuable_id: number;
    denomination: string;
    exercice: number;
    codes_alerte: string[];
    controle_le: string | null;
  }>;
  risques_en_retard: {
    total: number;
    top: Array<{
      risque_id: number;
      contribuable_id: number;
      denomination: string;
      libelle: string;
      montant_estime: string;
      echeance: string | null;
    }>;
  };
  echeances_portefeuille: {
    total: number;
    lignes: Array<{
      contribuable_id: number;
      denomination: string;
      code: string;
      libelle: string;
      date_limite: string;
      jours_restants: number;
      statut: string;
    }>;
  };
  relances_circularisation: {
    missions_concernees: number;
    items_en_attente: number;
    items_a_relancer: number;
    missions: Array<{
      mission_id: number;
      client: string;
      exercice: number;
      en_attente: number;
      recu: number;
      a_relancer: number;
      plus_ancienne_attente: string | null;
    }>;
  };
};

/** Réponse GET /api/v1/pilotage/supervision — supervision transverse. */
type SupervisionCabinet = {
  missions: Array<{
    mission_id: number;
    contribuable: string;
    exercice: number;
    statut: string;
    heures_totales: string;
    phases_completes: number;
    visas_restitution_complets: boolean;
    items_en_attente: number;
    items_a_relancer: number;
    alertes: string[];
  }>;
  synthese: {
    missions_actives: number;
    sans_aucun_visa: number;
    restitution_non_visee: number;
    heures_totales: string;
    items_a_relancer: number;
  };
};

/** Date ISO (aaaa-mm-jj) → jj/mm/aaaa ; valeur inattendue renvoyée telle quelle. */
function fmtDateFr(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso;
}

function useMobile(max = 720) {
  const [mobile, setMobile] = useState(
    () => window.matchMedia(`(max-width: ${max}px)`).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${max}px)`);
    const on = () => setMobile(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [max]);
  return mobile;
}

const SIDEBAR_COLLAPSED_KEY = "rf-sidebar-collapsed";

function lireSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

const SESSION_STORAGE_KEY = "rf-session";

/** Session persistée (localStorage) — restaurée au boot, nettoyée au logout / 401. */
function lireSessionStockee(): SessionAuth | null {
  try {
    const brut = localStorage.getItem(SESSION_STORAGE_KEY);
    if (!brut) return null;
    const s = JSON.parse(brut) as Partial<SessionAuth> | null;
    if (
      s &&
      typeof s.jeton === "string" &&
      s.jeton.length > 0 &&
      typeof s.tenant_id === "number" &&
      typeof s.email === "string" &&
      typeof s.tenant_denomination === "string" &&
      typeof s.role === "string"
    ) {
      return s as SessionAuth;
    }
  } catch {
    /* ignore */
  }
  return null;
}

/**
 * Deep-link applicatif écrit par la fiche client :
 * `#fiche-{id}-{overview|identite|pieces|risques|missions|dataroom}`.
 * `#fiche-{id}` et `#fiche-{id}-overview` restent valides (rétro-compat).
 */
function lireVueDeepLink(): { type: "fiche"; id: number } | null {
  try {
    const m = /^#fiche-(\d+)(?:-(overview|identite|pieces|risques|missions|dataroom))?$/.exec(
      window.location.hash || "",
    );
    if (m) {
      const id = Number(m[1]);
      if (Number.isFinite(id) && id > 0) return { type: "fiche", id };
    }
  } catch {
    /* ignore */
  }
  return null;
}

type AuthTab = "conn" | "prov" | "invite";

/** Deep-links auth : mail invitation (`?invitation=`) ou CTA inscription (`?inscription`). */
function lireAuthDeepLink(): { tab: AuthTab; inviteToken: string } {
  try {
    const params = new URLSearchParams(window.location.search);
    const hash = (window.location.hash || "").replace(/^#/, "");
    const inviteToken = (
      params.get("invitation") ||
      params.get("invite") ||
      params.get("token") ||
      ""
    ).trim();
    if (inviteToken.length >= 10) {
      return { tab: "invite", inviteToken };
    }
    const tabParam = (params.get("tab") || "").toLowerCase();
    const veutInscription =
      params.has("inscription") ||
      hash === "inscription" ||
      tabParam === "inscription" ||
      tabParam === "creer" ||
      tabParam === "prov";
    if (veutInscription) {
      return { tab: "prov", inviteToken: "" };
    }
  } catch {
    /* ignore */
  }
  return { tab: "conn", inviteToken: "" };
}

/** Responsable de mission (POST /missions/{id}/responsable). */
type ResponsableMissionOut = {
  mission_id: number;
  responsable_email: string | null;
};

function ResponsableMissionVue({
  missionId,
  jeton,
  estLecteur,
}: {
  missionId: number;
  jeton?: string | null;
  estLecteur: boolean;
}) {
  const [courant, setCourant] = useState<string | null>(null);
  const [choix, setChoix] = useState("");
  const [membres, setMembres] = useState<
    Array<{ id: number; email: string; actif: boolean }>
  >([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ txt: string; err: boolean } | null>(null);

  useEffect(() => {
    if (!jeton) return;
    let annule = false;
    void (async () => {
      try {
        const r = await api<ResponsableMissionOut>(
          `/api/v1/missions/${missionId}/responsable`,
          { jeton },
        );
        if (!annule) {
          setCourant(r.responsable_email);
          setChoix(r.responsable_email ?? "");
        }
      } catch {
        /* mission sans responsable ou migration absente — non bloquant */
      }
      try {
        const us = await api<
          Array<{ id: number; email: string; actif: boolean }>
        >("/api/v1/collaborateurs", { jeton });
        if (!annule) setMembres(us);
      } catch {
        /* lecteur (403) — retombe sur la saisie libre de l'email */
      }
    })();
    return () => {
      annule = true;
    };
  }, [jeton, missionId]);

  async function affecter(email: string | null) {
    if (!jeton || busy) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<
        ResponsableMissionOut & { precedent: string | null }
      >(`/api/v1/missions/${missionId}/responsable`, {
        method: "POST",
        jeton,
        json: { email },
      });
      setCourant(r.responsable_email);
      setChoix(r.responsable_email ?? "");
      setMsg({
        txt: r.responsable_email
          ? `Responsable affecté : ${r.responsable_email}.`
          : "Mission désaffectée — plus de responsable.",
        err: false,
      });
    } catch (e) {
      setMsg({
        txt:
          e instanceof ApiError
            ? e.message
            : "Affectation impossible pour le moment.",
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel dense resp-zone" aria-label="Responsable de mission">
      <div className="resp-head">
        <h3 className="resp-title">Responsable de mission</h3>
        <p className="resp-sub">
          {courant ? (
            <>
              Actuellement : <strong>{courant}</strong>
            </>
          ) : (
            "Aucun responsable affecté pour l'instant."
          )}
        </p>
      </div>
      {!estLecteur && (
        <div className="resp-form">
          {membres.length > 0 ? (
            <select
              className="resp-select"
              value={choix}
              disabled={busy}
              aria-label="Choisir le responsable de la mission"
              onChange={(e) => setChoix(e.target.value)}
            >
              <option value="">— Non affecté —</option>
              {membres.map((m) => (
                <option key={m.id} value={m.email}>
                  {m.email}
                </option>
              ))}
            </select>
          ) : (
            <input
              type="email"
              className="resp-input"
              placeholder="prenom.nom@cabinet.ci"
              value={choix}
              disabled={busy}
              aria-label="Email du responsable de la mission"
              onChange={(e) => setChoix(e.target.value)}
            />
          )}
          <button
            type="button"
            className="btn btn-primary btn-sm resp-btn"
            disabled={busy || (choix.trim() || null) === courant}
            onClick={() => void affecter(choix.trim() || null)}
          >
            {busy ? "Affectation…" : "Affecter"}
          </button>
        </div>
      )}
      {msg && (
        <p className={`status resp-status${msg.err ? " err" : ""}`} role="status">
          {msg.txt}
        </p>
      )}
    </section>
  );
}

/** Charge du cabinet (GET /cabinet/charge) — consultatif. */
type ChargeCabinetOut = {
  items: Array<{
    responsable: string;
    nb_missions: number;
    nb_en_cours: number;
    nb_cadrage: number;
  }>;
  synthese: {
    missions_actives: number;
    responsables: number;
    non_affectees: number;
  };
  note: string;
};

function ChargeCabinetVue({ jeton }: { jeton?: string | null }) {
  const [vue, setVue] = useState<ChargeCabinetOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!jeton) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<ChargeCabinetOut>("/api/v1/cabinet/charge", {
          jeton,
        });
        if (!annule) setVue(out ?? null);
      } catch {
        if (!annule) {
          setVue(null);
          setErr("Charge du cabinet indisponible pour le moment.");
        }
      } finally {
        if (!annule) setBusy(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, [jeton]);

  return (
    <section className="chargecab-zone" aria-label="Charge du cabinet">
      <div className="chargecab-head">
        <div>
          <h3 className="chargecab-title">Charge du cabinet</h3>
          <p className="chargecab-sub">
            Répartition des missions non clôturées par responsable — pour
            équilibrer la charge entre collaborateurs.
          </p>
        </div>
      </div>
      <article className="panel dense chargecab-card">
        {busy && !vue && (
          <p className="chargecab-vide">Chargement de la charge du cabinet…</p>
        )}
        {err && !busy && <p className="chargecab-err">{err}</p>}
        {vue && (
          <>
            <div className="chargecab-synthese">
              <span className="chargecab-chip">
                <strong>{vue.synthese.missions_actives}</strong> mission
                {vue.synthese.missions_actives > 1 ? "s" : ""} active
                {vue.synthese.missions_actives > 1 ? "s" : ""}
              </span>
              <span className="chargecab-chip">
                <strong>{vue.synthese.responsables}</strong> responsable
                {vue.synthese.responsables > 1 ? "s" : ""}
              </span>
              {vue.synthese.non_affectees > 0 && (
                <span className="chargecab-chip ancienne">
                  <strong>{vue.synthese.non_affectees}</strong> non affectée
                  {vue.synthese.non_affectees > 1 ? "s" : ""}
                </span>
              )}
            </div>
            {!vue.items.length && (
              <p className="chargecab-vide">
                Aucune mission active : la charge du cabinet est vide.
              </p>
            )}
            {vue.items.length > 0 && (
              <div className="balance-table-wrap">
                <table className="balance-table chargecab-table">
                  <thead>
                    <tr>
                      <th>Responsable</th>
                      <th>Missions</th>
                      <th>En cours</th>
                      <th>Cadrage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {vue.items.map((it) => (
                      <tr key={it.responsable}>
                        <td>
                          {it.responsable === "non affecté" ? (
                            <em>{it.responsable}</em>
                          ) : (
                            it.responsable
                          )}
                        </td>
                        <td className="num">{it.nb_missions}</td>
                        <td className="num">{it.nb_en_cours}</td>
                        <td className="num">{it.nb_cadrage}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {vue.note && <p className="chargecab-note">{vue.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}

export function App() {
  const mobile = useMobile();
  const [session, setSession] = useState<SessionAuth | null>(lireSessionStockee);
  const [vue, setVue] = useState<Vue>("dashboard");
  const [authDeep] = useState(lireAuthDeepLink);
  const [authTab, setAuthTab] = useState<AuthTab>(authDeep.tab);
  const [authStatus, setAuthStatus] = useState<{ msg: string; err: boolean } | null>(
    null,
  );
  const [inviteAcceptToken, setInviteAcceptToken] = useState(authDeep.inviteToken);
  const [inviteAcceptMdp, setInviteAcceptMdp] = useState("");
  const [inviteAcceptMdp2, setInviteAcceptMdp2] = useState("");
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(1);
  const [isDev, setIsDev] = useState(false);
  const [demoCreds, setDemoCreds] = useState<{
    email: string;
    mot_de_passe: string;
    rejouer: string;
  } | null>(null);

  const [emailConn, setEmailConn] = useState("");
  const [mdpConn, setMdpConn] = useState("");
  const [denom, setDenom] = useState("");
  const [emailProv, setEmailProv] = useState("");
  const [mdpProv, setMdpProv] = useState("");
  const [mdpProvConfirm, setMdpProvConfirm] = useState("");
  const [typeTenant, setTypeTenant] = useState<"cabinet" | "entreprise">(
    "cabinet",
  );
  const [provStep, setProvStep] = useState<1 | 2 | 3>(1);
  const [creerDemo, setCreerDemo] = useState(false);
  const [telephoneE164, setTelephoneE164] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [otpDebug, setOtpDebug] = useState<string | null>(null);
  const [jetonInscription, setJetonInscription] = useState<string | null>(null);
  const [onboarding, setOnboarding] = useState<{
    etapes: Record<string, boolean>;
    complete: boolean;
    progression: number;
    total: number;
  } | null>(null);
  const [onboardingMasque, setOnboardingMasque] = useState(false);

  const [contribNom, setContribNom] = useState("");
  const [contribNcc, setContribNcc] = useState("");
  const [contribForme, setContribForme] = useState<FormePersonne>("pm");
  const [contribRccm, setContribRccm] = useState("");
  const [contribDfe, setContribDfe] = useState("");
  const [contribSiege, setContribSiege] = useState("");
  const [contribCommune, setContribCommune] = useState("");
  const [contribCentreImpots, setContribCentreImpots] = useState("");
  const [contribCapital, setContribCapital] = useState("");
  const [contribMoisCloture, setContribMoisCloture] = useState("12");
  const [contribActivite, setContribActivite] = useState("");
  const [contribDateImmat, setContribDateImmat] = useState("");
  const [contribIdExistant, setContribIdExistant] = useState<number | null>(
    null,
  );
  const [piecesIdentiteClient, setPiecesIdentiteClient] = useState<
    PieceContribuable[]
  >([]);
  const [exercice, setExercice] = useState(2025);
  const [regime, setRegime] = useState("reel");
  const [forme, setForme] = useState("SA");
  const [secteur, setSecteur] = useState("");
  const [typeEntite, setTypeEntite] = useState("");
  const [crossBorder, setCrossBorder] = useState(false);
  const [typeEngagement, setTypeEngagement] = useState("");
  const [prescriptionConfirmee, setPrescriptionConfirmee] = useState(false);
  const [etapeRetour, setEtapeRetour] = useState<number | null>(null);
  const [missionCreee, setMissionCreee] = useState<{
    id: number;
    cid: number;
    exercice: number;
  } | null>(null);
  const [perimetreImpots, setPerimetreImpots] = useState<string[]>([]);
  const [exclusionsDeclarees, setExclusionsDeclarees] = useState("");
  const [seuilSignification, setSeuilSignification] = useState("");
  const [objectifsLibelles, setObjectifsLibelles] = useState<string[]>([""]);
  const [pointsOuverts, setPointsOuverts] = useState<
    Array<{
      id: number;
      texte: string;
      statut: string;
      mission_source_id?: number | null;
    }>
  >([]);
  const [resumeRisques, setResumeRisques] = useState<ResumeRisques | null>(
    null,
  );
  const [actionsRetard, setActionsRetard] = useState<
    Array<{
      id: number;
      risque_id: number;
      libelle: string;
      echeance: string | null;
      contribuable_id?: number | null;
      contribuable_denomination?: string | null;
      risque_libelle?: string | null;
    }>
  >([]);
  const [pilotage, setPilotage] = useState<PilotagePortefeuille | null>(null);
  const [supervision, setSupervision] = useState<SupervisionCabinet | null>(
    null,
  );
  const [balanceJson, setBalanceJson] = useState(BALANCE_DEMO);
  const [balanceFile, setBalanceFile] = useState<File | null>(null);
  const [balanceSource, setBalanceSource] = useState<"json" | "fichier">("json");
  const [balanceFichierAnalyse, setBalanceFichierAnalyse] =
    useState<BalanceAnalyse | null>(null);
  const [balanceDrag, setBalanceDrag] = useState(false);
  const [jeuBalanceId, setJeuBalanceId] = useState<string>("demo");
  const [sourceComptable, setSourceComptable] =
    useState<SourceComptableKind>("balance");
  const [sourceAltFile, setSourceAltFile] = useState<File | null>(null);
  const [sourceAltDrag, setSourceAltDrag] = useState(false);
  const [sourceDataroomOnglet, setSourceDataroomOnglet] = useState(false);
  const [sourceDataroomPiece, setSourceDataroomPiece] =
    useState<PieceTabulaire | null>(null);
  const [dataroomPieces, setDataroomPieces] = useState<PieceTabulaire[]>([]);
  const [dataroomEtat, setDataroomEtat] = useState<
    "pret" | "chargement" | "erreur"
  >("pret");
  const [piecesMission, setPiecesMission] = useState<PieceMission[]>([]);
  const [depotTypePiece, setDepotTypePiece] = useState<TypePieceApi>("autre");
  const [depotDrag, setDepotDrag] = useState(false);
  const [depotBusy, setDepotBusy] = useState(false);
  const [depotMsg, setDepotMsg] = useState<string | null>(null);
  const [depotErr, setDepotErr] = useState<string | null>(null);
  /** Une source a déjà été « figée » dans le wizard (fichier / JSON prêt). */
  const [sourceActiveFigee, setSourceActiveFigee] = useState(false);

  const [missionStatus, setMissionStatus] = useState<{
    msg: string;
    err: boolean;
  } | null>(null);
  const [restitution, setRestitution] = useState<Restitution | null>(null);
  const [missionId, setMissionId] = useState<number | null>(null);
  const [versionEpinglee, setVersionEpinglee] = useState<{
    id: number;
    libelle?: string | null;
  } | null>(null);
  const [auditJournal, setAuditJournal] = useState<AuditJournal | null>(null);

  const [clients, setClients] = useState<Contribuable[]>([]);
  const [clientDetail, setClientDetail] = useState<ContribuableDetail | null>(
    null,
  );
  const [clientEdit, setClientEdit] = useState<ClientEditState>(() =>
    etatInitialClientEdit("pm"),
  );
  const [missions, setMissions] = useState<MissionRow[]>([]);
  /** Nb de relances échues (badge sidebar « Tableau de bord ») — fetch léger au montage. */
  const [nbRelances, setNbRelances] = useState(0);
  const [quota, setQuota] = useState<QuotaResume | null>(null);
  const [invitations, setInvitations] = useState<
    Array<{ id: number; email: string; role: string; statut: string }>
  >([]);
  const [users, setUsers] = useState<
    Array<{ id: number; email: string; role: string; actif: boolean }>
  >([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"lecteur" | "reviseur" | "admin">(
    "lecteur",
  );
  const [equipeMsg, setEquipeMsg] = useState<{ msg: string; err: boolean } | null>(
    null,
  );
  const [inviteToken, setInviteToken] = useState<{
    email: string;
    token: string;
    emailEnvoi?: {
      statut?: string;
      mode?: string | null;
      outbox_id?: number | null;
      note?: string;
    };
  } | null>(null);
  const [emailOutbox, setEmailOutbox] = useState<{
    resend?: {
      resend_configure?: boolean;
      mode_sans_cle?: string | null;
      note?: string;
    };
    lignes?: Array<{
      id: number;
      destinataire: string;
      sujet: string;
      statut: string;
      dernier_erreur?: string | null;
      cree_le?: string;
    }>;
  } | null>(null);
  const [filtreExercice, setFiltreExercice] = useState("");
  const [filtreStatut, setFiltreStatut] = useState("");
  const [lienMsg, setLienMsg] = useState<string | null>(null);
  const [lienUrl, setLienUrl] = useState<string | null>(null);

  const estLecteur = session?.role === "lecteur";
  const estAdmin = session?.role === "admin";

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const sante = await api<{
          env?: string;
          demo?: {
            email?: string;
            mot_de_passe?: string;
            rejouer?: string;
            hint?: string;
          };
        }>("/sante");
        if (cancelled) return;
        const host = window.location.hostname;
        const local =
          host === "localhost" || host === "127.0.0.1" || host === "[::1]";
        /* Jamais hors localhost — credentials démo ne doivent pas fuiter en prod. */
        if (!local) {
          setIsDev(false);
          setDemoCreds(null);
          return;
        }
        const demo = sante.env === "dev";
        setIsDev(demo);
        if (demo) {
          const email = sante.demo?.email || "admin@demo.local";
          const mdp = sante.demo?.mot_de_passe || "demo-demo1";
          setDemoCreds({
            email,
            mot_de_passe: mdp,
            rejouer: sante.demo?.rejouer || "make demolot",
          });
          setDenom("Cabinet Démo");
          setEmailProv("");
          setMdpProv(mdp);
          setMdpProvConfirm(mdp);
          setCreerDemo(true);
          setContribNom("Société Démo CI");
          setContribNcc("CI-DEMO-0001");
          setContribForme("pm");
          setContribRccm("CI-ABJ-2020-B-12345");
          setContribDfe("");
          setContribSiege("Plateau, bd de la République");
          setContribCommune("Abidjan");
          setContribCentreImpots("CDI Plateau");
          setContribCapital("10000000");
          setContribActivite(composerActivite("services", "conseil"));
          setSecteur("Services — conseil");
          setForme("SA");
          setRegime("reel");
        }
      } catch {
        const host = window.location.hostname;
        if (
          !cancelled &&
          (host === "localhost" || host === "127.0.0.1" || host === "[::1]")
        ) {
          setIsDev(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function fillDemoCabinet() {
    const email = demoCreds?.email || "admin@demo.local";
    const mdp = demoCreds?.mot_de_passe || "demo-demo1";
    setEmailConn(email);
    setMdpConn(mdp);
  }

  function submitDemoCabinet() {
    const email = demoCreds?.email || "admin@demo.local";
    const mdp = demoCreds?.mot_de_passe || "demo-demo1";
    fillDemoCabinet();
    void connexion(undefined, { email, mot_de_passe: mdp });
  }

  async function chargerOnboarding(jeton: string) {
    try {
      const onb = await api<{
        etapes: Record<string, boolean>;
        complete: boolean;
        progression: number;
        total: number;
      }>("/api/v1/onboarding", { jeton });
      setOnboarding(onb);
    } catch {
      /* onboarding optionnel si migration absente */
    }
  }

  async function chargerDashboard(jeton: string) {
    const [c, m, q] = await Promise.all([
      api<Contribuable[]>("/api/v1/contribuables", { jeton }),
      api<MissionRow[]>("/api/v1/missions", { jeton }),
      api<QuotaResume>("/api/v1/quota", { jeton }),
    ]);
    setClients(c);
    setMissions(m);
    setQuota(q);
    await chargerOnboarding(jeton);
  }

  async function chargerEquipe(jeton: string) {
    if (!estAdmin && session?.role !== "admin") return;
    const [inv, us] = await Promise.all([
      api<typeof invitations>("/api/v1/invitations", { jeton }),
      api<typeof users>("/api/v1/utilisateurs", { jeton }),
    ]);
    setInvitations(inv);
    setUsers(us);
  }

  async function connexion(
    e?: FormEvent,
    override?: { email: string; mot_de_passe: string },
  ) {
    e?.preventDefault();
    setBusy(true);
    setAuthStatus(null);
    const email = override?.email ?? emailConn;
    const mot_de_passe = override?.mot_de_passe ?? mdpConn;
    try {
      const data = await api<{
        jeton: string;
        tenant_id: number;
        email: string;
        tenant_denomination: string;
        role: string;
      }>("/api/v1/auth/connexion", {
        method: "POST",
        json: { email, mot_de_passe },
      });
      const s: SessionAuth = {
        jeton: data.jeton,
        tenant_id: data.tenant_id,
        email: data.email,
        tenant_denomination: data.tenant_denomination,
        role: data.role,
      };
      setSession(s);
      setVue("dashboard");
      await chargerDashboard(s.jeton);
    } catch (err) {
      setAuthStatus({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function envoyerOtp(e?: FormEvent) {
    e?.preventDefault();
    setAuthStatus(null);
    if (!emailProv.trim() || !emailProv.includes("@")) {
      setAuthStatus({ msg: "Email administrateur invalide.", err: true });
      return;
    }
    setBusy(true);
    try {
      const data = await api<{
        email: string;
        otp_debug?: string | null;
        renvoye: boolean;
      }>("/api/v1/inscription/demarrer", {
        method: "POST",
        json: { email: emailProv.trim().toLowerCase() },
      });
      setOtpSent(true);
      setOtpDebug(data.otp_debug ?? null);
      setJetonInscription(null);
      setAuthStatus({
        msg: data.renvoye
          ? "Nouveau code envoyé à votre adresse email."
          : "Code envoyé — vérifiez votre boîte mail.",
        err: false,
      });
    } catch (err) {
      setAuthStatus({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function validerOtp(e?: FormEvent) {
    e?.preventDefault();
    setAuthStatus(null);
    if (otpCode.replace(/\s/g, "").length !== 6) {
      setAuthStatus({ msg: "Saisissez le code à 6 chiffres.", err: true });
      return;
    }
    if (!telephoneE164) {
      setAuthStatus({
        msg: "Indiquez un numéro de téléphone valide (indicatif pays).",
        err: true,
      });
      return;
    }
    setBusy(true);
    try {
      const data = await api<{ jeton_inscription: string; email: string }>(
        "/api/v1/inscription/verifier-otp",
        {
          method: "POST",
          json: {
            email: emailProv.trim().toLowerCase(),
            code: otpCode.replace(/\s/g, ""),
          },
        },
      );
      setJetonInscription(data.jeton_inscription);
      setProvStep(3);
      setAuthStatus({ msg: "Email vérifié.", err: false });
    } catch (err) {
      setAuthStatus({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function provisionner(e?: FormEvent) {
    e?.preventDefault();
    setAuthStatus(null);

    const nom = denom.trim();
    if (nom.length < 2) {
      setAuthStatus({ msg: "Indiquez le nom du cabinet ou de l’entreprise.", err: true });
      setProvStep(1);
      return;
    }
    if (!jetonInscription) {
      setAuthStatus({ msg: "Vérifiez d’abord votre email.", err: true });
      setProvStep(2);
      return;
    }
    if (mdpProv.length < 8) {
      setAuthStatus({
        msg: "Mot de passe trop court (minimum 8 caractères).",
        err: true,
      });
      return;
    }
    if (mdpProv !== mdpProvConfirm) {
      setAuthStatus({ msg: "Les mots de passe ne correspondent pas.", err: true });
      return;
    }
    if (!telephoneE164) {
      setAuthStatus({ msg: "Téléphone obligatoire.", err: true });
      setProvStep(2);
      return;
    }

    setBusy(true);
    try {
      const data = await api<{
        jeton: string;
        tenant_id: number;
        email_admin: string;
        tenant_denomination: string;
      }>("/api/v1/inscription/finaliser", {
        method: "POST",
        json: {
          jeton_inscription: jetonInscription,
          denomination: nom,
          type_tenant: typeTenant,
          palier: "standard",
          mot_de_passe: mdpProv,
          telephone: telephoneE164,
          creer_demo: isDev && creerDemo,
        },
      });
      setSession({
        jeton: data.jeton,
        tenant_id: data.tenant_id,
        email: data.email_admin,
        tenant_denomination: data.tenant_denomination,
        role: "admin",
      });
      setVue("dashboard");
      setOnboardingMasque(false);
      await chargerDashboard(data.jeton);
    } catch (err) {
      const raw = err instanceof Error ? err.message : String(err);
      let msg = raw;
      if (/jetable|temporaire/i.test(raw)) {
        msg = raw;
      } else if (/email deja pris|déjà associé/i.test(raw)) {
        msg =
          "Cet email est déjà utilisé. Connectez-vous ou choisissez une autre adresse.";
      } else if (/desactive|désactivé|403/i.test(raw)) {
        msg =
          "L’inscription publique est fermée. Contactez 2AàZ ou utilisez l’Admin billing.";
      }
      setAuthStatus({ msg, err: true });
    } finally {
      setBusy(false);
    }
  }

  function allerProvEtape2(e?: FormEvent) {
    e?.preventDefault();
    setAuthStatus(null);
    if (denom.trim().length < 2) {
      setAuthStatus({
        msg: "Indiquez le nom du cabinet ou de l’entreprise.",
        err: true,
      });
      return;
    }
    setProvStep(2);
  }

  function changerAuthTab(tab: "conn" | "prov") {
    setAuthTab(tab);
    setAuthStatus(null);
    if (tab === "prov") {
      setProvStep(1);
      setOtpSent(false);
      setOtpCode("");
      setOtpDebug(null);
      setJetonInscription(null);
    }
  }

  useEffect(() => {
    try {
      const deep = lireAuthDeepLink();
      if (deep.tab === "invite") {
        setInviteAcceptToken(deep.inviteToken);
        setAuthTab("invite");
      } else if (deep.tab === "prov") {
        setAuthTab("prov");
      }
      const params = new URLSearchParams(window.location.search);
      if (params.get("vue") === "facturation") {
        setVue("facturation");
      }
    } catch {
      /* ignore */
    }
  }, []);

  // Persistance session : sync localStorage (écrite à la connexion, purgée au logout).
  useEffect(() => {
    try {
      if (session) {
        localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
      } else {
        localStorage.removeItem(SESSION_STORAGE_KEY);
      }
    } catch {
      /* ignore */
    }
  }, [session]);

  // Profil cabinet (coordonnées réelles du tenant) — en-tête de la lettre de mission.
  const [cabinetProfil, setCabinetProfil] = useState<CabinetProfil | null>(
    null,
  );
  const chargerCabinetProfil = useCallback(async (jeton: string) => {
    try {
      const r = await api<{
        tenant: {
          siege_social?: string | null;
          commune?: string | null;
          ncc?: string | null;
          rccm?: string | null;
        };
        utilisateur: { email: string; telephone: string | null };
      }>("/api/v1/compte", { jeton });
      setCabinetProfil({
        siege_social: r.tenant.siege_social ?? null,
        commune: r.tenant.commune ?? null,
        ncc: r.tenant.ncc ?? null,
        rccm: r.tenant.rccm ?? null,
        email: r.utilisateur.email ?? null,
        telephone: r.utilisateur.telephone ?? null,
      });
    } catch {
      /* Coordonnées facultatives — l'en-tête retombe sur la dénomination seule. */
    }
  }, []);
  useEffect(() => {
    if (session?.jeton) void chargerCabinetProfil(session.jeton);
    else setCabinetProfil(null);
  }, [session?.jeton, chargerCabinetProfil]);

  // Badge sidebar : total des relances échues (fetch léger au montage, pas de polling).
  useEffect(() => {
    if (!session?.jeton) {
      setNbRelances(0);
      return;
    }
    let annule = false;
    void (async () => {
      try {
        const r = await api<{ total: number }>("/api/v1/cabinet/relances", {
          jeton: session.jeton,
        });
        if (!annule) setNbRelances(r?.total ?? 0);
      } catch {
        /* badge optionnel — silencieux si l'endpoint est indisponible */
      }
    })();
    return () => {
      annule = true;
    };
  }, [session?.jeton]);

  // Boot : vérifie la session restaurée via un appel léger, puis charge les données.
  useEffect(() => {
    const s = lireSessionStockee();
    if (!s) return;
    void (async () => {
      try {
        await api<QuotaResume>("/api/v1/quota", { jeton: s.jeton });
        await chargerDashboard(s.jeton);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          logout();
        }
      }
    })();
  }, []);

  // Jeton expiré/révoqué (401 signalé par api.ts) : nettoyer la session.
  useEffect(() => {
    if (!session) return;
    const onExpiree = () => {
      logout();
      setAuthStatus({ msg: "Session expirée — reconnectez-vous.", err: true });
    };
    window.addEventListener(AUTH_EXPIREE_EVENT, onExpiree);
    return () => window.removeEventListener(AUTH_EXPIREE_EVENT, onExpiree);
  }, [session]);

  // Deep-link #fiche-{id}-{section} : restaurer la vue après login / restauration.
  const deepLinkApplique = useRef(false);
  useEffect(() => {
    if (!session || deepLinkApplique.current) return;
    deepLinkApplique.current = true;
    const dl = lireVueDeepLink();
    if (dl?.type === "fiche") {
      void ouvrirClient(dl.id);
    }
  }, [session]);

  // Navigation à chaud sur hashchange (le sous-onglet de la fiche est géré par la fiche).
  useEffect(() => {
    if (!session) return;
    const onHash = () => {
      const dl = lireVueDeepLink();
      if (!dl) return;
      if (vue === "client" && clientDetail?.id === dl.id) return;
      void ouvrirClient(dl.id);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [session, vue, clientDetail?.id]);

  useEffect(() => {
    if (!session?.jeton || contribIdExistant == null) {
      setPointsOuverts([]);
      setResumeRisques(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const list = await api<
          Array<{
            id: number;
            texte: string;
            statut: string;
            mission_source_id?: number | null;
          }>
        >(
          `/api/v1/points-ouverts?contribuable_id=${contribIdExistant}&statut=ouvert`,
          { jeton: session.jeton },
        );
        if (!cancelled) setPointsOuverts(list);
      } catch {
        if (!cancelled) setPointsOuverts([]);
      }
      try {
        const resume = await api<ResumeRisques>(
          `/api/v1/contribuables/${contribIdExistant}/risques/resume`,
          { jeton: session.jeton },
        );
        if (!cancelled) setResumeRisques(resume);
      } catch {
        if (!cancelled) setResumeRisques(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session?.jeton, contribIdExistant]);

  useEffect(() => {
    if (!session?.jeton || vue !== "dashboard") {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const list = await api<
          Array<{
            id: number;
            risque_id: number;
            libelle: string;
            echeance: string | null;
            contribuable_id?: number | null;
            contribuable_denomination?: string | null;
            risque_libelle?: string | null;
          }>
        >("/api/v1/actions-risque/retards", { jeton: session.jeton });
        if (!cancelled) setActionsRetard(Array.isArray(list) ? list : []);
      } catch {
        if (!cancelled) setActionsRetard([]);
      }
      try {
        const p = await api<PilotagePortefeuille>("/api/v1/pilotage", {
          jeton: session.jeton,
        });
        if (!cancelled) setPilotage(p);
      } catch {
        if (!cancelled) setPilotage(null);
      }
      try {
        const s = await api<SupervisionCabinet>(
          "/api/v1/pilotage/supervision",
          { jeton: session.jeton },
        );
        if (!cancelled) setSupervision(s);
      } catch {
        if (!cancelled) setSupervision(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session?.jeton, vue]);

  useEffect(() => {
    if (!session?.jeton || contribIdExistant == null) {
      setPiecesIdentiteClient([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const liste = await api<PieceContribuable[]>(
          `/api/v1/pieces-contribuable?contribuable_id=${contribIdExistant}`,
          { jeton: session.jeton },
        );
        if (!cancelled) setPiecesIdentiteClient(liste);
      } catch {
        if (!cancelled) setPiecesIdentiteClient([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session?.jeton, contribIdExistant]);

  useEffect(() => {
    setSourceDataroomPiece(null);
    if (!session?.jeton || contribIdExistant == null) {
      setDataroomPieces([]);
      setDataroomEtat("pret");
      return;
    }
    let cancelled = false;
    setDataroomEtat("chargement");
    void (async () => {
      try {
        const liste = await api<PieceTabulaire[]>(
          `/api/v1/contribuables/${contribIdExistant}/pieces-tabulaires`,
          { jeton: session.jeton },
        );
        if (!cancelled) {
          setDataroomPieces(Array.isArray(liste) ? liste : []);
          setDataroomEtat("pret");
        }
      } catch {
        if (!cancelled) {
          setDataroomPieces([]);
          setDataroomEtat("erreur");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session?.jeton, contribIdExistant]);

  /* Data room mission : liste des pièces dès l'arrivée à l'étape Sources. */
  useEffect(() => {
    if (!session?.jeton || missionId == null) {
      setPiecesMission([]);
      return;
    }
    if (step !== 2) return;
    let cancelled = false;
    void (async () => {
      try {
        const liste = await api<PieceMission[]>(
          `/api/v1/missions/${missionId}/pieces`,
          { jeton: session.jeton },
        );
        if (!cancelled) setPiecesMission(Array.isArray(liste) ? liste : []);
      } catch {
        if (!cancelled) setPiecesMission([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session?.jeton, missionId, step]);

  async function rafraichirRestitution() {
    if (!session || !missionId) return;
    try {
      const rest = await api<Restitution>(
        `/api/v1/missions/${missionId}/restitution`,
        { jeton: session.jeton },
      );
      setRestitution(rest);
    } catch (err) {
      setMissionStatus({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    }
  }
  function logout() {
    deepLinkApplique.current = false;
    try {
      localStorage.removeItem(SESSION_STORAGE_KEY);
    } catch {
      /* ignore */
    }
    setSession(null);
    setRestitution(null);
    setMissionId(null);
    setAuditJournal(null);
    setMissionStatus(null);
    setStep(1);
    setAuthTab("conn");
    setVue("dashboard");
  }

  function resetMission() {
    setRestitution(null);
    setMissionId(null);
    setVersionEpinglee(null);
    setAuditJournal(null);
    setMissionStatus(null);
    setStep(1);
    setLienMsg(null);
    setLienUrl(null);
    setContribIdExistant(null);
    setPiecesIdentiteClient([]);
    setPointsOuverts([]);
    setSourceComptable("balance");
    setSourceAltFile(null);
    setSourceAltDrag(false);
    setSourceDataroomOnglet(false);
    setSourceDataroomPiece(null);
    setPiecesMission([]);
    setDepotTypePiece("autre");
    setDepotDrag(false);
    setDepotBusy(false);
    setDepotMsg(null);
    setDepotErr(null);
    setSourceActiveFigee(false);
    setTypeEngagement("");
    setPrescriptionConfirmee(false);
    setEtapeRetour(null);
    setMissionCreee(null);
    setPerimetreImpots([]);
    setExclusionsDeclarees("");
    setSeuilSignification("");
  }

  const identiteCourante = useMemo(
    () => ({
      denomination: contribNom,
      ncc: contribNcc,
      forme: contribForme,
      rccm: contribRccm,
      dfe: contribDfe,
      regime_fiscal: regime,
      forme_juridique: contribForme === "pp" ? "EI" : forme,
      siege_social: contribSiege,
      commune: contribCommune,
      centre_impots: contribCentreImpots,
      capital_social: contribCapital,
      mois_cloture: contribMoisCloture,
      activite_principale: contribActivite,
      date_immatriculation: contribDateImmat,
    }),
    [
      contribNom,
      contribNcc,
      contribForme,
      contribRccm,
      contribDfe,
      regime,
      forme,
      contribSiege,
      contribCommune,
      contribCentreImpots,
      contribCapital,
      contribMoisCloture,
      contribActivite,
      contribDateImmat,
    ],
  );

  const completude = useMemo(
    () => completudeIdentite(identiteCourante),
    [identiteCourante],
  );

  const apiMin = useMemo(
    () => identiteApiMinimale(identiteCourante),
    [identiteCourante],
  );

  /** C1a — nouveau contribuable dont le NCC/RCCM appartient déjà au portefeuille. */
  const conflitFiche = useMemo(() => {
    if (contribIdExistant != null || !clients.length) return null;
    const norm = (v?: string | null) => (v ?? "").trim().toUpperCase();
    const ncc = norm(contribNcc);
    const rccm = contribForme === "pm" ? norm(contribRccm) : "";
    for (const c of clients) {
      if (ncc && norm(c.ncc) === ncc) {
        return { champ: "NCC", valeur: contribNcc.trim(), client: c };
      }
      if (rccm && norm(c.rccm) === rccm) {
        return { champ: "RCCM", valeur: contribRccm.trim(), client: c };
      }
    }
    return null;
  }, [clients, contribIdExistant, contribNcc, contribRccm, contribForme]);

  const anneeCourante = new Date().getFullYear();
  const exerciceFutur = Number(exercice) > anneeCourante;
  const exercicePrescrit =
    !exerciceFutur && Number(exercice) < anneeCourante - 3;

  const balanceAnalyseJson = useMemo(
    () => analyserBalanceJson(balanceJson),
    [balanceJson],
  );

  const balanceAnalyseActive: BalanceAnalyse | null =
    sourceComptable !== "balance" || sourceDataroomOnglet
      ? null
      : balanceSource === "fichier"
        ? balanceFichierAnalyse
        : balanceAnalyseJson;

  const balanceExcelSeul =
    sourceComptable === "balance" &&
    !sourceDataroomOnglet &&
    balanceSource === "fichier" &&
    !!balanceFile &&
    /\.(xlsx|xlsm)$/i.test(balanceFile.name);

  const sourceMeta =
    SOURCES_COMPTABLES.find((s) => s.id === sourceComptable) ??
    SOURCES_COMPTABLES[0];

  const sourcePret = sourceDataroomOnglet
    ? !!sourceDataroomPiece
    : sourceComptable === "balance"
      ? balanceSource === "fichier"
        ? !!balanceFile &&
          (balanceExcelSeul || (balanceFichierAnalyse?.ok ?? false))
        : balanceAnalyseJson.ok
      : !!sourceAltFile;

  const peutLancerRevue = !busy && !quota?.bloque && sourcePret;

  const checklistControleur: ChecklistItem[] = useMemo(() => {
    const regimeLbl =
      REGIMES_FISCAUX.find((r) => r.value === regime)?.label ?? regime;
    let balanceDetail: string;
    if (sourceDataroomOnglet) {
      balanceDetail = sourceDataroomPiece
        ? `Pièce Data Room « ${sourceDataroomPiece.nom_fichier} » — import via /source-depuis-piece`
        : "Choisir une pièce comptable au Data Room du client";
    } else if (sourceComptable === "balance") {
      if (balanceExcelSeul) {
        balanceDetail = `Excel « ${balanceFile?.name ?? "—"} » — contrôle d’équilibre côté serveur`;
      } else if (balanceAnalyseActive?.ok) {
        balanceDetail = `${balanceAnalyseActive.nbLignes} comptes · ${
          balanceAnalyseActive.equilibre ? "équilibrée" : "déséquilibrée"
        }${balanceAnalyseActive.fictif ? " · FICTIF" : ""}`;
      } else {
        balanceDetail =
          balanceAnalyseActive?.erreurs[0] ??
          "Balance incomplete ou invalide";
      }
    } else {
      balanceDetail = sourceAltFile
        ? `Fichier « ${sourceAltFile.name} » prêt pour /${sourceMeta.route}`
        : `Déposer un fichier ${sourceMeta.short}`;
    }
    return checklistControleurAvantLancement({
      identiteComplet: completude.complet,
      identiteDetail: completude.complet
        ? `${contribNom || "—"} · ${regimeLbl} · identité ${completude.ok}/${completude.total}`
        : `Manque : ${completude.manquants.join(", ") || "champs identité"}`,
      exercice: Number(exercice),
      balancePret: sourcePret,
      balanceDetail,
      balanceFictif:
        sourceComptable === "balance" && !!balanceAnalyseActive?.fictif,
      quotaBloque: !!quota?.bloque,
      quotaDetail: quota
        ? `${quota.missions_utilisees}/${quota.missions_incluses} missions utilisées${
            quota.bloque ? " — création bloquée" : ""
          }`
        : "Quota non chargé — vérifié à la création",
      sourceLabel: sourceMeta.label,
    });
  }, [
    balanceAnalyseActive,
    balanceExcelSeul,
    balanceFile?.name,
    completude,
    contribNom,
    exercice,
    quota,
    regime,
    sourceAltFile,
    sourceComptable,
    sourceDataroomOnglet,
    sourceDataroomPiece,
    sourceMeta.label,
    sourceMeta.route,
    sourceMeta.short,
    sourcePret,
  ]);

  function chargerJeuBalance(id: string) {
    const jeu = JEUX_BALANCE.find((j) => j.id === id);
    if (!jeu) return;
    if (
      sourceActiveFigee &&
      sourceComptable !== "balance" &&
      !window.confirm(
        `Remplacer la source active « ${sourceMeta.label} » par la Balance SYSCOHADA ?\n\n` +
          "Les soldes seront recalculés uniquement depuis cette nouvelle source — pas de fusion.",
      )
    ) {
      return;
    }
    setJeuBalanceId(id);
    setBalanceJson(jeu.json);
    setBalanceFile(null);
    setBalanceFichierAnalyse(null);
    setBalanceSource("json");
    setSourceComptable("balance");
    setSourceAltFile(null);
    setSourceDataroomOnglet(false);
    setSourceActiveFigee(true);
  }

  function lireFichierBalance(file: File | null) {
    setBalanceFile(file);
    setBalanceFichierAnalyse(null);
    if (!file) return;
    setBalanceSource("fichier");
    setSourceComptable("balance");
    setSourceAltFile(null);
    setSourceDataroomOnglet(false);
    setSourceActiveFigee(true);
    const nom = file.name.toLowerCase();
    if (nom.endsWith(".xlsx") || nom.endsWith(".xlsm")) {
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const texte = String(reader.result ?? "");
      if (nom.endsWith(".json")) {
        const a = analyserBalanceJson(texte);
        setBalanceFichierAnalyse(a);
        if (a.ok) setBalanceJson(texte);
      } else {
        setBalanceFichierAnalyse(analyserBalanceCsv(texte));
      }
    };
    reader.readAsText(file);
  }

  function sourceDejaDefinie(kind: SourceComptableKind): boolean {
    if (!sourceActiveFigee && !sourcePret) return false;
    if (kind === sourceComptable) return false;
    return sourcePret || sourceActiveFigee;
  }

  function choisirSourceComptable(kind: SourceComptableKind) {
    if (kind === sourceComptable) return;
    const meta = SOURCES_COMPTABLES.find((s) => s.id === kind);
    if (sourceDejaDefinie(kind)) {
      const ok = window.confirm(
        `Changer la source active ?\n\n` +
          `Actuelle : ${sourceMeta.label}\n` +
          `Nouvelle : ${meta?.label ?? kind}\n\n` +
          "Une seule source alimente solde_compte. Le changement remplace les soldes — " +
          "les autres fichiers restent des annexes, sans fusion silencieuse.",
      );
      if (!ok) return;
    }
    setSourceComptable(kind);
    if (kind !== "balance") {
      setBalanceSource("fichier");
      setSourceAltFile(null);
    } else {
      setSourceAltFile(null);
    }
  }

  function lireFichierSourceAlt(file: File | null) {
    setSourceAltFile(file);
    if (file) {
      setSourceDataroomOnglet(false);
      setSourceActiveFigee(true);
    }
  }

  function utiliserPieceDataroom(p: PieceTabulaire) {
    setSourceDataroomPiece(p);
    setBalanceFile(null);
    setBalanceFichierAnalyse(null);
    setSourceAltFile(null);
    setSourceActiveFigee(true);
    if (p.format === "fec") {
      setSourceComptable("fec");
    } else if (p.format === "xlsx" || sourceComptable === "fec") {
      setSourceComptable("balance");
    }
  }

  /** Recharge la liste des pièces de la mission (data room). */
  async function rechargerPiecesMission() {
    if (!session || !missionId) return;
    try {
      const liste = await api<PieceMission[]>(
        `/api/v1/missions/${missionId}/pieces`,
        { jeton: session.jeton },
      );
      setPiecesMission(Array.isArray(liste) ? liste : []);
    } catch {
      /* liste conservée en l'état */
    }
  }

  /**
   * Dépose une ou plusieurs pièces dans la data room de la mission — même
   * pipeline que le panneau « Sources & data room » du poste de travail
   * (POST multipart /missions/{id}/pieces, champ type_piece).
   */
  async function deposerPiecesMission(fichiers: FileList | File[] | null) {
    if (!fichiers || depotBusy) return;
    const liste = Array.from(fichiers);
    if (!liste.length) return;
    if (!session || !missionId) return;
    setDepotBusy(true);
    setDepotMsg(null);
    setDepotErr(null);
    let envoyees = 0;
    let derniereErreur: string | null = null;
    for (const fichier of liste) {
      try {
        await apiUpload<PieceMission>(
          `/api/v1/missions/${missionId}/pieces`,
          fichier,
          session.jeton,
          { type_piece: depotTypePiece },
        );
        envoyees += 1;
      } catch (e) {
        derniereErreur = e instanceof Error ? e.message : String(e);
      }
    }
    if (envoyees > 0) {
      setDepotMsg(
        envoyees === 1
          ? "1 pièce déposée dans la data room."
          : `${envoyees} pièces déposées dans la data room.`,
      );
      await rechargerPiecesMission();
      // Capacité existante conservée : une balance déposée alimente aussi la
      // section « Source active » (analyse locale + import au lancement) tant
      // qu'aucune source n'a été préparée.
      if (depotTypePiece === "balance" && !sourcePret) {
        const premiere = liste.find((f) =>
          /\.(csv|tsv|txt|json|xlsx|xlsm)$/i.test(f.name),
        );
        if (premiere) lireFichierBalance(premiere);
      }
    }
    if (derniereErreur) {
      setDepotErr(
        envoyees > 0
          ? `Certaines pièces ont été refusées : ${derniereErreur}`
          : `Dépôt impossible : ${derniereErreur}`,
      );
    }
    setDepotBusy(false);
  }

  /**
   * Parcours non bloquant : ouvre l'étape Résultat même sans pièce ni revue
   * exécutée. Si la mission a déjà une restitution, on la recharge.
   */
  async function passerRestitution() {
    setStep(3);
    if (restitution) return;
    if (session && missionId) {
      try {
        const rest = await api<Restitution>(
          `/api/v1/missions/${missionId}/restitution`,
          { jeton: session.jeton },
        );
        setRestitution(rest);
        if (rest.version_referentiel_id != null) {
          setVersionEpinglee({
            id: rest.version_referentiel_id,
            libelle: rest.version_referentiel_libelle,
          });
        }
        return;
      } catch {
        /* pas encore de revue exécutée — message doux ci-dessous */
      }
    }
    setMissionStatus({
      msg:
        "Pas encore de revue exécutée — vous pourrez ajouter des sources à " +
        "tout moment (data room de l'étape Sources ou poste de travail) " +
        "puis lancer la revue.",
      err: false,
    });
  }

  function chargerContribuableDansWizard(c: Contribuable) {
    setContribIdExistant(c.id);
    setContribNom(c.denomination);
    setContribNcc(c.ncc ?? "");
    setContribForme(c.forme === "pp" ? "pp" : "pm");
    setContribRccm(c.rccm ?? "");
    setContribDfe(c.dfe ?? "");
    setContribSiege(c.siege_social ?? "");
    setContribCommune(c.commune ?? "");
    setContribCentreImpots(c.centre_impots ?? "");
    setContribCapital(
      c.capital_social != null && c.capital_social !== ""
        ? String(c.capital_social)
        : "",
    );
    setContribMoisCloture(
      c.mois_cloture != null ? String(c.mois_cloture) : "12",
    );
    setContribActivite(c.activite_principale ?? "");
    setContribDateImmat(
      c.date_immatriculation ? String(c.date_immatriculation).slice(0, 10) : "",
    );
    if (c.regime_fiscal) setRegime(c.regime_fiscal);
    if (c.forme_juridique) setForme(c.forme_juridique);
    else if (c.forme === "pp") setForme("EI");
    if (c.activite_principale?.trim()) {
      setSecteur(c.activite_principale.trim());
    }
  }

  /** Cadrage — repart sur une fiche contribuable vierge. */
  function reinitialiserClientCadrage() {
    setContribIdExistant(null);
    setContribNom("");
    setContribNcc("");
    setContribRccm("");
    setContribDfe("");
    setContribSiege("");
    setContribCommune("");
    setContribCentreImpots("");
    setContribCapital("");
    setContribMoisCloture("12");
    setContribActivite("");
    setContribDateImmat("");
    setSecteur("");
  }

  async function aller(
    v: Vue,
    opts?: { filtreStatut?: string; filtreExercice?: string },
  ) {
    if (!session) return;
    setVue(v);
    if (v === "nouvelle") {
      resetMission();
      return;
    }
    const statutFiltre =
      opts?.filtreStatut !== undefined ? opts.filtreStatut : filtreStatut;
    const exerciceFiltre =
      opts?.filtreExercice !== undefined ? opts.filtreExercice : filtreExercice;
    if (opts?.filtreStatut !== undefined) setFiltreStatut(opts.filtreStatut);
    if (opts?.filtreExercice !== undefined)
      setFiltreExercice(opts.filtreExercice);
    setBusy(true);
    try {
      if (v === "dashboard" || v === "clients" || v === "missions") {
        await chargerDashboard(session.jeton);
      }
      if (v === "equipe" && session.role === "admin") {
        await chargerEquipe(session.jeton);
        await chargerEmailOutbox(session.jeton);
      }
      if (v === "missions") {
        const qs = new URLSearchParams();
        if (exerciceFiltre) qs.set("exercice", exerciceFiltre);
        if (statutFiltre) qs.set("statut", statutFiltre);
        const path = qs.toString()
          ? `/api/v1/missions?${qs}`
          : "/api/v1/missions";
        setMissions(await api<MissionRow[]>(path, { jeton: session.jeton }));
      }
    } catch (err) {
      setMissionStatus({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  /** Validations bloquantes du cadrage (client + exercice + engagement). */
  function validerCadrage() {
    if (contribIdExistant == null && !apiMin.ok) {
      throw new Error(
        `Identité minimale incomplète : ${apiMin.manquants.join(", ")}.`,
      );
    }
    if (conflitFiche) {
      throw new Error(
        `Cette entreprise existe déjà : « ${conflitFiche.client.denomination} » (#${conflitFiche.client.id}) — utilisez la fiche existante du portefeuille.`,
      );
    }
    if (!typeEngagement) {
      throw new Error(
        "Type d'engagement non choisi — sélectionnez-le au cadrage.",
      );
    }
    if (exerciceFutur) {
      throw new Error(
        `L'exercice ${exercice} n'est pas encore clos — une revue fiscale porte sur un exercice achevé.`,
      );
    }
    if (exercicePrescrit && !prescriptionConfirmee) {
      throw new Error(
        `L'exercice ${exercice} est a priori prescrit — confirmez la revue volontaire au cadrage.`,
      );
    }
  }

  /** Crée ou met à jour le contribuable de la fiche courante → id. */
  async function assurerContribuable(jeton: string): Promise<number> {
    const payloadIdentite = {
      denomination: contribNom.trim(),
      ncc: contribNcc.trim(),
      forme: contribForme,
      rccm: contribForme === "pm" ? contribRccm.trim() : null,
      dfe: contribForme === "pm" ? contribDfe.trim() || null : null,
      regime_fiscal: regime,
      forme_juridique: contribForme === "pp" ? "EI" : forme,
      siege_social: contribSiege.trim() || null,
      commune: contribCommune.trim() || null,
      centre_impots: contribCentreImpots.trim() || null,
      capital_social:
        contribForme === "pm" && contribCapital.trim()
          ? Number(contribCapital.replace(/\s/g, "").replace(",", "."))
          : null,
      mois_cloture: Number(contribMoisCloture) || 12,
      activite_principale: contribActivite.trim() || null,
      date_immatriculation: contribDateImmat.trim() || null,
    };
    if (contribIdExistant) {
      setMissionStatus({ msg: "Mise à jour du contribuable…", err: false });
      await api(`/api/v1/contribuables/${contribIdExistant}`, {
        method: "PATCH",
        jeton,
        json: payloadIdentite,
      });
      return contribIdExistant;
    }
    setMissionStatus({ msg: "Création du contribuable…", err: false });
    const contrib = await api<{ id: number }>("/api/v1/contribuables", {
      method: "POST",
      jeton,
      json: payloadIdentite,
    });
    setContribIdExistant(contrib.id);
    return contrib.id;
  }

  /** Crée la mission (ou réutilise celle d'une tentative précédente). */
  async function assurerMission(
    jeton: string,
    cid: number,
  ): Promise<{ id: number; version_referentiel_id: number }> {
    if (
      missionCreee &&
      missionCreee.cid === cid &&
      missionCreee.exercice === Number(exercice)
    ) {
      // Mission déjà créée lors d'une tentative précédente — on la réutilise
      // au lieu de créer un doublon (la contrainte serveur le refuserait).
      setMissionStatus({
        msg: `Reprise de la mission #${missionCreee.id} déjà créée…`,
        err: false,
      });
      return {
        id: missionCreee.id,
        version_referentiel_id: versionEpinglee?.id ?? 0,
      };
    }
    setMissionStatus({ msg: "Création de la mission…", err: false });
    const profil: Record<string, string | boolean> = {
      regime,
      forme_juridique: contribForme === "pp" ? "EI" : forme,
    };
    const secteurProfil = contribActivite.trim() || secteur.trim();
    if (secteurProfil) profil.secteur = secteurProfil;
    if (typeEntite.trim()) profil.type_entite = typeEntite.trim();
    if (crossBorder) profil.cross_border = true;

    const mission = await api<{ id: number; version_referentiel_id: number }>(
      "/api/v1/missions",
      {
        method: "POST",
        jeton,
        json: {
          contribuable_id: cid,
          exercice: Number(exercice),
          profil,
          type_engagement: typeEngagement,
          perimetre_impots: perimetreImpots.length > 0 ? perimetreImpots : null,
          exclusions_declarees: exclusionsDeclarees.trim() || null,
          seuil_signification: seuilSignification.trim()
            ? Number(seuilSignification)
            : null,
          objectifs: objectifsLibelles
            .map((l) => l.trim())
            .filter(Boolean)
            .map((libelle) => ({ libelle })),
        },
      },
    );
    setMissionCreee({ id: mission.id, cid, exercice: Number(exercice) });
    setVersionEpinglee({ id: mission.version_referentiel_id });
    return mission;
  }

  /** Erreurs de création — 403 quota, 409 doublon, 400 validation. */
  function messageErreurCreation(err: unknown): string {
    let msg = err instanceof Error ? err.message : String(err);
    if (err instanceof ApiError && err.status === 403) {
      const bas = msg.toLowerCase();
      if (bas.includes("quota") || bas.includes("epuise") || bas.includes("épuis")) {
        msg =
          "Quota missions épuisé — impossible de créer une nouvelle mission. " +
          "Contactez l’admin billing ou attendez la prochaine période. " +
          `(${err.message})`;
      }
    } else if (err instanceof ApiError && err.status === 409) {
      msg = `${err.message} Votre paramétrage est conservé — ajustez le cadrage.`;
    } else if (err instanceof ApiError && err.status === 400) {
      msg = `Création refusée : ${err.message}`;
    }
    return msg;
  }

  /**
   * Bouton « Créer la mission » du cadrage — lie un client existant du
   * portefeuille (la création de fiche se fait dans l'onglet Clients), crée
   * la mission puis enchaîne sur l'étape Sources existante.
   */
  async function creerMissionDepuisCadrage() {
    if (!session) return;
    setBusy(true);
    setMissionStatus(null);
    const jeton = session.jeton;
    try {
      if (contribIdExistant == null) {
        throw new Error(
          "Aucun client lié — sélectionnez un client du portefeuille " +
            "(la création de fiche se fait dans l'onglet Clients).",
        );
      }
      validerCadrage();
      const mission = await assurerMission(jeton, contribIdExistant);
      setMissionId(mission.id);
      setMissionStatus({
        msg: `Mission #${mission.id} créée — référentiel épinglé id=${mission.version_referentiel_id}. Déposez la source comptable.`,
        err: false,
      });
      setStep(2);
    } catch (err) {
      setMissionStatus({ msg: messageErreurCreation(err), err: true });
    } finally {
      setBusy(false);
    }
  }

  async function lancerRevue() {
    if (!session) return;
    setBusy(true);
    setRestitution(null);
    setAuditJournal(null);
    setMissionId(null);
    setEtapeRetour(null);
    setStep(3);
    const jeton = session.jeton;
    let etapeEnCours = 1;
    try {
      validerCadrage();
      const cid = await assurerContribuable(jeton);
      const mission = await assurerMission(jeton, cid);
      setMissionId(mission.id);
      etapeEnCours = 2;

      if (!peutLancerRevue) {
        throw new Error(
          "Source comptable non prête — corrigez l’équilibre / le format avant de lancer.",
        );
      }

      setMissionStatus({
        msg: `Mission #${mission.id} — référentiel épinglé id=${mission.version_referentiel_id}. Import source active (${sourceMeta.label})…`,
        err: false,
      });
      type RapportFiab = {
        statut: string;
        anomalies?: string[];
        nb_comptes?: number;
      };
      type DesigneOut = {
        rapport: RapportFiab;
        piece?: { id: number } | null;
        source_precedente_degradee?: boolean;
      };
      const typePiece = typePieceDepuisSource(sourceComptable);
      let rapport: RapportFiab;

      if (sourceDataroomOnglet) {
        if (!sourceDataroomPiece) {
          throw new Error("Pièce du Data Room manquante.");
        }
        const designe = await api<DesigneOut>(
          `/api/v1/missions/${mission.id}/source-depuis-piece`,
          {
            method: "POST",
            jeton,
            json: {
              piece_id: sourceDataroomPiece.id,
              type_piece:
                sourceDataroomPiece.format === "fec" ? "fec" : typePiece,
              confirmer: true,
            },
          },
        );
        rapport = designe.rapport;
        if (rapport.statut && rapport.statut !== "ok") {
          const detail = (rapport.anomalies ?? []).slice(0, 3).join(" · ");
          throw new Error(
            `Import refusé (${rapport.statut})${detail ? ` — ${detail}` : ""}. Corrigez la source puis relancez.`,
          );
        }
      } else if (sourceComptable === "balance" && balanceSource === "json") {
        // Import JSON puis enregistrement métadonnée source_active.
        rapport = await api<RapportFiab>(
          `/api/v1/missions/${mission.id}/balance`,
          {
            method: "POST",
            jeton,
            json: JSON.parse(balanceJson),
          },
        );
        if (rapport.statut && rapport.statut !== "ok") {
          const detail = (rapport.anomalies ?? []).slice(0, 3).join(" · ");
          throw new Error(
            `Import refusé (${rapport.statut})${detail ? ` — ${detail}` : ""}. Corrigez la source puis relancez.`,
          );
        }
        const blob = new Blob([balanceJson], { type: "application/json" });
        const metaFile = new File([blob], "balance.json", {
          type: "application/json",
        });
        await apiUpload(
          `/api/v1/missions/${mission.id}/pieces/enregistrer-source`,
          metaFile,
          jeton,
          { type_piece: typePiece, confirmer: "true" },
        );
      } else {
        const fichierActif =
          sourceComptable === "balance" ? balanceFile : sourceAltFile;
        if (!fichierActif) {
          throw new Error(`Fichier ${sourceMeta.label} manquant.`);
        }
        const designe = await apiUpload<DesigneOut>(
          `/api/v1/missions/${mission.id}/source-active?type_piece=${encodeURIComponent(typePiece)}&confirmer=true`,
          fichierActif,
          jeton,
          { type_piece: typePiece, confirmer: "true" },
        );
        rapport = designe.rapport;
        if (rapport.statut && rapport.statut !== "ok") {
          const detail = (rapport.anomalies ?? []).slice(0, 3).join(" · ");
          throw new Error(
            `Import refusé (${rapport.statut})${detail ? ` — ${detail}` : ""}. Corrigez la source puis relancez.`,
          );
        }
      }

      setMissionStatus({ msg: "Exécution du moteur…", err: false });
      await api(`/api/v1/missions/${mission.id}/executer`, {
        method: "POST",
        jeton,
        json: { reponses: {} },
      });

      setMissionStatus({ msg: "Restitution…", err: false });
      const rest = await api<Restitution>(
        `/api/v1/missions/${mission.id}/restitution`,
        { jeton },
      );
      setRestitution(rest);
      if (rest.version_referentiel_id != null) {
        setVersionEpinglee({
          id: rest.version_referentiel_id,
          libelle: rest.version_referentiel_libelle,
        });
      }
      setMissionStatus({
        msg: `Terminé — exécution ${rest.execution_id ?? "—"} · référentiel ${
          rest.version_referentiel_libelle ?? rest.version_referentiel_id ?? "—"
        }`,
        err: false,
      });
      void chargerDashboard(jeton);
      try {
        const q = await api<QuotaResume>("/api/v1/quota", { jeton });
        setQuota(q);
        if (q.bloque) {
          setMissionStatus((prev) =>
            prev && !prev.err
              ? {
                  msg:
                    `${prev.msg} · Quota missions atteint ` +
                    `(${q.missions_utilisees}/${q.missions_incluses}) — ` +
                    "cette mission était la dernière incluse de la période.",
                  err: false,
                }
              : prev,
          );
        }
      } catch {
        /* quota indicatif — silencieux */
      }
    } catch (err) {
      setEtapeRetour(etapeEnCours);
      setMissionStatus({ msg: messageErreurCreation(err), err: true });
    } finally {
      setBusy(false);
    }
  }

  async function ouvrirMission(id: number) {
    if (!session) return;
    setBusy(true);
    setVue("nouvelle");
    setStep(3);
    setMissionId(id);
    try {
      const rest = await api<Restitution>(`/api/v1/missions/${id}/restitution`, {
        jeton: session.jeton,
      });
      setRestitution(rest);
      if (rest.version_referentiel_id != null) {
        setVersionEpinglee({
          id: rest.version_referentiel_id,
          libelle: rest.version_referentiel_libelle,
        });
      }
      setMissionStatus({
        msg: `Mission #${id} ouverte · référentiel ${
          rest.version_referentiel_libelle ?? rest.version_referentiel_id ?? "—"
        }`,
        err: false,
      });
    } catch (err) {
      setMissionStatus({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function ouvrirClient(id: number) {
    if (!session) return;
    setBusy(true);
    try {
      const det = await api<ContribuableDetail>(
        `/api/v1/contribuables/${id}`,
        { jeton: session.jeton },
      );
      setClientDetail(det);
      setClientEdit({
        denomination: det.denomination,
        ncc: det.ncc || "",
        rccm: det.rccm || "",
        forme: (det.forme === "pp" ? "pp" : "pm") as FormePersonne,
        dfe: det.dfe || "",
        regime_fiscal: det.regime_fiscal || "reel",
        forme_juridique: det.forme_juridique || (det.forme === "pp" ? "EI" : "SA"),
        siege_social: det.siege_social || "",
        commune: det.commune || "",
        centre_impots: det.centre_impots || "",
        capital_social:
          det.capital_social != null && det.capital_social !== ""
            ? String(det.capital_social)
            : "",
        mois_cloture:
          det.mois_cloture != null ? String(det.mois_cloture) : "12",
        activite_principale: det.activite_principale || "",
        date_immatriculation: det.date_immatriculation
          ? String(det.date_immatriculation).slice(0, 10)
          : "",
      });
      setVue("client");
    } catch (err) {
      setMissionStatus({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function sauverClient() {
    if (!session || !clientDetail) return;
    setBusy(true);
    try {
      await api(`/api/v1/contribuables/${clientDetail.id}`, {
        method: "PATCH",
        jeton: session.jeton,
        json: payloadDepuisEdit(clientEdit),
      });
      await ouvrirClient(clientDetail.id);
      void chargerDashboard(session.jeton);
    } catch (err) {
      setMissionStatus({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  function payloadContribuable(edit: ClientEditState) {
    return payloadDepuisEdit(edit);
  }

  async function creerClientSeul(
    edit: ClientEditState,
    sessionUpload: string,
  ) {
    if (!session) return;
    setBusy(true);
    setMissionStatus(null);
    try {
      const cree = await api<{ id: number }>("/api/v1/contribuables", {
        method: "POST",
        jeton: session.jeton,
        json: payloadContribuable(edit),
      });
      let piecesMsg = "";
      try {
        const rattachees = await api<{ id: number }[]>(
          "/api/v1/pieces-contribuable/rattacher",
          {
            method: "POST",
            jeton: session.jeton,
            json: {
              session_upload: sessionUpload,
              contribuable_id: cree.id,
            },
          },
        );
        if (rattachees.length > 0) {
          piecesMsg = ` ${rattachees.length} pièce(s) rattachée(s).`;
        }
      } catch {
        piecesMsg =
          " Attention : pièces non rattachées (session orpheline possible).";
      }
      setMissionStatus({
        msg: `Client créé — fiche #${cree.id}.${piecesMsg}`,
        err: false,
      });
      await chargerDashboard(session.jeton);
      await ouvrirClient(cree.id);
    } catch (err) {
      setMissionStatus({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function creerClientPuisMission(
    edit: ClientEditState,
    sessionUpload: string,
  ) {
    if (!session) return;
    setBusy(true);
    setMissionStatus(null);
    try {
      const cree = await api<Contribuable>("/api/v1/contribuables", {
        method: "POST",
        jeton: session.jeton,
        json: payloadContribuable(edit),
      });
      try {
        await api("/api/v1/pieces-contribuable/rattacher", {
          method: "POST",
          jeton: session.jeton,
          json: {
            session_upload: sessionUpload,
            contribuable_id: cree.id,
          },
        });
      } catch {
        /* pièces optionnelles — mission créée quand même */
      }
      await chargerDashboard(session.jeton);
      await naviguer("nouvelle");
      chargerContribuableDansWizard({
        id: cree.id,
        denomination: cree.denomination,
        ncc: cree.ncc,
        rccm: cree.rccm,
        forme: cree.forme,
        dfe: cree.dfe,
        regime_fiscal: cree.regime_fiscal,
        forme_juridique: cree.forme_juridique,
        siege_social: cree.siege_social,
        commune: cree.commune,
        centre_impots: cree.centre_impots,
        capital_social: cree.capital_social,
        mois_cloture: cree.mois_cloture,
        activite_principale: cree.activite_principale,
        date_immatriculation: cree.date_immatriculation,
      });
      setMissionStatus({
        msg: `Client #${cree.id} créé — complètez la mission.`,
        err: false,
      });
    } catch (err) {
      setMissionStatus({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function creerLienClient() {
    if (!session || !missionId) return;
    setLienMsg(null);
    setLienUrl(null);
    try {
      const r = await api<{ token: string; expire_le: string }>(
        "/api/v1/liens-acces",
        {
          method: "POST",
          jeton: session.jeton,
          json: { mission_id: missionId },
        },
      );
      const url = `${location.origin}/client/?token=${encodeURIComponent(r.token)}`;
      setLienUrl(url);
      setLienMsg(null);
    } catch (err) {
      setLienUrl(null);
      setLienMsg(err instanceof Error ? err.message : String(err));
    }
  }

  async function copierLienClient() {
    if (!lienUrl) return;
    try {
      await navigator.clipboard.writeText(lienUrl);
      setMissionStatus({ msg: "Lien client copié.", err: false });
    } catch {
      setMissionStatus({
        msg: "Impossible de copier automatiquement — sélectionnez le lien.",
        err: true,
      });
    }
  }

  async function changerStatutMission(statut: "en_cours" | "cloturee") {
    if (!session || !missionId) return;
    setBusy(true);
    try {
      const r = await api<{
        id: number;
        statut: string;
        statut_precedent: string;
      }>(`/api/v1/missions/${missionId}/statut`, {
        method: "PATCH",
        jeton: session.jeton,
        json: { statut },
      });
      setMissionStatus({
        msg:
          statut === "cloturee"
            ? `Mission #${r.id} clôturée.`
            : `Mission #${r.id} réouverte (${r.statut}).`,
        err: false,
      });
      if (restitution) {
        setRestitution({
          ...restitution,
          identification: {
            ...(restitution.identification || {}),
            statut: r.statut,
          },
        });
      }
      setAuditJournal(null);
      void chargerDashboard(session.jeton);
    } catch (err) {
      setMissionStatus({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function accepterInvitation(e?: FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setAuthStatus(null);
    if (inviteAcceptToken.trim().length < 10) {
      setAuthStatus({ msg: "Jeton d'invitation invalide.", err: true });
      setBusy(false);
      return;
    }
    if (inviteAcceptMdp.length < 8) {
      setAuthStatus({
        msg: "Mot de passe trop court (min. 8 caractères).",
        err: true,
      });
      setBusy(false);
      return;
    }
    if (inviteAcceptMdp !== inviteAcceptMdp2) {
      setAuthStatus({ msg: "Les mots de passe ne correspondent pas.", err: true });
      setBusy(false);
      return;
    }
    try {
      const r = await api<{ email: string; role: string; tenant_id: number }>(
        "/api/v1/invitations/accepter",
        {
          method: "POST",
          json: {
            token: inviteAcceptToken.trim(),
            mot_de_passe: inviteAcceptMdp,
          },
        },
      );
      setEmailConn(r.email);
      setMdpConn(inviteAcceptMdp);
      setInviteAcceptToken("");
      setInviteAcceptMdp("");
      setInviteAcceptMdp2("");
      setAuthTab("conn");
      setAuthStatus({
        msg: `Compte créé (${r.email}, rôle ${r.role}). Connectez-vous.`,
        err: false,
      });
      try {
        const u = new URL(window.location.href);
        u.searchParams.delete("invitation");
        u.searchParams.delete("invite");
        u.searchParams.delete("token");
        const qs = u.searchParams.toString();
        window.history.replaceState({}, "", u.pathname + (qs ? `?${qs}` : ""));
      } catch {
        /* ignore */
      }
    } catch (err) {
      setAuthStatus({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function inviter(e?: FormEvent) {
    e?.preventDefault();
    if (!session) return;
    setBusy(true);
    setEquipeMsg(null);
    setInviteToken(null);
    try {
      const r = await api<{
        token: string;
        email: string;
        email_envoi?: {
          statut?: string;
          mode?: string | null;
          outbox_id?: number | null;
          note?: string;
        };
      }>("/api/v1/invitations", {
        method: "POST",
        jeton: session.jeton,
        json: { email: inviteEmail, role: inviteRole },
      });
      setInviteToken({
        email: r.email,
        token: r.token,
        emailEnvoi: r.email_envoi,
      });
      const envoi = r.email_envoi;
      const statutMail = envoi?.statut || "inconnu";
      let msgMail = `Invitation créée pour ${r.email}.`;
      if (statutMail === "simule_dev") {
        msgMail +=
          " Email simulé (RESEND_API_KEY absent) — jeton ci-dessous + outbox.";
      } else if (statutMail === "echec") {
        msgMail +=
          " Envoi email en échec — jeton ci-dessous (pas de faux succès).";
      } else if (statutMail === "envoye") {
        msgMail += " Email envoyé via Resend.";
      } else {
        msgMail += " Copiez le jeton ci-dessous (affiché une seule fois).";
      }
      setEquipeMsg({ msg: msgMail, err: statutMail === "echec" });
      setInviteEmail("");
      await chargerEquipe(session.jeton);
      await chargerOnboarding(session.jeton);
      await chargerEmailOutbox(session.jeton);
    } catch (err) {
      setEquipeMsg({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function changerRoleUtilisateur(
    userId: number,
    role: "lecteur" | "reviseur" | "admin",
  ) {
    if (!session) return;
    setBusy(true);
    setEquipeMsg(null);
    try {
      await api(`/api/v1/utilisateurs/${userId}`, {
        method: "PATCH",
        jeton: session.jeton,
        json: { role },
      });
      setEquipeMsg({ msg: "Rôle mis à jour.", err: false });
      await chargerEquipe(session.jeton);
    } catch (err) {
      setEquipeMsg({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
      await chargerEquipe(session.jeton);
    } finally {
      setBusy(false);
    }
  }

  async function revoquerInvitation(invitationId: number) {
    if (!session) return;
    setBusy(true);
    setEquipeMsg(null);
    try {
      await api(`/api/v1/invitations/${invitationId}/revoquer`, {
        method: "POST",
        jeton: session.jeton,
      });
      setEquipeMsg({ msg: "Invitation révoquée.", err: false });
      await chargerEquipe(session.jeton);
    } catch (err) {
      setEquipeMsg({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function chargerEmailOutbox(jeton: string) {
    try {
      const data = await api<{
        resend?: {
          resend_configure?: boolean;
          mode_sans_cle?: string | null;
          note?: string;
        };
        lignes?: Array<{
          id: number;
          destinataire: string;
          sujet: string;
          statut: string;
          dernier_erreur?: string | null;
          cree_le?: string;
        }>;
      }>("/api/v1/email-outbox?limit=10", { jeton });
      setEmailOutbox(data);
    } catch {
      setEmailOutbox(null);
    }
  }

  async function copierInviteToken() {
    if (!inviteToken) return;
    try {
      await navigator.clipboard.writeText(inviteToken.token);
      setEquipeMsg({
        msg: `Jeton copié pour ${inviteToken.email}.`,
        err: false,
      });
    } catch {
      setEquipeMsg({
        msg: "Copie automatique indisponible — sélectionnez le jeton manuellement.",
        err: true,
      });
    }
  }

  async function chargerAudit() {
    if (!session || !missionId) return;
    setBusy(true);
    try {
      const audit = await api<AuditJournal>(
        `/api/v1/missions/${missionId}/audit`,
        { jeton: session.jeton },
      );
      setAuditJournal(audit);
    } catch (err) {
      setMissionStatus({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function exportFichier(kind: "docx" | "pdf") {
    if (!session || !missionId) return;
    try {
      await telecharger(
        `/api/v1/missions/${missionId}/restitution/rapport.${kind}`,
        session.jeton,
        `rapport-mission-${missionId}.${kind}`,
      );
    } catch (err) {
      setMissionStatus({
        msg: err instanceof Error ? err.message : String(err),
        err: true,
      });
    }
  }

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(lireSidebarCollapsed);

  function basculerSidebar() {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        /* ignore quota / mode privé */
      }
      return next;
    });
  }

  const progressPct =
    session && vue === "nouvelle"
      ? restitution
        ? 100
        : ((step - 1) / 2) * 100
      : 0;

  const navItems: Array<{
    id: Vue;
    label: string;
    group: "pilotage" | "travail" | "cabinet";
    hide?: boolean;
    accent?: boolean;
    badge?: number | null;
    /** Classe additionnelle du badge (ex. « orange » pour les relances échues). */
    badgeClass?: string;
    icon: ReactNode;
  }> = [
    {
      id: "dashboard",
      label: "Tableau de bord",
      group: "pilotage",
      badge: nbRelances || null,
      badgeClass: "orange",
      icon: (
        <svg className="nav-ico" viewBox="0 0 24 24" aria-hidden="true">
          <rect x="3" y="3" width="7" height="9" rx="1" />
          <rect x="14" y="3" width="7" height="5" rx="1" />
          <rect x="14" y="12" width="7" height="9" rx="1" />
          <rect x="3" y="16" width="7" height="5" rx="1" />
        </svg>
      ),
    },
    {
      id: "clients",
      label: "Clients",
      group: "travail",
      badge: clients.length || null,
      icon: (
        <svg className="nav-ico" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
        </svg>
      ),
    },
    {
      id: "missions",
      label: "Missions",
      group: "travail",
      badge: missions.length || null,
      icon: (
        <svg className="nav-ico" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6M8 13h8M8 17h5" />
        </svg>
      ),
    },
    {
      id: "nouvelle",
      label: "Nouvelle mission",
      group: "travail",
      hide: estLecteur,
      accent: true,
      icon: (
        <svg className="nav-ico" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 5v14M5 12h14" strokeLinecap="round" />
        </svg>
      ),
    },
    {
      id: "equipe",
      label: "Équipe",
      group: "cabinet",
      hide: !estAdmin,
      badge: users.length || null,
      icon: (
        <svg className="nav-ico" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M22 11h-6M19 8v6" strokeLinecap="round" />
        </svg>
      ),
    },
    {
      id: "facturation",
      label: "Facturation",
      group: "cabinet",
      icon: (
        <svg className="nav-ico" viewBox="0 0 24 24" aria-hidden="true">
          <rect x="4" y="3" width="16" height="18" rx="2" />
          <path d="M8 7h8M8 11h8M8 15h5" strokeLinecap="round" />
        </svg>
      ),
    },
    {
      id: "compte",
      label: "Compte",
      group: "cabinet",
      icon: (
        <svg className="nav-ico" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="8" r="4" />
          <path d="M4 21v-1a6 6 0 0 1 12 0v1" />
        </svg>
      ),
    },
  ];

  const navGroups: Array<{
    id: "pilotage" | "travail" | "cabinet";
    label: string;
  }> = [
    { id: "pilotage", label: "Pilotage" },
    { id: "travail", label: "Travail" },
    { id: "cabinet", label: "Cabinet" },
  ];

  /** Destinations pouce (mobile) — labels courts ; Équipe / Nouvelle restent dans le drawer. */
  const bottomNavIds: Vue[] = [
    "dashboard",
    "missions",
    "clients",
    "facturation",
    "compte",
  ];
  const bottomNavItems = bottomNavIds
    .map((id) => navItems.find((n) => n.id === id))
    .filter((n): n is (typeof navItems)[number] => !!n && !n.hide)
    .map((n) =>
      n.id === "dashboard" ? { ...n, label: "Accueil" } : n,
    );

  function navItemActif(id: Vue): boolean {
    return (
      vue === id ||
      (id === "clients" && (vue === "client" || vue === "client-nouveau"))
    );
  }

  async function naviguer(
    v: Vue,
    opts?: { filtreStatut?: string; filtreExercice?: string },
  ) {
    setDrawerOpen(false);
    await aller(v, opts);
  }

  const dashStats = useMemo(() => {
    // Actives = non clôturées (cadrage + en_cours) — cf. src/statuts.ts,
    // aligné sur les 3 statuts canoniques du backend.
    const actives = missions.filter((m) => estMissionActive(m.statut));
    const cloturees = missions.length - actives.length;
    const parStatut = new Map<string, number>();
    for (const m of missions) {
      parStatut.set(m.statut, (parStatut.get(m.statut) ?? 0) + 1);
    }
    const enCours = parStatut.get("en_cours") ?? 0;
    const cadrage = parStatut.get("cadrage") ?? 0;
    const quotaPct =
      quota && quota.missions_incluses > 0
        ? Math.min(
            100,
            Math.round(
              (quota.missions_utilisees / quota.missions_incluses) * 100,
            ),
          )
        : 0;
    const restant = quota
      ? Math.max(0, quota.missions_incluses - quota.missions_utilisees)
      : null;
    return { actives, cloturees, enCours, cadrage, parStatut, quotaPct, restant };
  }, [missions, quota]);

  return (
    <>
      {!session ? (
        <div className="login-screen">
          <div className="login-shell">
            <aside className="login-hero">
              <div className="login-hero-glow" aria-hidden="true" />
              <div className="login-hero-grid" aria-hidden="true" />
              <div className="login-hero-copy">
                <p className="login-eyebrow">Intelligence fiscale · CGI</p>
                <h1 className="hero-brand">
                  <Logo variant="hero" />
                </h1>
                <p className="hero-tagline">
                  Scannez votre comptabilité, anticipez l’exposition au contrôle
                  et validez des conclusions assumées — cabinets comme entreprises.
                </p>
                <ul className="login-points">
                  <li>
                    <span className="login-point-k">01</span>
                    <span>Risques détectés — écritures analysées, points d’attention signalés</span>
                  </li>
                  <li>
                    <span className="login-point-k">02</span>
                    <span>L’intelligence propose — vous validez et portez chaque conclusion</span>
                  </li>
                  <li>
                    <span className="login-point-k">03</span>
                    <span>Dossiers protégés — chaque cabinet et entreprise dans son espace</span>
                  </li>
                </ul>
              </div>
              <p className="login-hero-foot">
                Un produit 2AàZ SAS — cabinet d’expertise comptable agréé, inscrit
                à l’Ordre des experts-comptables de Côte d’Ivoire
              </p>
            </aside>

            <div className="login-card">
              <div className="login-card-inner">
                <div className="login-card-head">
                  <div className="login-card-brand mobile-only">
                    <Logo variant="bar" />
                  </div>
                  <p className="login-card-kicker">Espace abonné</p>
                  <h2 className="login-form-title">
                    {authTab === "conn"
                      ? "Bon retour"
                      : authTab === "invite"
                        ? "Rejoindre un cabinet"
                        : "Ouvrir un espace"}
                  </h2>
                  {authTab === "conn" ? (
                    <p className="login-form-sub">
                      Accédez au cabinet avec l’email administrateur.
                    </p>
                  ) : authTab === "invite" ? (
                    <p className="login-form-sub">
                      Choisissez un mot de passe pour activer votre accès
                      (invitation reçue par e-mail).
                    </p>
                  ) : null}
                </div>

                <div className="auth-panel" role="region" aria-label="Authentification">
                  {authTab !== "invite" ? (
                    <div className="tabs" role="tablist" aria-label="Mode d'accès">
                      <button
                        type="button"
                        className={`tab${authTab === "conn" ? " active" : ""}`}
                        role="tab"
                        aria-selected={authTab === "conn"}
                        onClick={() => changerAuthTab("conn")}
                      >
                        Connexion
                      </button>
                      <button
                        type="button"
                        className={`tab${authTab === "prov" ? " active" : ""}`}
                        role="tab"
                        aria-selected={authTab === "prov"}
                        onClick={() => changerAuthTab("prov")}
                      >
                        Créer un espace
                      </button>
                    </div>
                  ) : null}

                  {authTab === "invite" ? (
                    <form
                      className="auth-form"
                      onSubmit={(e) => void accepterInvitation(e)}
                    >
                      <input type="hidden" value={inviteAcceptToken} readOnly />
                      <div className="field-stack">
                        <label htmlFor="invite-mdp">Mot de passe</label>
                        <input
                          id="invite-mdp"
                          type="password"
                          autoComplete="new-password"
                          placeholder="••••••••"
                          value={inviteAcceptMdp}
                          onChange={(e) => setInviteAcceptMdp(e.target.value)}
                          minLength={8}
                          required
                          autoFocus
                        />
                      </div>
                      <div className="field-stack">
                        <label htmlFor="invite-mdp2">Confirmer</label>
                        <input
                          id="invite-mdp2"
                          type="password"
                          autoComplete="new-password"
                          placeholder="••••••••"
                          value={inviteAcceptMdp2}
                          onChange={(e) => setInviteAcceptMdp2(e.target.value)}
                          minLength={8}
                          required
                        />
                      </div>
                      <div className="cta-row">
                        <button
                          type="submit"
                          className="btn btn-primary btn-block btn-auth"
                          disabled={busy}
                        >
                          {busy ? "Validation…" : "Créer mon compte"}
                        </button>
                      </div>
                      <p className="login-form-sub" style={{ marginTop: "0.75rem" }}>
                        <button
                          type="button"
                          className="btn btn-ghost btn-block"
                          onClick={() => {
                            setInviteAcceptToken("");
                            setInviteAcceptMdp("");
                            setInviteAcceptMdp2("");
                            changerAuthTab("conn");
                            try {
                              const u = new URL(window.location.href);
                              u.searchParams.delete("invitation");
                              u.searchParams.delete("invite");
                              u.searchParams.delete("token");
                              const qs = u.searchParams.toString();
                              window.history.replaceState(
                                {},
                                "",
                                u.pathname + (qs ? `?${qs}` : ""),
                              );
                            } catch {
                              /* ignore */
                            }
                          }}
                        >
                          Retour à la connexion
                        </button>
                      </p>
                    </form>
                  ) : authTab === "conn" ? (
                    <>
                      <form
                        id="form-login-conn"
                        className="auth-form"
                        onSubmit={connexion}
                      >
                        <div className="field-stack">
                          <label htmlFor="email-conn">Email</label>
                          <input
                            id="email-conn"
                            type="email"
                            autoComplete="username"
                            placeholder="admin@cabinet.ci"
                            value={emailConn}
                            onChange={(e) => setEmailConn(e.target.value)}
                            required
                          />
                        </div>
                        <div className="field-stack">
                          <label htmlFor="mdp-conn">Mot de passe</label>
                          <input
                            id="mdp-conn"
                            type="password"
                            autoComplete="current-password"
                            placeholder="••••••••"
                            value={mdpConn}
                            onChange={(e) => setMdpConn(e.target.value)}
                            required
                          />
                        </div>
                        <div className="cta-row">
                          <button
                            type="submit"
                            className="btn btn-primary btn-block btn-auth"
                            disabled={busy}
                          >
                            {busy ? "Connexion…" : "Se connecter"}
                          </button>
                        </div>
                      </form>
                      {isDev && (
                        <div className="demo-access" role="region" aria-label="Accès démo">
                          <div className="demo-access-head">
                            <span className="demo-badge">Démo</span>
                            <span className="demo-access-hint">
                              Clic = remplir · double-clic = connexion
                            </span>
                          </div>
                          <div className="demo-chips" role="group">
                            <button
                              type="button"
                              className="demo-chip"
                              onClick={fillDemoCabinet}
                              onDoubleClick={(e) => {
                                e.preventDefault();
                                submitDemoCabinet();
                              }}
                            >
                              Remplir Cabinet
                            </button>
                            <button
                              type="button"
                              className="demo-chip demo-chip-submit"
                              onClick={submitDemoCabinet}
                              disabled={busy}
                            >
                              Connexion démo
                            </button>
                          </div>
                          <p className="demo-access-rejouer">
                            Rejouer la démo :{" "}
                            <code>{demoCreds?.rejouer || "make demolot"}</code>
                            {" "}(seed + mission FICTIF)
                          </p>
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      <ol className="signup-steps signup-steps-3" aria-label="Progression">
                        <li
                          className={
                            provStep === 1 ? "current" : provStep > 1 ? "done" : ""
                          }
                        >
                          <span className="signup-step-n">1</span>
                          Identité
                        </li>
                        <li
                          className={
                            provStep === 2 ? "current" : provStep > 2 ? "done" : ""
                          }
                        >
                          <span className="signup-step-n">2</span>
                          Contact
                        </li>
                        <li className={provStep === 3 ? "current" : ""}>
                          <span className="signup-step-n">3</span>
                          Accès
                        </li>
                      </ol>

                      {provStep === 1 ? (
                        <form className="auth-form" onSubmit={allerProvEtape2}>
                          <div className="field-stack">
                            <span className="field-legend">Type d’abonné</span>
                            <div
                              className="seg"
                              role="group"
                              aria-label="Type d’abonné"
                            >
                              <button
                                type="button"
                                className={`seg-btn${typeTenant === "cabinet" ? " active" : ""}`}
                                onClick={() => setTypeTenant("cabinet")}
                              >
                                Cabinet
                              </button>
                              <button
                                type="button"
                                className={`seg-btn${typeTenant === "entreprise" ? " active" : ""}`}
                                onClick={() => setTypeTenant("entreprise")}
                              >
                                Entreprise
                              </button>
                            </div>
                          </div>
                          <div className="field-stack">
                            <label htmlFor="denom">
                              {typeTenant === "cabinet"
                                ? "Nom du cabinet"
                                : "Raison sociale"}
                            </label>
                            <input
                              id="denom"
                              autoComplete="organization"
                              placeholder={
                                typeTenant === "cabinet"
                                  ? "Cabinet Dupont & Associés"
                                  : "Société Exemple SA"
                              }
                              value={denom}
                              onChange={(e) => setDenom(e.target.value)}
                              required
                              minLength={2}
                              maxLength={200}
                              autoFocus
                            />
                          </div>
                          <div className="cta-row">
                            <button
                              type="submit"
                              className="btn btn-primary btn-block btn-auth"
                            >
                              Continuer
                            </button>
                          </div>
                        </form>
                      ) : provStep === 2 ? (
                        <form
                          className="auth-form"
                          onSubmit={jetonInscription ? undefined : otpSent ? validerOtp : envoyerOtp}
                        >
                          <div className="signup-recap">
                            <span className="signup-recap-type">
                              {typeTenant === "cabinet" ? "Cabinet" : "Entreprise"}
                            </span>
                            <strong>{denom.trim()}</strong>
                            <button
                              type="button"
                              className="linkish"
                              onClick={() => {
                                setProvStep(1);
                                setAuthStatus(null);
                              }}
                            >
                              Modifier
                            </button>
                          </div>
                          <div className="field-stack">
                            <label htmlFor="email-prov">Email professionnel</label>
                            <input
                              id="email-prov"
                              type="email"
                              autoComplete="username"
                              placeholder="admin@cabinet.ci"
                              value={emailProv}
                              onChange={(e) => {
                                setEmailProv(e.target.value);
                                setOtpSent(false);
                                setJetonInscription(null);
                                setOtpCode("");
                              }}
                              required
                              disabled={!!jetonInscription}
                              autoFocus
                            />
                          </div>
                          {!otpSent ? (
                            <div className="cta-row">
                              <button
                                type="submit"
                                className="btn btn-primary btn-block btn-auth"
                                disabled={busy}
                              >
                                {busy ? "Envoi…" : "Envoyer le code"}
                              </button>
                            </div>
                          ) : (
                            <>
                              <div className="field-stack">
                                <label htmlFor="otp-code">Code reçu par email</label>
                                <input
                                  id="otp-code"
                                  inputMode="numeric"
                                  autoComplete="one-time-code"
                                  placeholder="000000"
                                  maxLength={6}
                                  value={otpCode}
                                  onChange={(e) =>
                                    setOtpCode(e.target.value.replace(/\D/g, "").slice(0, 6))
                                  }
                                  required
                                />
                                {otpDebug && (
                                  <p className="field-hint">
                                    Dev — code : <strong>{otpDebug}</strong>
                                  </p>
                                )}
                                <button
                                  type="button"
                                  className="linkish"
                                  disabled={busy}
                                  onClick={() => void envoyerOtp()}
                                >
                                  Renvoyer le code
                                </button>
                              </div>
                              <div className="field-stack">
                                <label htmlFor="telephone">Téléphone mobile</label>
                                <PhoneField
                                  id="telephone"
                                  valueE164={telephoneE164}
                                  onChangeE164={setTelephoneE164}
                                  defaultCountry="CI"
                                  required
                                />
                                <p className="field-hint">
                                  Indicatif pays + masque national — format E.164.
                                </p>
                              </div>
                              <div className="cta-row cta-row-split">
                                <button
                                  type="button"
                                  className="btn btn-ghost"
                                  onClick={() => {
                                    setProvStep(1);
                                    setAuthStatus(null);
                                  }}
                                  disabled={busy}
                                >
                                  Retour
                                </button>
                                <button
                                  type="submit"
                                  className="btn btn-primary btn-auth"
                                  disabled={
                                    busy ||
                                    otpCode.length !== 6 ||
                                    !telephoneE164
                                  }
                                  onClick={(ev) => {
                                    ev.preventDefault();
                                    void validerOtp();
                                  }}
                                >
                                  {busy ? "Vérification…" : "Continuer"}
                                </button>
                              </div>
                            </>
                          )}
                        </form>
                      ) : (
                        <form className="auth-form" onSubmit={provisionner}>
                          <div className="signup-recap">
                            <span className="signup-recap-type">Vérifié</span>
                            <strong>{emailProv.trim().toLowerCase()}</strong>
                            <button
                              type="button"
                              className="linkish"
                              onClick={() => {
                                setProvStep(2);
                                setAuthStatus(null);
                              }}
                            >
                              Modifier
                            </button>
                          </div>
                          <div className="field-stack">
                            <label htmlFor="mdp-prov">Mot de passe</label>
                            <input
                              id="mdp-prov"
                              type="password"
                              autoComplete="new-password"
                              placeholder="8 caractères minimum"
                              value={mdpProv}
                              onChange={(e) => setMdpProv(e.target.value)}
                              required
                              minLength={8}
                              autoFocus
                            />
                            <p
                              className={`field-hint${mdpProv.length > 0 && mdpProv.length < 8 ? " warn" : ""}`}
                            >
                              {mdpProv.length === 0
                                ? "Minimum 8 caractères."
                                : mdpProv.length < 8
                                  ? `Encore ${8 - mdpProv.length} caractère(s).`
                                  : "Longueur acceptée."}
                            </p>
                          </div>
                          <div className="field-stack">
                            <label htmlFor="mdp-prov-confirm">
                              Confirmer le mot de passe
                            </label>
                            <input
                              id="mdp-prov-confirm"
                              type="password"
                              autoComplete="new-password"
                              placeholder="Retapez le mot de passe"
                              value={mdpProvConfirm}
                              onChange={(e) => setMdpProvConfirm(e.target.value)}
                              required
                              minLength={8}
                            />
                            {mdpProvConfirm.length > 0 &&
                              mdpProv !== mdpProvConfirm && (
                                <p className="field-hint warn">
                                  Les mots de passe ne correspondent pas.
                                </p>
                              )}
                          </div>
                          {isDev && (
                            <label className="check" htmlFor="creer-demo">
                              <input
                                id="creer-demo"
                                type="checkbox"
                                checked={creerDemo}
                                onChange={(e) => setCreerDemo(e.target.checked)}
                              />
                              Créer un contribuable démo (dev uniquement)
                            </label>
                          )}
                          <div className="cta-row cta-row-split">
                            <button
                              type="button"
                              className="btn btn-ghost"
                              onClick={() => {
                                setProvStep(2);
                                setAuthStatus(null);
                              }}
                              disabled={busy}
                            >
                              Retour
                            </button>
                            <button
                              type="submit"
                              className="btn btn-primary btn-auth"
                              disabled={
                                busy ||
                                mdpProv.length < 8 ||
                                mdpProv !== mdpProvConfirm
                              }
                            >
                              {busy ? "Création…" : "Créer l’espace"}
                            </button>
                          </div>
                        </form>
                      )}
                    </>
                  )}

                  {authStatus && (
                    <p
                      className={`status${authStatus.err ? " err" : ""}`}
                      role="status"
                    >
                      {authStatus.msg}
                    </p>
                  )}
                </div>

                <p className="login-pitch">
                  Moins d’incertitude fiscale. Plus de décisions sourcées —
                  pour chaque client, chaque exercice.
                </p>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div
          className={`app-frame${sidebarCollapsed ? " sidebar-collapsed" : ""}`}
        >
          <header className="app-topbar">
            <div className="topbar-left">
              <button
                type="button"
                className="btn-menu"
                aria-label="Menu"
                onClick={() => setDrawerOpen(true)}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />
                </svg>
              </button>
              <div className="brand-mini">
                <Logo variant="bar" />
              </div>
              <span className="surface-pill">Cabinet</span>
            </div>
            <div className="topbar-actions">
              <span
                className="chip"
                title={`${session.tenant_denomination} · ${session.email} · ${session.role}`}
              >
                {session.tenant_denomination}
                <span className="chip-sep">·</span>
                {session.role}
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={logout}
              >
                Déconnexion
              </button>
            </div>
          </header>

          <aside
            className={`app-sidebar${drawerOpen ? " open" : ""}`}
            aria-label="Navigation"
          >
            <div className="sidebar-brand">
              <LogoMark variant="bar" />
              <div className="sidebar-brand-copy">
                <strong>Revue Fiscale</strong>
                <span>Espace cabinet</span>
              </div>
              <button
                type="button"
                className="btn-sidebar-collapse"
                aria-expanded={!sidebarCollapsed}
                aria-controls="sidebar-nav"
                aria-label={
                  sidebarCollapsed
                    ? "Développer la navigation"
                    : "Réduire la navigation"
                }
                title={
                  sidebarCollapsed
                    ? "Développer la navigation"
                    : "Réduire la navigation"
                }
                onClick={basculerSidebar}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  {sidebarCollapsed ? (
                    <path
                      d="M9 6l6 6-6 6"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.75"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  ) : (
                    <path
                      d="M15 6l-6 6 6 6"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.75"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  )}
                </svg>
              </button>
              {mobile && (
                <button
                  type="button"
                  className="sidebar-close"
                  aria-label="Fermer le menu"
                  onClick={() => setDrawerOpen(false)}
                >
                  ✕
                </button>
              )}
            </div>

            <nav className="sidebar-nav" id="sidebar-nav">
              {navGroups.map((g) => {
                const items = navItems.filter(
                  (n) => n.group === g.id && !n.hide,
                );
                if (!items.length) return null;
                return (
                  <div key={g.id} className="sidebar-group">
                    <p className="nav-label">{g.label}</p>
                    <div className="sidebar-group-items">
                      {items.map((n) => {
                        const active = navItemActif(n.id);
                        return (
                          <button
                            key={n.id}
                            type="button"
                            className={`side-nav-item${active ? " active" : ""}${n.accent ? " accent" : ""}`}
                            title={sidebarCollapsed ? n.label : undefined}
                            aria-label={n.label}
                            aria-current={active ? "page" : undefined}
                            onClick={() => void naviguer(n.id)}
                          >
                            <span className="nav-ico-wrap" aria-hidden="true">
                              {n.icon}
                            </span>
                            <span className="nav-label-txt">{n.label}</span>
                            {n.badge != null && n.badge > 0 && (
                              <span
                                className={`nav-badge${
                                  n.badgeClass ? ` ${n.badgeClass}` : ""
                                }`}
                              >
                                {n.badge}
                              </span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </nav>

            <div className="sidebar-foot">
              {quota && (
                <div
                  className={`sidebar-quota${quota.alerte_80 ? " warn" : ""}${quota.bloque ? " blocked" : ""}`}
                  title={
                    sidebarCollapsed
                      ? `Quota missions ${quota.missions_utilisees}/${quota.missions_incluses}`
                      : undefined
                  }
                >
                  <div className="sidebar-quota-head">
                    <span>Quota missions</span>
                    <strong>
                      {quota.missions_utilisees}/{quota.missions_incluses}
                    </strong>
                  </div>
                  <div className="sidebar-quota-track" aria-hidden="true">
                    <i
                      style={{
                        width: `${Math.min(
                          100,
                          Math.round(
                            (100 * quota.missions_utilisees) /
                              Math.max(1, quota.missions_incluses),
                          ),
                        )}%`,
                      }}
                    />
                  </div>
                </div>
              )}
              <div className="sidebar-guarantees">
                <span>Référentiel épinglé</span>
                <span>RLS</span>
                <span>Calcul déterministe</span>
              </div>
              <div className="sidebar-tenant">
                <span className="sidebar-tenant-name">
                  {session.tenant_denomination}
                </span>
                <span className="sidebar-tenant-meta">
                  {session.role} · {session.email}
                </span>
              </div>
            </div>
          </aside>

          <main className="app-main">
            {onboarding && !onboarding.complete && !onboardingMasque && (
              <section className="onboarding-card" aria-label="Premiers pas">
                <div className="onboarding-card-head">
                  <div>
                    <p className="onboarding-kicker">Bienvenue</p>
                    <h2 className="onboarding-title">
                      Lancez votre espace en {onboarding.total} étapes
                    </h2>
                    <p className="onboarding-sub">
                      {onboarding.progression}/{onboarding.total} complétées —
                      suivez le parcours pour un démarrage propre.
                    </p>
                  </div>
                  <Tooltip label="Masquer pour cette session — le parcours réapparaîtra à la prochaine connexion si incomplet.">
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => setOnboardingMasque(true)}
                    >
                      Plus tard
                    </button>
                  </Tooltip>
                </div>
                <div
                  className="onboarding-progress"
                  role="progressbar"
                  aria-valuenow={onboarding.progression}
                  aria-valuemin={0}
                  aria-valuemax={onboarding.total}
                  aria-label="Progression du démarrage"
                >
                  <div
                    className="onboarding-progress-fill"
                    style={{
                      width: `${Math.round(
                        (onboarding.progression / onboarding.total) * 100,
                      )}%`,
                    }}
                  />
                </div>
                <ul className="onboarding-list">
                  {(
                    [
                      [
                        "email_verifie",
                        "Email vérifié",
                        "Adresse e-mail confirmée — requis pour les notifications et invitations.",
                      ],
                      [
                        "telephone_renseigne",
                        "Téléphone renseigné",
                        "Numéro E.164 du cabinet — utile pour la sécurisation du compte.",
                      ],
                      [
                        "premier_client",
                        "Ajouter un premier client",
                        "Créer un contribuable dans votre portefeuille cloisonné.",
                      ],
                      [
                        "premiere_mission",
                        "Lancer une première mission",
                        "Ouvrir une revue fiscale avec référentiel épinglé pour l’exercice.",
                      ],
                      [
                        "equipe_invitee",
                        "Inviter un collègue",
                        "Partager l’espace cabinet (admin) — rôles lecteur, réviseur ou admin.",
                      ],
                    ] as const
                  ).map(([id, label, tip]) => {
                    const done = !!onboarding.etapes[id];
                    const action =
                      !done && id === "telephone_renseigne"
                        ? () => {
                            void naviguer("compte");
                          }
                        : !done && id === "premier_client"
                        ? () => {
                            void naviguer("client-nouveau");
                          }
                        : !done && id === "premiere_mission"
                          ? () => {
                              void naviguer("nouvelle");
                            }
                          : !done && id === "equipe_invitee" && estAdmin
                            ? () => void naviguer("equipe")
                            : null;
                    return (
                      <li
                        key={id}
                        className={`${done ? "done" : ""}${action ? " actionable" : ""}`}
                      >
                        <Tooltip label={tip} side="bottom">
                          <span className="onboarding-check" aria-hidden="true">
                            {done ? "✓" : "○"}
                          </span>
                        </Tooltip>
                        <Tooltip label={tip} side="bottom">
                          <span className="onboarding-label">{label}</span>
                        </Tooltip>
                        {action && (
                          <button
                            type="button"
                            className="linkish"
                            onClick={action}
                          >
                            {id === "telephone_renseigne"
                              ? "Renseigner"
                              : id === "premier_client"
                              ? "Commencer"
                              : id === "premiere_mission"
                                ? "Lancer"
                                : "Inviter"}
                          </button>
                        )}
                        {done && (
                          <span className="onboarding-done-tag">Fait</span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}
            {quota && (quota.alerte_80 || quota.bloque) && (
              <Tooltip
                label={
                  quota.bloque
                    ? "Quota épuisé : aucune nouvelle mission tant que la capacité n’est pas ajustée."
                    : "Plus de 80 % du quota missions consommé sur la période en cours."
                }
              >
                <div
                  className={`quota-bar${quota.alerte_80 ? " warn" : ""}${quota.bloque ? " blocked" : ""}`}
                  role="status"
                >
                  Quota missions : {quota.missions_utilisees}/
                  {quota.missions_incluses}
                  {quota.alerte_80 && !quota.bloque ? " — alerte 80 %" : ""}
                  {quota.bloque
                    ? " — BLOQUÉ : création de mission impossible jusqu’à la prochaine période ou ajustement billing."
                    : ""}
                  {quota.bloque && estAdmin && (
                    <>
                      {" "}
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => void naviguer("compte")}
                      >
                        Demander un palier
                      </button>
                    </>
                  )}
                </div>
              </Tooltip>
            )}

            {vue === "dashboard" && (
            <div className="page">
              <header className="page-head">
                <div>
                  <p className="page-eyebrow">Vue d&apos;ensemble</p>
                  <h2 className="section-title">Tableau de bord</h2>
                  <p className="section-sub">
                    Pilotage du cabinet — clients, missions et capacité.
                  </p>
                </div>
                <div className="page-actions">
                  {!estLecteur && (
                    <Tooltip
                      label={
                        quota?.bloque
                          ? "Quota bloqué — création impossible pour l’instant."
                          : "Créer un client et lancer une revue fiscale."
                      }
                    >
                      <button
                        type="button"
                        className="btn btn-primary"
                        disabled={!!quota?.bloque}
                        onClick={() => void naviguer("nouvelle")}
                      >
                        Nouvelle mission
                      </button>
                    </Tooltip>
                  )}
                  <Tooltip label="Liste filtrable par exercice et statut.">
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => void naviguer("missions")}
                    >
                      Voir les missions
                    </button>
                  </Tooltip>
                </div>
              </header>

              <div className="metrics metrics-grid metrics-grid-4">
                <Tooltip label="Ouvrir le portefeuille contribuables du cabinet.">
                  <button
                    type="button"
                    className="metric card-metric card-metric-btn"
                    onClick={() => void naviguer("clients")}
                  >
                    <div className="metric-top">
                      <div className="k">Clients</div>
                      <span className="metric-hint" aria-hidden="true">
                        →
                      </span>
                    </div>
                    <div className="v">{clients.length}</div>
                    <div className="metric-foot">Contribuables actifs</div>
                  </button>
                </Tooltip>
                <Tooltip label="Toutes les missions, tous exercices confondus.">
                  <button
                    type="button"
                    className="metric card-metric card-metric-btn"
                    onClick={() => void naviguer("missions")}
                  >
                    <div className="metric-top">
                      <div className="k">Missions</div>
                      <span className="metric-hint" aria-hidden="true">
                        →
                      </span>
                    </div>
                    <div className="v">{missions.length}</div>
                    <div className="metric-foot">
                      {dashStats.cloturees} clôturée
                      {dashStats.cloturees !== 1 ? "s" : ""}
                    </div>
                  </button>
                </Tooltip>
                <Tooltip label="Missions non clôturées — cadrage ou en cours de revue.">
                  <button
                    type="button"
                    className="metric card-metric card-metric-btn"
                    onClick={() => void naviguer("missions", { filtreStatut: "" })}
                  >
                    <div className="metric-top">
                      <div className="k">Actives</div>
                      <span className="metric-hint" aria-hidden="true">
                        →
                      </span>
                    </div>
                    <div className="v">{dashStats.actives.length}</div>
                    <div className="metric-foot">
                      {dashStats.enCours} en cours · {dashStats.cadrage} en
                      cadrage
                    </div>
                  </button>
                </Tooltip>
                <Tooltip
                  label={
                    quota?.bloque
                      ? "Capacité épuisée — contactez le billing ou attendez la prochaine période."
                      : quota
                        ? `${dashStats.restant} mission${dashStats.restant !== 1 ? "s" : ""} restante${dashStats.restant !== 1 ? "s" : ""} sur l’abonnement (${dashStats.quotaPct} % utilisés). Le quota compte les missions créées sur le mois en cours, tous statuts confondus — pas le total des missions listées.`
                        : "Quota indisponible."
                  }
                >
                  <button
                    type="button"
                    className={`metric card-metric card-metric-btn${quota?.alerte_80 ? " warn" : ""}${quota?.bloque ? " blocked" : ""}`}
                    onClick={() => {
                      if (!estLecteur && !quota?.bloque) {
                        void naviguer("nouvelle");
                      } else {
                        void naviguer("missions");
                      }
                    }}
                  >
                    <div className="metric-top">
                      <div className="k">Quota</div>
                      <span className="metric-hint" aria-hidden="true">
                        →
                      </span>
                    </div>
                    <div className="v">
                      {quota
                        ? `${quota.missions_utilisees}/${quota.missions_incluses}`
                        : "—"}
                    </div>
                    {quota && (
                      <div
                        className="quota-mini"
                        aria-hidden="true"
                      >
                        <div
                          className="quota-mini-fill"
                          style={{ width: `${dashStats.quotaPct}%` }}
                        />
                      </div>
                    )}
                    <div className="metric-foot">
                      {quota?.bloque
                        ? "Bloqué"
                        : quota?.alerte_80
                          ? "Alerte capacité"
                          : "Créées ce mois-ci"}
                    </div>
                  </button>
                </Tooltip>
              </div>

              {actionsRetard.length > 0 && (
                <section
                  className="panel dense dash-retards"
                  aria-label="Actions en retard"
                >
                  <h3>Actions en retard ({actionsRetard.length})</h3>
                  <p className="muted">
                    Tous clients — suivi hors période de mission.
                  </p>
                  <ul className="dash-retards-list">
                    {actionsRetard.slice(0, 12).map((a) => (
                      <li key={a.id}>
                        <strong>
                          {a.contribuable_denomination ||
                            `Client #${a.contribuable_id}`}
                        </strong>
                        {" — "}
                        {a.libelle}
                        {a.echeance ? ` · éch. ${a.echeance}` : ""}
                        {a.contribuable_id != null && (
                          <>
                            {" "}
                            <button
                              type="button"
                              className="linkish"
                              onClick={() =>
                                void ouvrirClient(a.contribuable_id!)
                              }
                            >
                              Ouvrir fiche
                            </button>
                          </>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {pilotage && (
                <section
                  className="pilotage-zone"
                  aria-label="Pilotage portefeuille"
                >
                  <div className="pilotage-head">
                    <h3 className="pilotage-title">Pilotage portefeuille</h3>
                    <p className="pilotage-sub">
                      Risque cumulé, missions qui traînent, fiabilité des
                      sources.
                    </p>
                  </div>
                  <div className="pilotage-grid">
                    <article className="panel dense pilotage-card">
                      <h4 className="pilotage-card-title">
                        Exposition par client
                        <span className="pilotage-count">
                          {pilotage.exposition_par_client.length}
                        </span>
                      </h4>
                      <ul className="pilotage-list">
                        {pilotage.exposition_par_client.map((e) => (
                          <li key={e.contribuable_id}>
                            <button
                              type="button"
                              className="pilotage-row"
                              onClick={() =>
                                void ouvrirClient(e.contribuable_id)
                              }
                            >
                              <span className="pilotage-row-nom">
                                {e.denomination}
                              </span>
                              <span className="pilotage-row-meta">
                                {e.nb_risques_ouverts} risque
                                {e.nb_risques_ouverts !== 1 ? "s" : ""} ·
                                score {e.score}
                              </span>
                              <span className="pilotage-row-montant">
                                {fmtMontant(e.exposition_ouverte)} FCFA
                              </span>
                            </button>
                          </li>
                        ))}
                        {!pilotage.exposition_par_client.length && (
                          <li className="pilotage-vide">
                            Aucun risque ouvert au portefeuille.
                          </li>
                        )}
                      </ul>
                    </article>

                    <article className="panel dense pilotage-card">
                      <h4 className="pilotage-card-title">
                        Missions inactives &gt;30 j
                        <span className="pilotage-count">
                          {pilotage.missions_a_cloturer.length}
                        </span>
                      </h4>
                      <ul className="pilotage-list">
                        {pilotage.missions_a_cloturer.map((m) => (
                          <li key={m.mission_id}>
                            <button
                              type="button"
                              className="pilotage-row"
                              onClick={() => void ouvrirMission(m.mission_id)}
                            >
                              <span className="pilotage-row-nom">
                                {m.denomination}
                              </span>
                              <span className="pilotage-row-meta">
                                Exercice {m.exercice}
                              </span>
                              <span className="pilotage-row-alerte">
                                {m.jours_inactivite} j d&apos;inactivité
                              </span>
                            </button>
                          </li>
                        ))}
                        {!pilotage.missions_a_cloturer.length && (
                          <li className="pilotage-vide">
                            Aucune mission en cours inactive.
                          </li>
                        )}
                      </ul>
                    </article>

                    <article className="panel dense pilotage-card">
                      <h4 className="pilotage-card-title">
                        Alertes fiabilité source
                        <span className="pilotage-count">
                          {pilotage.alertes_source.length}
                        </span>
                      </h4>
                      <ul className="pilotage-list">
                        {pilotage.alertes_source.map((a) => (
                          <li key={a.mission_id}>
                            <button
                              type="button"
                              className="pilotage-row"
                              onClick={() => void ouvrirMission(a.mission_id)}
                            >
                              <span className="pilotage-row-nom">
                                {a.denomination}
                              </span>
                              <span className="pilotage-row-meta">
                                Exercice {a.exercice}
                              </span>
                              <span className="pilotage-row-alerte">
                                {a.codes_alerte.join(", ")}
                              </span>
                            </button>
                          </li>
                        ))}
                        {!pilotage.alertes_source.length && (
                          <li className="pilotage-vide">
                            Aucune alerte sur les sources FEC contrôlées.
                          </li>
                        )}
                      </ul>
                    </article>

                    <article className="panel dense pilotage-card">
                      <h4 className="pilotage-card-title">
                        Risques en retard
                        <span className="pilotage-count warn">
                          {pilotage.risques_en_retard.total}
                        </span>
                      </h4>
                      <ul className="pilotage-list">
                        {pilotage.risques_en_retard.top.map((r) => (
                          <li key={r.risque_id}>
                            <button
                              type="button"
                              className="pilotage-row"
                              onClick={() =>
                                void ouvrirClient(r.contribuable_id)
                              }
                            >
                              <span className="pilotage-row-nom">
                                {r.denomination}
                              </span>
                              <span className="pilotage-row-meta">
                                {r.libelle}
                                {r.echeance ? ` · éch. ${r.echeance}` : ""}
                              </span>
                              <span className="pilotage-row-montant">
                                {fmtMontant(r.montant_estime)} FCFA
                              </span>
                            </button>
                          </li>
                        ))}
                        {!pilotage.risques_en_retard.total && (
                          <li className="pilotage-vide">
                            Aucun risque avec échéance dépassée.
                          </li>
                        )}
                      </ul>
                    </article>

                    <article className="panel dense pilotage-card">
                      <h4 className="pilotage-card-title">
                        Échéances déclaratives
                        <span
                          className={
                            pilotage.echeances_portefeuille.total
                              ? "pilotage-count warn"
                              : "pilotage-count"
                          }
                        >
                          {pilotage.echeances_portefeuille.total}
                        </span>
                      </h4>
                      <ul className="pilotage-list">
                        {pilotage.echeances_portefeuille.lignes.map((e) => (
                          <li
                            key={`${e.contribuable_id}-${e.code}-${e.date_limite}`}
                          >
                            <button
                              type="button"
                              className="pilotage-row"
                              onClick={() =>
                                void ouvrirClient(e.contribuable_id)
                              }
                            >
                              <span className="pilotage-row-nom">
                                {fmtDateFr(e.date_limite)} · {e.denomination}
                              </span>
                              <span className="pilotage-row-meta">
                                {e.libelle}
                              </span>
                              <span
                                className={
                                  e.statut === "depassee"
                                    ? "pilotage-badge depasse"
                                    : "pilotage-badge imminent"
                                }
                              >
                                {e.statut === "depassee"
                                  ? "Dépassé"
                                  : "Imminent"}
                              </span>
                            </button>
                          </li>
                        ))}
                        {!pilotage.echeances_portefeuille.total && (
                          <li className="pilotage-vide">
                            Aucune échéance déclarative imminente sur 30 jours.
                          </li>
                        )}
                      </ul>
                    </article>

                    <article className="panel dense pilotage-card">
                      <h4 className="pilotage-card-title">
                        Relances client
                        <span
                          className={
                            pilotage.relances_circularisation.items_a_relancer
                              ? "pilotage-count warn"
                              : "pilotage-count"
                          }
                        >
                          {pilotage.relances_circularisation.items_a_relancer}
                        </span>
                      </h4>
                      <p className="pilotage-relances-totaux">
                        {pilotage.relances_circularisation.missions_concernees}{" "}
                        mission(s) ·{" "}
                        {pilotage.relances_circularisation.items_en_attente}{" "}
                        item(s) en attente ·{" "}
                        {pilotage.relances_circularisation.items_a_relancer} à
                        relancer
                      </p>
                      <ul className="pilotage-list">
                        {pilotage.relances_circularisation.missions.map(
                          (m) => (
                            <li key={m.mission_id}>
                              <button
                                type="button"
                                className="pilotage-row"
                                onClick={() =>
                                  void ouvrirMission(m.mission_id)
                                }
                              >
                                <span className="pilotage-row-nom">
                                  {m.client}
                                </span>
                                <span className="pilotage-row-meta">
                                  Ex. {m.exercice} · {m.en_attente} en attente
                                  · {m.recu} reçu(s)
                                  {m.plus_ancienne_attente
                                    ? ` · depuis ${fmtDateFr(m.plus_ancienne_attente)}`
                                    : ""}
                                </span>
                                {m.a_relancer > 0 ? (
                                  <span className="pilotage-badge relance">
                                    {m.a_relancer} à relancer
                                  </span>
                                ) : (
                                  <span className="pilotage-badge attente">
                                    En attente
                                  </span>
                                )}
                              </button>
                            </li>
                          ),
                        )}
                        {!pilotage.relances_circularisation
                          .missions_concernees && (
                          <li className="pilotage-vide">
                            Aucune réponse client en attente sur les missions
                            ouvertes.
                          </li>
                        )}
                      </ul>
                    </article>
                  </div>
                </section>
              )}

              {supervision && (
                <section
                  className="pilotage-zone"
                  aria-label="Supervision des missions"
                >
                  <div className="pilotage-head">
                    <h3 className="pilotage-title">
                      Supervision des missions
                    </h3>
                    <p className="pilotage-sub">
                      Où en est chaque mission active : temps, visas,
                      circularisation.
                    </p>
                  </div>
                  <article className="panel dense pilotage-card">
                    <div className="missions-table-wrap">
                      <table className="missions-table supervision-table">
                        <thead className="missions-thead">
                          <tr>
                            <th>Client</th>
                            <th className="missions-th-ex">Exercice</th>
                            <th>Statut</th>
                            <th>Heures</th>
                            <th>Visas</th>
                            <th>Alertes</th>
                          </tr>
                        </thead>
                        <tbody>
                          {supervision.missions.map((m) => (
                            <tr
                              key={m.mission_id}
                              className="missions-tr"
                              onClick={() => void ouvrirMission(m.mission_id)}
                            >
                              <td>{m.contribuable}</td>
                              <td className="missions-th-ex">{m.exercice}</td>
                              <td>
                                <span className={`badge statut-${m.statut}`}>
                                  {libelleStatut(m.statut)}
                                </span>
                              </td>
                              <td>{m.heures_totales} h</td>
                              <td>{m.phases_completes}/4</td>
                              <td>
                                {m.alertes.length ? (
                                  m.alertes.map((a) => (
                                    <span
                                      key={a}
                                      className="pilotage-badge relance"
                                    >
                                      {a}
                                    </span>
                                  ))
                                ) : (
                                  <span className="pilotage-badge ok">
                                    RAS
                                  </span>
                                )}
                              </td>
                            </tr>
                          ))}
                          {!supervision.missions.length && (
                            <tr>
                              <td colSpan={6} className="pilotage-vide">
                                Aucune mission active au portefeuille.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                    <p className="pilotage-relances-totaux">
                      {supervision.synthese.missions_actives} mission(s)
                      active(s) · {supervision.synthese.heures_totales} h
                      saisies · {supervision.synthese.sans_aucun_visa} sans
                      aucun visa ·{" "}
                      {supervision.synthese.restitution_non_visee} restitution
                      (s) non visée(s) ·{" "}
                      {supervision.synthese.items_a_relancer} item(s) à
                      relancer
                    </p>
                  </article>
                </section>
              )}

              {dashStats.parStatut.size > 0 && (
                <div className="status-strip" aria-label="Répartition par statut">
                  <span className="status-strip-label">Statuts</span>
                  {[...dashStats.parStatut.entries()].map(([statut, n]) => (
                    <Tooltip
                      key={statut}
                      label={`Filtrer les missions au statut « ${libelleStatut(statut)} ».`}
                    >
                      <button
                        type="button"
                        className={`status-chip statut-${statut}`}
                        onClick={() =>
                          void naviguer("missions", { filtreStatut: statut })
                        }
                      >
                        <span className={`badge statut-${statut}`}>
                          {libelleStatut(statut)}
                        </span>
                        <strong>{n}</strong>
                      </button>
                    </Tooltip>
                  ))}
                </div>
              )}

              <CentreAlertesVue
                jeton={session?.jeton ?? null}
                onOuvrirMission={(id) => void ouvrirMission(id)}
              />

              <MonTableauVue
                jeton={session?.jeton ?? null}
                onOuvrirMission={(id) => void ouvrirMission(id)}
              />

              <AgendaFiscalVue
                jeton={session?.jeton ?? null}
                onOuvrirMission={(id) => void ouvrirMission(id)}
              />

              <EcheancesCabinetVue
                jeton={session?.jeton ?? null}
                onOuvrirMission={(id) => void ouvrirMission(id)}
              />

              <RelancesCabinetVue
                jeton={session?.jeton ?? null}
                onOuvrirMission={(id) => void ouvrirMission(id)}
              />

              <ActionsCabinetVue
                jeton={session?.jeton ?? null}
                estLecteur={estLecteur}
                onOuvrirMission={(id) => void ouvrirMission(id)}
              />

              <RentabiliteCabinetVue
                jeton={session?.jeton ?? null}
                onOuvrirMission={(id) => void ouvrirMission(id)}
              />

              <DelaisCabinetVue jeton={session?.jeton ?? null} />

              <ClotureCabinetVue
                jeton={session?.jeton ?? null}
                onOuvrirMission={(id) => void ouvrirMission(id)}
              />

              <PointsConvenusCabinetVue
                jeton={session?.jeton ?? null}
                onOuvrirMission={(id) => void ouvrirMission(id)}
              />

              <ChargeCabinetVue jeton={session?.jeton ?? null} />

              <div className="dash-split">
                <section className="panel dense list-panel">
                  <div className="panel-head">
                    <div>
                      <h3 className="panel-title">Dernières missions</h3>
                      <p className="panel-sub">
                        Cliquez une ligne pour ouvrir la restitution.
                      </p>
                    </div>
                    <Tooltip label="Voir toutes les missions du cabinet.">
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => void naviguer("missions")}
                      >
                        Tout voir
                      </button>
                    </Tooltip>
                  </div>
                  <ul className="mission-list">
                    {missions.slice(0, 6).map((m) => (
                      <li key={m.id}>
                        <Tooltip
                          label={`Ouvrir la mission #${m.id} · ${m.contribuable_denomination} · exercice ${m.exercice}`}
                          side="bottom"
                        >
                          <button
                            type="button"
                            className="mission-row"
                            onClick={() => void ouvrirMission(m.id)}
                          >
                            <span className="mission-id">#{m.id}</span>
                            <span className="mission-name">
                              {m.contribuable_denomination}
                            </span>
                            <span className="mission-meta">
                              Exercice {m.exercice}
                            </span>
                            <span className={`badge statut-${m.statut}`}>
                              {libelleStatut(m.statut)}
                            </span>
                            {m.revue_partielle ? (
                              <span className="badge badge-partielle">
                                Revue partielle
                              </span>
                            ) : null}
                          </button>
                        </Tooltip>
                      </li>
                    ))}
                    {!missions.length && (
                      <li className="empty-state">
                        Aucune mission pour l&apos;instant.
                        {!estLecteur && (
                          <>
                            {" "}
                            <button
                              type="button"
                              className="linkish"
                              onClick={() => void naviguer("nouvelle")}
                            >
                              Créer la première mission
                            </button>
                          </>
                        )}
                      </li>
                    )}
                  </ul>
                </section>

                <section className="panel dense list-panel">
                  <div className="panel-head">
                    <div>
                      <h3 className="panel-title">Portefeuille</h3>
                      <p className="panel-sub">
                        Contribuables cloisonnés (RLS).
                      </p>
                    </div>
                    <Tooltip label="Ouvrir la liste complète des clients.">
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => void naviguer("clients")}
                      >
                        Tout voir
                      </button>
                    </Tooltip>
                  </div>
                  <ul className="mission-list client-list">
                    {clients.slice(0, 6).map((c) => {
                      const nMissions = missions.filter(
                        (m) => m.contribuable_id === c.id,
                      ).length;
                      return (
                        <li key={c.id}>
                          <Tooltip
                            label={
                              nMissions
                                ? `${nMissions} mission${nMissions > 1 ? "s" : ""} — voir le portefeuille.`
                                : "Aucun dossier encore — créer une mission pour ce client."
                            }
                            side="bottom"
                          >
                            <button
                              type="button"
                              className="mission-row client-row"
                              onClick={() => void naviguer("clients")}
                            >
                              <span className="mission-name">{c.denomination}</span>
                              <span className="mission-meta">
                                {c.ncc || c.forme || "—"}
                              </span>
                              <span className="client-count">
                                {nMissions} miss.
                              </span>
                            </button>
                          </Tooltip>
                        </li>
                      );
                    })}
                    {!clients.length && (
                      <li className="empty-state">
                        Aucun client pour l&apos;instant.
                        {!estLecteur && (
                          <>
                            {" "}
                            <button
                              type="button"
                              className="linkish"
                              onClick={() => {
                                void naviguer("client-nouveau");
                              }}
                            >
                              Ajouter un client
                            </button>
                          </>
                        )}
                      </li>
                    )}
                  </ul>
                </section>
              </div>
            </div>
          )}

          {vue === "clients" && (
            <ClientsVue
              clients={clients}
              missions={missions}
              estLecteur={estLecteur}
              onOuvrirClient={(id) => void ouvrirClient(id)}
              onNouveauClient={() => {
                void naviguer("client-nouveau");
              }}
              onNouvelleMission={(c) => {
                void (async () => {
                  await naviguer("nouvelle");
                  chargerContribuableDansWizard(c);
                })();
              }}
            />
          )}

          {vue === "client-nouveau" && session && (
            <ClientCreationVue
              jeton={session.jeton}
              busy={busy}
              clients={clients}
              onRetour={() => void naviguer("clients")}
              onCreer={creerClientSeul}
              onCreerPuisMission={creerClientPuisMission}
            />
          )}

          {vue === "client" && clientDetail && session && (
            <ClientFicheVue
              jeton={session.jeton}
              clientDetail={clientDetail}
              clientEdit={clientEdit}
              setClientEdit={setClientEdit}
              estLecteur={estLecteur}
              busy={busy}
              onRetour={() => void naviguer("clients")}
              onSauver={() => void sauverClient()}
              onOuvrirMission={(id) => void ouvrirMission(id)}
              onNouvelleMission={() => {
                void (async () => {
                  await naviguer("nouvelle");
                  chargerContribuableDansWizard(clientDetail);
                })();
              }}
              onRafraichir={() => void ouvrirClient(clientDetail.id)}
            />
          )}

          {vue === "missions" && (
            <MissionsVue
              missions={missions}
              filtreExercice={filtreExercice}
              filtreStatut={filtreStatut}
              estLecteur={estLecteur}
              busy={busy}
              onFiltrer={(opts) => void naviguer("missions", opts)}
              onOuvrirMission={(id) => void ouvrirMission(id)}
              onNouvelleMission={() => {
                setFiltreExercice("");
                setFiltreStatut("");
                void naviguer("nouvelle");
              }}
            />
          )}

          {vue === "equipe" && estAdmin && (
            <EquipeVue
              users={users}
              invitations={invitations}
              inviteEmail={inviteEmail}
              inviteRole={inviteRole}
              busy={busy}
              equipeMsg={equipeMsg}
              inviteToken={inviteToken}
              emailOutbox={emailOutbox}
              onInviteEmailChange={setInviteEmail}
              onInviteRoleChange={setInviteRole}
              onInviter={(e) => void inviter(e)}
              onCopierToken={() => void copierInviteToken()}
              onMasquerToken={() => setInviteToken(null)}
              onChangerRole={(id, role) => void changerRoleUtilisateur(id, role)}
              onRevoquerInvitation={(id) => void revoquerInvitation(id)}
            />
          )}

          {vue === "facturation" && session && (
            <FacturationVue jeton={session.jeton} estAdmin={estAdmin} />
          )}

          {vue === "compte" && session && (
            <CompteVue
              jeton={session.jeton}
              estAdmin={estAdmin}
              onDenominationChange={(d) =>
                setSession((s) => (s ? { ...s, tenant_denomination: d } : s))
              }
              onProfilSaved={() => {
                void chargerOnboarding(session.jeton);
                void chargerCabinetProfil(session.jeton);
              }}
              onOuvrirFacturation={() => void naviguer("facturation")}
            />
          )}

          {vue === "nouvelle" && (
            <div className="wizard">
              <header className="wizard-head">
                <div>
                  <p className="page-eyebrow">Nouvelle revue</p>
                  <h2 className="section-title label-with-tip">
                    {STEPS[step - 1]?.lbl ?? "Mission"}
                    {step === 3 && (
                      <InfoTip
                        label={PROCESS_TIPS.artefact}
                        ariaLabel="Aide : étape résultat"
                      />
                    )}
                    {step === 1 && (
                      <InfoTip
                        label={PROCESS_TIPS.epingleWizard}
                        ariaLabel="Aide : cadrage mission"
                      />
                    )}
                  </h2>
                  <p className="section-sub">
                    {step === 1 &&
                      "On ne remplit pas un formulaire — on cadre une lettre de mission : le client, l’engagement, le périmètre."}
                    {step === 2 &&
                      "Sources & data room de la mission — déposez des pièces de tout format, à tout moment ; une source comptable active unique alimente le moteur déterministe."}
                    {step === 3 &&
                      "Dossier de revue — synthèse, passage, risques et suivi."}
                  </p>
                </div>
                <div className="wizard-head-meta" aria-hidden="true">
                  Étape {step}/{STEPS.length}
                </div>
              </header>

              <div className="wizard-progress" aria-hidden="true">
                <i style={{ width: `${progressPct}%` }} />
              </div>

              <nav className="wizard-steps" aria-label="Étapes de la mission">
                {STEPS.map((s, idx) => {
                  const done = s.n < step || (s.n === 3 && !!restitution);
                  const active = step === s.n;
                  const reachable = s.n <= step || (s.n === 3 && !!restitution);
                  const stepTip =
                    s.n === 1
                      ? PROCESS_TIPS.epingleWizard
                      : s.n === 2
                        ? PROCESS_TIPS.sourceActive
                        : PROCESS_TIPS.artefact;
                  return (
                    <Tooltip key={s.n} label={stepTip} side="bottom">
                      <button
                        type="button"
                        className={`wizard-step${active ? " active" : ""}${done ? " done" : ""}`}
                        disabled={!reachable}
                        aria-current={active ? "step" : undefined}
                        onClick={() => {
                          if (reachable) setStep(s.n);
                        }}
                      >
                        <span className="wizard-step-n" aria-hidden="true">
                          {done && !active ? "✓" : s.n}
                        </span>
                        <span className="wizard-step-copy">
                          <span className="wizard-step-lbl">{s.lbl}</span>
                          <span className="wizard-step-desc">{s.desc}</span>
                        </span>
                        {idx < STEPS.length - 1 && (
                          <span className="wizard-step-rail" aria-hidden="true" />
                        )}
                      </button>
                    </Tooltip>
                  );
                })}
              </nav>

              {step === 1 && (
                <CadrageMissionVue
                  busy={busy}
                  quotaBloque={!!quota?.bloque}
                  missionStatus={missionStatus}
                  cabinet={session?.tenant_denomination ?? ""}
                  cabinetProfil={cabinetProfil}
                  clients={clients}
                  missions={missions}
                  contribIdExistant={contribIdExistant}
                  chargerContribuable={chargerContribuableDansWizard}
                  reinitialiserClient={reinitialiserClientCadrage}
                  onAllerClients={() => void naviguer("clients")}
                  onOuvrirMission={(id) => void ouvrirMission(id)}
                  exercice={exercice}
                  setExercice={setExercice}
                  typeEngagement={typeEngagement}
                  setTypeEngagement={setTypeEngagement}
                  regime={regime}
                  setRegime={setRegime}
                  forme={forme}
                  setForme={setForme}
                  exerciceFutur={exerciceFutur}
                  exercicePrescrit={exercicePrescrit}
                  prescriptionConfirmee={prescriptionConfirmee}
                  setPrescriptionConfirmee={setPrescriptionConfirmee}
                  resumeRisques={resumeRisques}
                  pointsOuverts={pointsOuverts}
                  perimetreImpots={perimetreImpots}
                  setPerimetreImpots={setPerimetreImpots}
                  seuilSignification={seuilSignification}
                  setSeuilSignification={setSeuilSignification}
                  exclusionsDeclarees={exclusionsDeclarees}
                  setExclusionsDeclarees={setExclusionsDeclarees}
                  objectifsLibelles={objectifsLibelles}
                  setObjectifsLibelles={setObjectifsLibelles}
                  crossBorder={crossBorder}
                  setCrossBorder={setCrossBorder}
                  typeEntite={typeEntite}
                  setTypeEntite={setTypeEntite}
                  onCreerMission={() => void creerMissionDepuisCadrage()}
                />
              )}

              {step > 1 && (
              <div className="panel dense wizard-panel">

                {/* Rappel consultatif au démarrage / à la reprise de la
                    mission : points « à faire » hérités des exercices
                    antérieurs — affiché seulement s'il y en a. */}
                {missionId != null && (
                  <PointsAnterieursVue
                    missionId={missionId}
                    jeton={session?.jeton}
                  />
                )}

                {/* Lettre de mission : document contractuel du CADRAGE —
                    disponible dès que la mission existe (statut cadrage),
                    et conservée aux étapes suivantes. */}
                {missionId != null && (
                  <LettreMissionVue
                    missionId={missionId}
                    jeton={session?.jeton}
                  />
                )}

                {step === 2 && (
                  <>
                    <div className="sources2-intro">
                      <p className="sources2-intro-lead">
                        La mission{missionId != null ? ` #${missionId}` : ""}{" "}
                        dispose de sa <strong>data room</strong> : déposez des
                        pièces de tout format, à tout moment — ici comme depuis
                        le poste de travail. Seule la{" "}
                        <strong>source active</strong>
                        <InfoTip
                          label={PROCESS_TIPS.sourceActive}
                          ariaLabel="Aide : source active"
                        />{" "}
                        alimente <code>solde_compte</code> ; les autres pièces
                        enrichissent la revue sans écrasement.
                      </p>
                    </div>

                    <div className="wizard-context wizard-context-rich">
                      <div className="wizard-context-row">
                        <span className="wizard-context-k">Client</span>
                        <strong>{contribNom || "—"}</strong>
                        <span className="wizard-context-meta">
                          {contribForme === "pp" ? "PP" : "PM"}
                          {contribNcc ? ` · NCC ${contribNcc}` : ""}
                          {contribForme === "pm" && contribRccm
                            ? ` · RCCM ${contribRccm}`
                            : ""}
                          {contribForme === "pm" && contribDfe
                            ? ` · DFE ${contribDfe}`
                            : ""}
                        </span>
                      </div>
                      <div className="wizard-context-grid">
                        <div>
                          <span className="wizard-context-k">Exercice</span>
                          <strong>{exercice}</strong>
                        </div>
                        <div>
                          <span className="wizard-context-k">Engagement</span>
                          <strong>
                            {TYPES_ENGAGEMENT.find(
                              (t) => t.value === typeEngagement,
                            )?.label ?? typeEngagement}
                            {perimetreImpots.length > 0
                              ? ` · ${perimetreImpots.join(", ")}`
                              : " · complet"}
                          </strong>
                        </div>
                        <div>
                          <span className="wizard-context-k">Régime</span>
                          <strong>
                            {REGIMES_FISCAUX.find((r) => r.value === regime)
                              ?.label ?? regime}
                          </strong>
                        </div>
                        <div>
                          <span className="wizard-context-k">Forme</span>
                          <strong>
                            {contribForme === "pp" ? "EI" : forme}
                          </strong>
                        </div>
                        <div>
                          <span className="wizard-context-k">Identité</span>
                          <strong
                            className={
                              completude.complet ? "ok" : "err"
                            }
                          >
                            {completude.ok}/{completude.total}
                          </strong>
                        </div>
                        {secteur ? (
                          <div>
                            <span className="wizard-context-k">Secteur</span>
                            <strong>{secteur}</strong>
                          </div>
                        ) : null}
                        {typeEntite ? (
                          <div>
                            <span className="wizard-context-k">Type</span>
                            <strong>{typeEntite}</strong>
                          </div>
                        ) : null}
                        {crossBorder ? (
                          <div>
                            <span className="wizard-context-k">Transfrontalier</span>
                            <strong>Oui</strong>
                          </div>
                        ) : null}
                        {contribCentreImpots ? (
                          <div>
                            <span className="wizard-context-k">Centre impôts</span>
                            <strong>{contribCentreImpots}</strong>
                          </div>
                        ) : null}
                        {contribSiege ? (
                          <div>
                            <span className="wizard-context-k">Siège</span>
                            <strong>{contribSiege}</strong>
                          </div>
                        ) : null}
                      </div>
                    </div>

                    <section
                      className="sources2-section"
                      aria-labelledby="sources2-dataroom-titre"
                    >
                      <div className="sources2-head">
                        <h3
                          id="sources2-dataroom-titre"
                          className="sources2-titre label-with-tip"
                        >
                          Sources &amp; data room
                          <InfoTip
                            label={PROCESS_TIPS.annexes}
                            ariaLabel="Aide : data room de la mission"
                          />
                        </h3>
                        <span className="sources2-pastille">
                          {piecesMission.length} pièce
                          {piecesMission.length !== 1 ? "s" : ""}
                        </span>
                      </div>
                      <p className="sources2-note">
                        Tout format accepté — chaque dépôt est enregistré
                        immédiatement au dossier de la mission, sans remplacer
                        la source comptable active.
                      </p>
                      {missionId == null ? (
                        <p className="sources2-vide">
                          Créez d&apos;abord la mission à l&apos;étape Cadrage —
                          la data room est liée à la mission.
                        </p>
                      ) : (
                        <>
                          <div className="sources2-depot">
                            <label
                              className="sources2-type"
                              htmlFor="sources2-type-piece"
                            >
                              Type de pièce
                              <select
                                id="sources2-type-piece"
                                value={depotTypePiece}
                                disabled={depotBusy}
                                onChange={(e) =>
                                  setDepotTypePiece(
                                    e.target.value as TypePieceApi,
                                  )
                                }
                              >
                                {TYPES_PIECE_MISSION.map((t) => (
                                  <option key={t.id} value={t.id}>
                                    {t.label}
                                  </option>
                                ))}
                              </select>
                            </label>
                          </div>
                          <div
                            className={`field-upload balance-drop sources2-drop${depotDrag ? " drag" : ""}`}
                            onDragOver={(e) => {
                              e.preventDefault();
                              setDepotDrag(true);
                            }}
                            onDragLeave={() => setDepotDrag(false)}
                            onDrop={(e) => {
                              e.preventDefault();
                              setDepotDrag(false);
                              void deposerPiecesMission(e.dataTransfer.files);
                            }}
                          >
                            <label
                              htmlFor="sources2-files"
                              className="field-upload-label"
                            >
                              <span className="field-upload-title">
                                {depotBusy
                                  ? "Dépôt en cours…"
                                  : "Déposer des pièces ou cliquer"}
                              </span>
                              <span className="field-upload-meta">
                                Plusieurs fichiers, tout format — type courant
                                :{" "}
                                {TYPES_PIECE_MISSION.find(
                                  (t) => t.id === depotTypePiece,
                                )?.label ?? depotTypePiece}
                              </span>
                            </label>
                            <input
                              id="sources2-files"
                              type="file"
                              multiple
                              disabled={depotBusy}
                              onChange={(e) => {
                                void deposerPiecesMission(e.target.files);
                                e.target.value = "";
                              }}
                            />
                          </div>
                          {depotMsg && !depotBusy && (
                            <p className="sources2-msg" role="status">
                              {depotMsg}
                            </p>
                          )}
                          {depotErr && !depotBusy && (
                            <p className="sources2-err" role="alert">
                              {depotErr}
                            </p>
                          )}
                          {piecesMission.length > 0 ? (
                            <ul
                              className="sources2-pieces"
                              aria-label="Pièces de la mission"
                            >
                              {piecesMission.map((p) => (
                                <li key={p.id}>
                                  <div className="sources2-piece-infos">
                                    <strong className="sources2-piece-nom">
                                      {p.nom_fichier}
                                      {p.role === "source_active" && (
                                        <span className="sources2-badge-source">
                                          Source active
                                        </span>
                                      )}
                                    </strong>
                                    <span className="sources2-piece-meta">
                                      {TYPES_PIECE_MISSION.find(
                                        (t) => t.id === p.type_piece,
                                      )?.label ??
                                        p.type_piece ??
                                        "—"}
                                      {p.cree_le
                                        ? ` · déposée le ${String(p.cree_le).slice(0, 10)}`
                                        : ""}
                                    </span>
                                  </div>
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <p className="sources2-vide">
                              Aucune pièce pour l&apos;instant — le parcours
                              n&apos;est pas bloqué : vous pourrez ajouter des
                              sources à tout moment, ici ou depuis le poste de
                              travail.
                            </p>
                          )}
                          {missionId != null && (
                            <CompletudeDataRoomVue
                              missionId={missionId}
                              jeton={session?.jeton}
                              version={piecesMission.length}
                            />
                          )}
                        </>
                      )}
                    </section>

                    {contribIdExistant != null && (
                      <aside
                        className="sources-identite-dossier"
                        aria-label="Pièces d'identité du client"
                      >
                        <div className="sources2-head">
                          <h3 className="sources2-titre">
                            Dossier identité client
                          </h3>
                          <span className="sources2-pastille muted">
                            Hors moteur · informatif
                          </span>
                        </div>
                        <p className="field-hint">
                          NCC, centre, secteur et pièces DFE/RCCM viennent de la
                          fiche — ils ne remplacent pas la source comptable
                          active ci-dessous.
                        </p>
                        {piecesIdentiteClient.length > 0 ? (
                          <ul className="sources-identite-pieces">
                            {piecesIdentiteClient.map((p) => (
                              <li key={p.id}>
                                <strong>
                                  {TYPES_PIECE_CONTRIBUABLE.find(
                                    (t) => t.id === p.type_piece,
                                  )?.label ?? p.type_piece}
                                </strong>
                                <span>{p.nom_fichier}</span>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="picker-hint">
                            Aucune pièce d&apos;identité sur la fiche — vous
                            pouvez les joindre depuis Clients.
                          </p>
                        )}
                      </aside>
                    )}

                    <section className="sources2-section" aria-labelledby="src-active-title">
                      <div className="sources2-head">
                        <h3
                          id="src-active-title"
                          className="sources2-titre label-with-tip"
                        >
                          Source active
                          <InfoTip
                            label={PROCESS_TIPS.sourceActive}
                            ariaLabel="Aide : source active"
                          />
                        </h3>
                        <span className="sources2-pastille">
                          Unique · vers le moteur
                        </span>
                      </div>
                      <p className="field-hint sources-kind-hint">
                        {sourceMeta.hint} Changer de type demande une
                        confirmation explicite — jamais de merge multi-sources.
                      </p>

                    <div className="sources-kinds" role="tablist" aria-label="Type de source active">
                      {SOURCES_COMPTABLES.map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          role="tab"
                          aria-selected={sourceComptable === s.id}
                          className={`sources-kind${sourceComptable === s.id ? " active" : ""}${s.prioritaire ? " prioritaire" : ""}`}
                          onClick={() => choisirSourceComptable(s.id)}
                        >
                          <span className="sources-kind-name">{s.label}</span>
                          <span className="sources-kind-meta">
                            {s.prioritaire ? "Recommandé · " : "Alternative · "}
                            {s.hint.split("—")[0].trim()}
                          </span>
                        </button>
                      ))}
                    </div>

                    {sourceComptable === "balance" && (
                      <>
                        <div className="balance-source-tabs" role="tablist">
                          <button
                            type="button"
                            role="tab"
                            aria-selected={
                              !sourceDataroomOnglet && balanceSource === "json"
                            }
                            className={`balance-source-tab${!sourceDataroomOnglet && balanceSource === "json" ? " active" : ""}`}
                            onClick={() => {
                              setSourceDataroomOnglet(false);
                              setBalanceSource("json");
                            }}
                          >
                            Éditeur JSON
                          </button>
                          <button
                            type="button"
                            role="tab"
                            aria-selected={
                              !sourceDataroomOnglet &&
                              balanceSource === "fichier"
                            }
                            className={`balance-source-tab${!sourceDataroomOnglet && balanceSource === "fichier" ? " active" : ""}`}
                            onClick={() => {
                              setSourceDataroomOnglet(false);
                              setBalanceSource("fichier");
                            }}
                          >
                            Fichier CSV / Excel
                          </button>
                          <button
                            type="button"
                            role="tab"
                            aria-selected={sourceDataroomOnglet}
                            className={`balance-source-tab${sourceDataroomOnglet ? " active" : ""}`}
                            onClick={() => setSourceDataroomOnglet(true)}
                          >
                            Depuis le Data Room
                          </button>
                        </div>

                        <div className="balance-jeux">
                          <p className="picker-kicker">Jeux FICTIF (calage)</p>
                          <div className="picker-chips">
                            {JEUX_BALANCE.map((j) => (
                              <Tooltip key={j.id} label={j.hint} side="bottom">
                                <button
                                  type="button"
                                  className={`picker-chip${jeuBalanceId === j.id && balanceSource === "json" ? " selected" : ""}`}
                                  onClick={() => chargerJeuBalance(j.id)}
                                >
                                  <span className="picker-chip-name">
                                    {j.label}
                                  </span>
                                  <span className="picker-chip-meta">
                                    {j.hint}
                                  </span>
                                </button>
                              </Tooltip>
                            ))}
                          </div>
                        </div>

                        {!sourceDataroomOnglet && balanceSource === "json" && (
                          <div className="field field-area is-filled">
                            <div className="field-control">
                              <textarea
                                id="balance"
                                className="field-input field-textarea"
                                spellCheck={false}
                                value={balanceJson}
                                onChange={(e) => {
                                  setBalanceJson(e.target.value);
                                  setJeuBalanceId("");
                                  setSourceActiveFigee(true);
                                }}
                                placeholder=" "
                              />
                              <label className="field-label" htmlFor="balance">
                                Lignes (JSON)
                              </label>
                            </div>
                            <p className="field-hint">
                              Format :{" "}
                              <code>{`{ "lignes": [{ "compte", "libelle", "debit", "credit" }] }`}</code>
                            </p>
                          </div>
                        )}

                        {!sourceDataroomOnglet && balanceSource === "fichier" && (
                          <div
                            className={`field-upload balance-drop${balanceDrag ? " drag" : ""}${balanceFile ? " has-file" : ""}`}
                            onDragOver={(e) => {
                              e.preventDefault();
                              setBalanceDrag(true);
                            }}
                            onDragLeave={() => setBalanceDrag(false)}
                            onDrop={(e) => {
                              e.preventDefault();
                              setBalanceDrag(false);
                              const f = e.dataTransfer.files?.[0] ?? null;
                              lireFichierBalance(f);
                            }}
                          >
                            <label
                              htmlFor="balance-file"
                              className="field-upload-label"
                            >
                              <span className="field-upload-title">
                                {balanceFile
                                  ? balanceFile.name
                                  : "Déposer un fichier ou cliquer"}
                              </span>
                              <span className="field-upload-meta">
                                {balanceFile
                                  ? `${Math.round(balanceFile.size / 1024)} Ko · ${balanceFile.type || "fichier"}`
                                  : "CSV, TSV, TXT, JSON, XLSX, XLSM — en-tête compte,libelle,debit,credit"}
                              </span>
                            </label>
                            <input
                              id="balance-file"
                              type="file"
                              accept=".csv,.tsv,.txt,.json,.xlsx,.xlsm"
                              onChange={(e) =>
                                lireFichierBalance(e.target.files?.[0] ?? null)
                              }
                            />
                            {balanceFile && (
                              <button
                                type="button"
                                className="linkish balance-clear"
                                onClick={() => {
                                  lireFichierBalance(null);
                                  setBalanceSource("json");
                                }}
                              >
                                Retirer le fichier
                              </button>
                            )}
                          </div>
                        )}

                        {balanceExcelSeul && (
                          <p className="hint" role="status">
                            Fichier Excel : l’aperçu local est limité — le
                            contrôle d’équilibre sera fait côté serveur à
                            l’import.
                          </p>
                        )}
                      </>
                    )}

                    {sourceComptable !== "balance" && (
                      <div className="balance-source-tabs" role="tablist">
                        <button
                          type="button"
                          role="tab"
                          aria-selected={!sourceDataroomOnglet}
                          className={`balance-source-tab${!sourceDataroomOnglet ? " active" : ""}`}
                          onClick={() => setSourceDataroomOnglet(false)}
                        >
                          Fichier {sourceMeta.short}
                        </button>
                        <button
                          type="button"
                          role="tab"
                          aria-selected={sourceDataroomOnglet}
                          className={`balance-source-tab${sourceDataroomOnglet ? " active" : ""}`}
                          onClick={() => setSourceDataroomOnglet(true)}
                        >
                          Depuis le Data Room
                        </button>
                      </div>
                    )}

                    {sourceComptable !== "balance" && !sourceDataroomOnglet && (
                      <div
                        className={`field-upload balance-drop${sourceAltDrag ? " drag" : ""}${sourceAltFile ? " has-file" : ""}`}
                        onDragOver={(e) => {
                          e.preventDefault();
                          setSourceAltDrag(true);
                        }}
                        onDragLeave={() => setSourceAltDrag(false)}
                        onDrop={(e) => {
                          e.preventDefault();
                          setSourceAltDrag(false);
                          lireFichierSourceAlt(
                            e.dataTransfer.files?.[0] ?? null,
                          );
                        }}
                      >
                        <label
                          htmlFor="source-alt-file"
                          className="field-upload-label"
                        >
                          <span className="field-upload-title">
                            {sourceAltFile
                              ? sourceAltFile.name
                              : `Déposer ${sourceMeta.label}`}
                          </span>
                          <span className="field-upload-meta">
                            {sourceAltFile
                              ? `${Math.round(sourceAltFile.size / 1024)} Ko — import via /source-active`
                              : `Formats : ${sourceMeta.accept} — validation serveur à l’import (pas de faux succès local)`}
                          </span>
                        </label>
                        <input
                          id="source-alt-file"
                          type="file"
                          accept={sourceMeta.accept}
                          onChange={(e) =>
                            lireFichierSourceAlt(e.target.files?.[0] ?? null)
                          }
                        />
                        {sourceAltFile && (
                          <button
                            type="button"
                            className="linkish balance-clear"
                            onClick={() => lireFichierSourceAlt(null)}
                          >
                            Retirer le fichier
                          </button>
                        )}
                      </div>
                    )}

                    {sourceDataroomOnglet && (
                      <div className="sources-dataroom" role="tabpanel">
                        <p className="field-hint sources-dataroom-hint">
                          Réutilisez un fichier comptable (FEC, CSV, XLSX) déjà
                          déposé au coffre du client — sans re-téléverser.
                          Équilibre et format vérifiés par le serveur à
                          l’import.
                        </p>
                        {contribIdExistant == null ? (
                          <p className="sources-dataroom-vide">
                            Sélectionnez un client existant à l’étape 1 — le
                            Data Room appartient à la fiche client.
                          </p>
                        ) : dataroomEtat === "chargement" ? (
                          <p className="sources-dataroom-vide" role="status">
                            Chargement du Data Room…
                          </p>
                        ) : dataroomEtat === "erreur" ? (
                          <p className="sources-dataroom-erreur" role="alert">
                            Impossible de charger le Data Room du client —
                            rouvrez l’étape ou réessayez depuis la fiche
                            client.
                          </p>
                        ) : dataroomPieces.length === 0 ? (
                          <p className="sources-dataroom-vide">
                            Aucun fichier comptable au Data Room — déposez un
                            FEC au coffre du client.
                          </p>
                        ) : (
                          <ul className="sources-dataroom-liste">
                            {dataroomPieces.map((p) => (
                              <li
                                key={p.id}
                                className={`sources-dataroom-piece${sourceDataroomPiece?.id === p.id ? " selected" : ""}`}
                              >
                                <div className="sources-dataroom-infos">
                                  <strong className="sources-dataroom-nom">
                                    {p.nom_fichier}
                                  </strong>
                                  <span className="sources-dataroom-meta">
                                    <span
                                      className={`sources-dataroom-badge fmt-${p.format}`}
                                    >
                                      {p.format.toUpperCase()}
                                    </span>
                                    {fmtTaillePiece(p.taille_octets)}
                                    {p.cree_le
                                      ? ` · ${String(p.cree_le).slice(0, 10)}`
                                      : ""}
                                  </span>
                                </div>
                                <button
                                  type="button"
                                  className="sources-dataroom-utiliser"
                                  onClick={() => utiliserPieceDataroom(p)}
                                  disabled={sourceDataroomPiece?.id === p.id}
                                >
                                  {sourceDataroomPiece?.id === p.id
                                    ? "Source choisie"
                                    : "Utiliser comme source"}
                                </button>
                              </li>
                            ))}
                          </ul>
                        )}
                        {sourceDataroomPiece && (
                          <div className="balance-insight ok" role="status">
                            <p className="sources-alt-ready">
                              Source active prête :{" "}
                              <strong>
                                {sourceDataroomPiece.nom_fichier}
                              </strong>{" "}
                              (Data Room). L’import passe par le même pipeline
                              serveur (<code>/source-depuis-piece</code>) —
                              aucun re-téléversement.
                            </p>
                          </div>
                        )}
                      </div>
                    )}

                    {balanceAnalyseActive && (
                      <div
                        className={`balance-insight${balanceAnalyseActive.ok ? " ok" : " bad"}`}
                      >
                        <div className="balance-insight-head">
                          <span className="picker-kicker">
                            Analyse pré-import
                          </span>
                          <span className="balance-preview-meta">
                            Structure locale — aucun calcul fiscal
                          </span>
                        </div>
                        <div className="balance-metrics">
                          <div className="balance-metric">
                            <span className="k">Lignes</span>
                            <strong>{balanceAnalyseActive.nbLignes}</strong>
                          </div>
                          <div className="balance-metric">
                            <span className="k">Débit</span>
                            <strong>
                              {fmtXof(balanceAnalyseActive.totalDebit)}
                            </strong>
                          </div>
                          <div className="balance-metric">
                            <span className="k">Crédit</span>
                            <strong>
                              {fmtXof(balanceAnalyseActive.totalCredit)}
                            </strong>
                          </div>
                          <div className="balance-metric">
                            <span className="k">Équilibre</span>
                            <strong
                              className={
                                balanceAnalyseActive.equilibre ? "ok" : "err"
                              }
                            >
                              {balanceAnalyseActive.equilibre
                                ? "OK"
                                : `Écart ${fmtXof(balanceAnalyseActive.ecart)}`}
                            </strong>
                          </div>
                        </div>

                        {balanceAnalyseActive.couverture.length > 0 && (
                          <div className="balance-classes">
                            <span className="picker-kicker">
                              Couverture classes 1–7
                            </span>
                            <div className="balance-class-chips">
                              {balanceAnalyseActive.couverture.map((c) => (
                                <Tooltip
                                  key={c.classe}
                                  label={
                                    c.presente
                                      ? `${c.label} — ${c.n} compte(s)`
                                      : `${c.label} — absente (informationnel)`
                                  }
                                  side="bottom"
                                >
                                  <span
                                    className={`balance-class-chip${c.presente ? "" : " missing"}`}
                                  >
                                    Cl. {c.classe}
                                    <strong>{c.presente ? c.n : "—"}</strong>
                                  </span>
                                </Tooltip>
                              ))}
                            </div>
                          </div>
                        )}

                        {balanceAnalyseActive.checklistStructurelle.length >
                          0 && (
                          <ul className="ctrl-checklist compact" aria-label="Contrôles structurels">
                            {balanceAnalyseActive.checklistStructurelle.map(
                              (item) => (
                                <li
                                  key={item.id}
                                  className={`ctrl-check ctrl-${item.statut}`}
                                >
                                  <span className="ctrl-mark" aria-hidden="true" />
                                  <div>
                                    <strong>{item.label}</strong>
                                    {item.detail ? (
                                      <span>{item.detail}</span>
                                    ) : null}
                                  </div>
                                </li>
                              ),
                            )}
                          </ul>
                        )}

                        {balanceAnalyseActive.erreurs.length > 0 && (
                          <ul className="balance-alerts err">
                            {balanceAnalyseActive.erreurs.map((e) => (
                              <li key={e}>{e}</li>
                            ))}
                          </ul>
                        )}
                        {balanceAnalyseActive.avertissements.length > 0 && (
                          <ul className="balance-alerts warn">
                            {balanceAnalyseActive.avertissements.map((e) => (
                              <li key={e}>{e}</li>
                            ))}
                          </ul>
                        )}

                        {balanceAnalyseActive.lignes.length > 0 && (
                          <div className="balance-preview">
                            <div className="balance-preview-head">
                              <span className="picker-kicker">Aperçu</span>
                              <span className="balance-preview-meta">
                                {Math.min(
                                  10,
                                  balanceAnalyseActive.lignes.length,
                                )}
                                /{balanceAnalyseActive.lignes.length} lignes
                              </span>
                            </div>
                            <div className="balance-table-wrap">
                              <table className="balance-table">
                                <thead>
                                  <tr>
                                    <th>Compte</th>
                                    <th>Libellé</th>
                                    <th>Débit</th>
                                    <th>Crédit</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {balanceAnalyseActive.lignes
                                    .slice(0, 10)
                                    .map((l) => (
                                      <tr key={`${l.compte}-${l.libelle}`}>
                                        <td>
                                          <code>{l.compte}</code>
                                        </td>
                                        <td>{l.libelle}</td>
                                        <td className="num">
                                          {l.debit ? fmtXof(l.debit) : "—"}
                                        </td>
                                        <td className="num">
                                          {l.credit ? fmtXof(l.credit) : "—"}
                                        </td>
                                      </tr>
                                    ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {sourceComptable !== "balance" &&
                      !sourceDataroomOnglet &&
                      sourceAltFile && (
                      <div className="balance-insight ok" role="status">
                        <p className="sources-alt-ready">
                          Source active prête :{" "}
                          <strong>{sourceAltFile.name}</strong>. Le contrôle
                          d’équilibre / format sera fait par le serveur à
                          l’import (<code>/source-active</code>) — pas de
                          validation fiscale inventée ici.
                        </p>
                      </div>
                    )}
                    </section>

                    <div className="ctrl-panel">
                      <div className="ctrl-panel-head">
                        <span className="picker-kicker">
                          Checklist contrôleur
                        </span>
                        <span className="balance-preview-meta">
                          Avant lancement — cadrage, pas de règle fiscale
                        </span>
                      </div>
                      <ul className="ctrl-checklist">
                        {checklistControleur.map((item) => (
                          <li
                            key={item.id}
                            className={`ctrl-check ctrl-${item.statut}`}
                          >
                            <span className="ctrl-mark" aria-hidden="true" />
                            <div>
                              <strong>{item.label}</strong>
                              {item.detail ? <span>{item.detail}</span> : null}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>

                    {quota?.bloque && (
                      <p className="status err label-with-tip" role="alert">
                        Quota missions bloqué ({quota.missions_utilisees}/
                        {quota.missions_incluses}) — la création échouera.
                        <InfoTip
                          label={PROCESS_TIPS.quota}
                          ariaLabel="Aide : quota missions"
                        />
                      </p>
                    )}
                    <div className="cta-row desktop-only wizard-cta">
                      <button
                        type="button"
                        className="btn btn-ghost"
                        onClick={() => setStep(1)}
                      >
                        Retour
                      </button>
                      <Tooltip label="Ouvrir le poste de travail de la mission — accessible même sans pièce : les sources s'ajoutent à tout moment.">
                        <button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => void passerRestitution()}
                        >
                          Passer à la restitution
                        </button>
                      </Tooltip>
                      <Tooltip
                        label={
                          peutLancerRevue
                            ? PROCESS_TIPS.lancerRevue
                            : "Corrigez la source active (équilibre / format) ou déposez un fichier valide."
                        }
                      >
                        <button
                          type="button"
                          className="btn btn-primary"
                          disabled={!peutLancerRevue}
                          onClick={() => void lancerRevue()}
                        >
                          Lancer la revue
                        </button>
                      </Tooltip>
                      {!peutLancerRevue && !quota?.bloque && (
                        <span className="cta-hint">
                          Sans source active prête, la revue ne peut pas être
                          exécutée — vous pouvez néanmoins passer à la
                          restitution et compléter plus tard.
                        </span>
                      )}
                    </div>
                  </>
                )}

                {step === 3 && (
                  <>
                    {restitution ? (
                      <>
                      {/* Fil conducteur consultatif EN TÊTE : guide
                          pas-à-pas du process de revue, dérivé des
                          modules existants — lecture seule, l'humain
                          décide de l'ordre réel de ses travaux. */}
                      <FilConducteurVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                      />
                      <ResponsableMissionVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton ?? null}
                        estLecteur={estLecteur}
                      />
                      <RestitutionVue
                        restitution={restitution}
                        jeton={session?.jeton}
                        missionStatus={missionStatus}
                        versionEpinglee={versionEpinglee}
                        auditJournal={auditJournal}
                        busy={busy}
                        estLecteur={estLecteur}
                        collaborateurs={users}
                        lienMsg={lienMsg}
                        lienUrl={lienUrl}
                        onExport={(kind) => void exportFichier(kind)}
                        onAudit={() => void chargerAudit()}
                        onOuvrirClient={(cid) => void ouvrirClient(cid)}
                        onRestitutionRefresh={() => void rafraichirRestitution()}
                        onLienClient={
                          estLecteur
                            ? undefined
                            : () => void creerLienClient()
                        }
                        onCopierLien={
                          lienUrl ? () => void copierLienClient() : undefined
                        }
                        onCloturer={
                          estLecteur
                            ? undefined
                            : () => void changerStatutMission("cloturee")
                        }
                        onReouvrir={
                          estLecteur
                            ? undefined
                            : () => void changerStatutMission("en_cours")
                        }
                        onReprendreImport={
                          estLecteur
                            ? undefined
                            : () => {
                                setStep(2);
                                setMissionStatus({
                                  msg: "Reprise de l'import — déposez la source active puis lancez la revue.",
                                  err: false,
                                });
                              }
                        }
                      />
                      {/* Panorama consultatif de conformité :
                          bandeau compact agrégeant les STATUTS (pas
                          les montants) des vues fiscales ci-dessous,
                          classés en niveaux d'attention — aucun
                          score, le panorama oriente la lecture,
                          chaque volet s'apprécie dans sa vue
                          détaillée, l'humain décide. */}
                      <PanoramaConformiteVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                      />
                      {/* Seuil de matérialité consultatif calculé
                          depuis la balance (1 % CA, 5 % résultat,
                          1 % total bilan) + ciblage des travaux — la
                          retenue du seuil reste un clic explicite du
                          fiscaliste. */}
                      <MaterialiteVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                        estLecteur={estLecteur}
                      />
                      {/* Pont consultatif : diligences proposées
                          depuis les comptes ciblés par la matérialité
                          (mapping SYSCOHADA → diligence type) et les
                          risques non clos — l'ajout au programme de
                          travail reste un clic explicite du
                          fiscaliste. */}
                      <ProgrammeProposeVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                        estLecteur={estLecteur}
                      />
                      {/* Rapprochement consultatif TVA déclarée /
                          comptabilisée (comptes 443x/445x de la
                          balance) — la saisie des périodes déclarées
                          reste un clic explicite du fiscaliste. */}
                      <RapprochementTvaVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                        estLecteur={estLecteur}
                      />
                      {/* Complétude déclarative mensuelle : périodes
                          échues de l'exercice sans déclaration saisie
                          (TVA, impôts sur salaires) — consultatif, la
                          saisie ne prouve pas le dépôt à la DGI,
                          l'humain vérifie les quittances. */}
                      <CompletudeDeclarativeVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                      />
                      {/* Croisement consultatif CA comptable (70x) /
                          CA reconstitué depuis la TVA collectée
                          déclarée ÷ 18 % — le contrôle classique de
                          la DGI, offert au réviseur avant
                          l'administration. Approximation assumée,
                          écart « à expliquer », l'humain décide. */}
                      <CoherenceCaVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                      />
                      {/* Retenue à la source sur loyers : charges
                          locatives (comptes 622x de la balance) et
                          retenue théorique maximale indicative à
                          15 % — la qualité du bailleur (PP/PM,
                          régime) n'est pas connue de la balance,
                          seul l'humain qualifie et décide. */}
                      <RetenueLoyersVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                      />
                      {/* Retenue à la source sur honoraires :
                          rémunérations d'intermédiaires et de
                          conseils (comptes 632x de la balance) et
                          retenue théorique maximale indicative à
                          7,5 % — le régime du prestataire (résident
                          ou non, immatriculé ou non) n'est pas connu
                          de la balance, seul l'humain qualifie et
                          décide. */}
                      <RetenueHonorairesVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                      />
                      {/* Suivi pluriannuel des déficits reportables :
                          résultat fiscal théorique par exercice revu
                          du client (tableau de passage existant) et
                          cumul indicatif à imputation théorique
                          maximale — approximation assumée, seules
                          les liasses font foi, l'humain rapproche
                          et décide. */}
                      <DeficitsReportablesVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                      />
                      {/* Rapprochement acomptes IS / IS théorique :
                          l'IS théorique du tableau de passage (aucun
                          recalcul) rapproché des acomptes saisis —
                          solde indicatif de liquidation (reste à
                          payer ou crédit d'impôt indicatif),
                          approximation assumée : les quittances font
                          foi, l'humain liquide et décide. */}
                      <RapprochementAcomptesVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                      />
                      {/* Revue consultative de déductibilité des
                          charges (classe 6 de la balance) : points de
                          vigilance de réintégration IS selon un
                          référentiel déterministe du CGI ivoirien —
                          aucun calcul automatique, les soldes restent
                          à apprécier par le fiscaliste. */}
                      <DeductibiliteVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                      />
                      {/* Rapprochement consultatif des impôts sur
                          salaires déclarés / masse salariale
                          comptabilisée (comptes 66x, informatif
                          447x/42x) — la saisie des périodes déclarées
                          reste un clic explicite du fiscaliste. */}
                      <RapprochementSalairesVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                        estLecteur={estLecteur}
                      />
                      {/* Suivi consultatif des acomptes IS versés et
                          de la position de solde projetée (IS dû
                          estimé saisi par le fiscaliste, comptes
                          441x/444x informatifs) — la saisie reste un
                          clic explicite du fiscaliste. */}
                      <AcomptesVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                        estLecteur={estLecteur}
                      />
                      {/* Tableau de passage consultatif résultat
                          comptable → résultat fiscal (retraitements
                          saisis, report déficitaire plafonné au
                          bénéfice, IS théorique 25 %, signal IMF
                          indicatif) — la reprise comme IS dû estimé
                          reste un clic explicite du fiscaliste. */}
                      <ResultatFiscalVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                        estLecteur={estLecteur}
                      />
                      {/* Estimation consultative de la contribution
                          des patentes : droit sur le CA approché à
                          0,5 % des comptes 70x (plancher 300 000
                          FCFA, plafond indicatif) ; le droit sur la
                          valeur locative n'est pas calculable depuis
                          la balance — estimation partielle, lecture
                          seule, l'humain décide. */}
                      <PatenteVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                      />
                      {/* Panorama consultatif de la charge fiscale
                          estimée : agrégat des estimations déjà
                          calculées par les écrans ci-dessus (IS
                          théorique, patente partielle, impôts sur
                          salaires et TVA déclarés, position
                          d'acomptes) — aucun recalcul, total partiel
                          hors TVA collectée, l'humain décide. */}
                      <ChargeFiscaleVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                      />
                      {/* Suivi consultatif des contrôles fiscaux et
                          contentieux — délais de riposte LPF calculés,
                          la consignation reste un clic explicite du
                          fiscaliste. */}
                      <ControlesFiscauxVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                        estLecteur={estLecteur}
                      />
                      <DossierMissionVue
                        missionId={restitution.mission_id}
                        jeton={session?.jeton}
                      />
                      </>
                    ) : (
                      <>
                        <h2 className="section-title wizard-panel-title">
                          Restitution
                        </h2>
                        {!missionStatus?.err && (
                          <p className="empty-state">
                            Aucune restitution pour l&apos;instant. Lancez une
                            revue ou ouvrez une mission existante.
                          </p>
                        )}
                        {missionStatus && (
                          <p
                            className={`status${missionStatus.err ? " err" : ""}`}
                            role="status"
                          >
                            {missionStatus.msg}
                          </p>
                        )}
                      </>
                    )}
                    <div className="cta-row desktop-only wizard-cta">
                      {missionStatus?.err && !restitution && (
                        <button
                          type="button"
                          className="btn btn-primary"
                          onClick={() => setStep(etapeRetour ?? 1)}
                        >
                          Revenir au paramétrage
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn-ghost"
                        onClick={resetMission}
                      >
                        Nouvelle mission
                      </button>
                    </div>
                  </>
                )}
              </div>
              )}
            </div>
          )}
          </main>

          <div
            className={`drawer-backdrop${drawerOpen ? " open" : ""}`}
            onClick={() => setDrawerOpen(false)}
            aria-hidden={!drawerOpen}
          />

          <nav
            className={`bottom-nav${vue === "nouvelle" ? " is-wizard-hidden" : ""}`}
            aria-label="Navigation principale"
            aria-hidden={vue === "nouvelle"}
          >
            {bottomNavItems.map((n) => {
              const active = navItemActif(n.id);
              return (
                <button
                  key={n.id}
                  type="button"
                  className={`bottom-nav-item${active ? " is-active" : ""}`}
                  aria-label={n.label}
                  aria-current={active ? "page" : undefined}
                  disabled={vue === "nouvelle"}
                  tabIndex={vue === "nouvelle" ? -1 : undefined}
                  onClick={() => void naviguer(n.id)}
                >
                  <span className="bottom-nav-ico" aria-hidden="true">
                    {n.icon}
                  </span>
                  <span className="bottom-nav-label">{n.label}</span>
                </button>
              );
            })}
          </nav>

          {mobile && vue === "nouvelle" && step > 1 && (
            <div className="dock on" aria-label="Actions">
              {step === 2 && (
                <>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => setStep(1)}
                  >
                    Retour
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => void passerRestitution()}
                  >
                    Restitution
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={!peutLancerRevue}
                    onClick={() => void lancerRevue()}
                  >
                    Lancer la revue
                  </button>
                </>
              )}
              {step === 3 && (
                <>
                  {missionStatus?.err && !restitution && (
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={() => setStep(etapeRetour ?? 1)}
                    >
                      Revenir au paramétrage
                    </button>
                  )}
                  <button
                    type="button"
                    className={`btn ${missionStatus?.err && !restitution ? "btn-ghost" : "btn-primary"}`}
                    onClick={resetMission}
                  >
                    Nouvelle mission
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );
}
