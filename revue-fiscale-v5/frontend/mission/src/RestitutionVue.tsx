import { useEffect, useMemo, useRef, useState } from "react";
import { api, apiUpload, fmtMontant, telecharger } from "./api";
import {
  CODES_IMPOT_PIVOT,
  PERIMETRE_DONS_HINT,
  PERIMETRE_EXONERATIONS_HINT,
  extraireReglesDonsEtAllegements,
  tipImpot,
} from "./impotLabels";
import { libelleStatut } from "./MissionsVue";
import { PROCESS_TIPS } from "./processTips";
import { InfoTip, Tooltip } from "./Tooltip";
import {
  STATUTS_TRAITEMENT,
  classeBadgeTraitement,
  compterOuvertsClotures,
  libelleStatutTache,
  normaliserStatutTache,
  statutTacheVersTraitement,
  synthetiserTraitements,
  type StatutTache,
  type TraitementRisque,
} from "./risqueTraitement";
import { RapportArtifact } from "./RapportArtifact";
import { EcheancierFiscalVue } from "./EcheancierFiscalVue";
import { PilotageVue } from "./PilotageVue";
import { PrescriptionVue } from "./PrescriptionVue";
import { CivismeVue } from "./CivismeVue";
import { PlanActionsVue } from "./PlanActionsVue";
import { BilanClotureVue } from "./BilanClotureVue";
import type { AuditEntree, AuditJournal, ConclusionRestitution, Restitution } from "./types";

type CollaborateurOpt = {
  id: number;
  email: string;
  role?: string;
  actif?: boolean;
};

type SectionId = "synthese" | "passage" | "risques" | "rapport" | "audit";

const STATUTS_CONCLUSION = [
  { value: "conforme", label: "Conforme" },
  { value: "anomalie", label: "Anomalie" },
  { value: "sous_seuil", label: "Sous seuil" },
  { value: "non_verifiable", label: "Non vérifiable" },
  { value: "hors_perimetre", label: "Hors périmètre" },
] as const;

/** Conclusions à suivre inter-missions (hors conforme / hors périmètre). */
const STATUTS_SENSIBLES = new Set(["anomalie", "non_verifiable", "sous_seuil"]);

const TYPES_ENGAGEMENT = [
  { value: "autre", label: "Autre" },
  { value: "preventive", label: "Revue préventive" },
  { value: "cac", label: "Commissariat aux comptes" },
  { value: "due_diligence", label: "Due diligence" },
  { value: "assistance_controle", label: "Assistance à contrôle" },
] as const;

type PieceMissionOpt = {
  id: number;
  nom_fichier: string;
  role: string;
  type_piece?: string;
  cree_le?: string | null;
};

/** Types de pièce acceptés par le dépôt mission (backend socle). */
const TYPES_PIECE_MISSION = [
  { value: "balance", label: "Balance" },
  { value: "etats_financiers", label: "États financiers" },
  { value: "grand_livre", label: "Grand livre" },
  { value: "fec", label: "FEC" },
  { value: "autre", label: "Autre" },
] as const;

function libelleTypePieceMission(type?: string): string {
  return (
    TYPES_PIECE_MISSION.find((t) => t.value === type)?.label || type || "—"
  );
}

type ControleFecOccurrence = {
  ligne: number | null;
  valeur: string;
};

type ControleFec = {
  code: string;
  libelle: string;
  statut: "ok" | "alerte";
  compteur: number;
  echantillon: ControleFecOccurrence[];
};

type ControlesFecOut = {
  disponible: boolean;
  exercice?: number;
  controles: ControleFec[];
  cree_le: string | null;
};

type LigneRevueAnalytique = {
  compte: string;
  libelle: string | null;
  solde_n: number;
  solde_n1: number;
  variation: number;
  variation_pct: number | null;
  sens: string;
  classement: "apparition" | "disparition" | "variation_forte" | "stable";
};

type RevueAnalytiqueOut = {
  disponible: boolean;
  exercice_n: number;
  exercice_n1: number;
  mission_n1_id: number | null;
  lignes: LigneRevueAnalytique[];
  totaux_par_classe: Array<{
    classe: number;
    total_n: number;
    total_n1: number;
    variation: number;
  }>;
};

const REVUE_ANALYTIQUE_MAX_LIGNES = 30;

/* Note de synthèse de mission — executive summary IA versionné. */
type NoteSyntheseVersion = {
  id: number;
  mission_id: number;
  version: number;
  statut: "en_cours" | "disponible" | "echec";
  modele: string | null;
  erreur: string | null;
  auteur: string | null;
  cree_le: string | null;
};

type NoteConstat = {
  regle_id: string;
  resume: string;
  montant: string | null;
  gravite: "faible" | "moyenne" | "haute";
};

type NoteContenu = {
  contexte: string;
  constats: NoteConstat[];
  exposition: string;
  points_attention: string[];
  recommandations: string[];
};

type NoteSyntheseDetail = NoteSyntheseVersion & {
  contenu: NoteContenu | null;
};

/* Commentaire IA de revue analytique — versionné par mission. */
type CommentaireAnalytiqueVersion = {
  id: number;
  mission_id: number;
  version: number;
  statut: "en_cours" | "disponible" | "echec";
  modele: string | null;
  erreur: string | null;
  auteur: string | null;
  cree_le: string | null;
};

type CommentaireExplication = {
  poste: string;
  hypothese_explicative: string;
  question_a_poser_au_client: string;
  gravite: "faible" | "moyenne" | "haute";
};

type CommentaireContenu = {
  resume: string;
  explications: CommentaireExplication[];
  alertes_coherence: string[];
};

type CommentaireAnalytiqueDetail = CommentaireAnalytiqueVersion & {
  contenu: CommentaireContenu | null;
};

/* Suivi de circularisation — réponses client à la demande de renseignements. */
type SuiviStatut = "en_attente" | "recu" | "sans_objet";

type SuiviItem = {
  cle_item: string;
  libelle: string;
  statut: SuiviStatut;
  date_relance: string | null;
  derniere_relance_le: string | null;
  nb_relances: number;
  note: string | null;
  maj_le: string | null;
};

type SuiviSynthese = {
  total: number;
  en_attente: number;
  recu: number;
  sans_objet: number;
  a_relancer: number;
};

type SuiviOut = {
  items: SuiviItem[];
  synthese: SuiviSynthese;
};

/* Réponse client saisie pour un item de circularisation. */
type ReponseClient = {
  cle_item: string;
  contenu: string;
  pieces_recues: string | null;
  saisie_par: string;
  saisie_le: string;
  regle_id: string | null;
  statut_derniere_execution: string | null;
};

/* Temps passés par mission — pilotage de la rentabilité cabinet. */
type TempsPhase =
  | "cadrage"
  | "collecte"
  | "controles"
  | "restitution"
  | "suivi";

type TempsEntree = {
  id: number;
  collaborateur: string;
  phase: TempsPhase;
  date_jour: string;
  heures: string;
  note: string | null;
  saisi_le: string;
};

type TempsRecap = {
  entrees: TempsEntree[];
  total_heures: string;
  par_phase: Record<string, string>;
  par_collaborateur: Record<string, string>;
  valorisation: string | null;
};

/* Rentabilité : honoraires convenus, taux horaire, marge estimée. */
type RentabiliteMission = {
  honoraires: string | null;
  taux_horaire: string | null;
  total_heures: string;
  cout_estime: string | null;
  marge_estimee: string | null;
  taux_marge_pct: string | null;
};

const PHASES_TEMPS: Array<{ value: TempsPhase; label: string }> = [
  { value: "cadrage", label: "Cadrage" },
  { value: "collecte", label: "Collecte" },
  { value: "controles", label: "Contrôles" },
  { value: "restitution", label: "Restitution" },
  { value: "suivi", label: "Suivi" },
];

function libellePhaseTemps(phase: string): string {
  return PHASES_TEMPS.find((p) => p.value === phase)?.label ?? phase;
}

/* Visas de supervision — préparateur, réviseur, associé, par phase. */
type VisaRole = "preparateur" | "reviseur" | "associe";
type VisaPhase = "cadrage" | "collecte" | "controles" | "restitution";

type VisaMission = {
  role: VisaRole;
  vise_par: string;
  vise_le: string;
  commentaire: string | null;
};

type VisasEtat = {
  phases: Array<{ phase: VisaPhase; visas: VisaMission[]; complet: boolean }>;
  synthese: { phases_completes: number; total_visas: number };
};

const ROLES_VISA: Array<{ value: VisaRole; label: string }> = [
  { value: "preparateur", label: "Préparateur" },
  { value: "reviseur", label: "Réviseur" },
  { value: "associe", label: "Associé" },
];

/* Programme de travail — diligences standard par phase, avancement %. */
type DiligenceProgramme = {
  code: string;
  libelle: string;
  fait: boolean;
  fait_par: string | null;
  fait_le: string | null;
};

type ProgrammeEtat = {
  phases: Array<{
    phase: TempsPhase;
    diligences: DiligenceProgramme[];
    faites: number;
    total: number;
    avancement_pct: string;
  }>;
  synthese: { faites: number; total: number; avancement_pct: string };
};

/* Comparatif déterministe entre deux exécutions d'une mission. */
type ComparatifItem = {
  regle_id: string;
  avant: string | null;
  apres: string | null;
  montant_avant: string | null;
  montant_apres: string | null;
};

type ComparatifOut = {
  execution_a: { id: number; date: string | null };
  execution_b: { id: number; date: string | null };
  ameliorations: ComparatifItem[];
  degradations: ComparatifItem[];
  inchanges_a_risque: ComparatifItem[];
  nouveaux: ComparatifItem[];
  disparus: ComparatifItem[];
  synthese: {
    ameliorations: number;
    degradations: number;
    inchanges_a_risque: number;
    nouveaux: number;
    disparus: number;
    delta_montant_anomalies: string;
  };
};

const LIBELLES_STATUT_COMPARATIF: Record<string, string> = {
  conforme: "Conforme",
  anomalie: "Anomalie",
  sous_seuil: "Sous seuil",
  non_verifiable: "Non vérifiable",
  hors_perimetre: "Hors périmètre",
};

function libelleStatutComparatif(statut: string | null): string {
  if (!statut) return "—";
  return LIBELLES_STATUT_COMPARATIF[statut] ?? statut;
}

const STATUTS_SUIVI: Array<{ value: SuiviStatut; label: string }> = [
  { value: "en_attente", label: "En attente" },
  { value: "recu", label: "Reçu" },
  { value: "sans_objet", label: "Sans objet" },
];

function itemARelancer(it: SuiviItem): boolean {
  return (
    it.statut === "en_attente" &&
    !!it.date_relance &&
    it.date_relance <= new Date().toISOString().slice(0, 10)
  );
}

/* Contrôle qualité de pré-clôture — déterministe et consultatif. */
type ControleCloturePoint = {
  code: string;
  libelle: string;
  statut: "ok" | "attention" | "bloquant";
  detail: string;
};

type ControleClotureOut = {
  mission_id: number;
  statut_mission: string;
  points: ControleCloturePoint[];
  synthese: { ok: number; attention: number; bloquant: number };
  cloture_recommandee: boolean;
};

function libelleStatutControle(statut: ControleCloturePoint["statut"]): string {
  if (statut === "ok") return "OK";
  if (statut === "bloquant") return "Bloquant";
  return "Attention";
}

function libelleGraviteNote(g: string): string {
  const m: Record<string, string> = {
    haute: "Gravité haute",
    moyenne: "Gravité moyenne",
    faible: "Gravité faible",
  };
  return m[g] ?? g;
}

function badgeAnalytique(
  classement: LigneRevueAnalytique["classement"],
): { label: string; classe: string } | null {
  if (classement === "apparition") {
    return { label: "Apparition", classe: "apparition" };
  }
  if (classement === "disparition") {
    return { label: "Disparition", classe: "disparition" };
  }
  if (classement === "variation_forte") {
    return { label: "Variation forte", classe: "forte" };
  }
  return null;
}

type Props = {
  restitution: Restitution;
  jeton?: string | null;
  missionStatus?: { msg: string; err: boolean } | null;
  versionEpinglee?: { id: number; libelle?: string | null } | null;
  auditJournal?: AuditJournal | null;
  busy?: boolean;
  estLecteur?: boolean;
  /** Équipe cabinet déjà chargée (admin) — sinon fetch collaborateurs. */
  collaborateurs?: CollaborateurOpt[];
  onExport: (kind: "docx" | "pdf") => void;
  onAudit: () => void;
  /** Ouvre la fiche client (bandeau mission). */
  onOuvrirClient?: (contribuableId: number) => void;
  onLienClient?: () => void;
  onCopierLien?: () => void;
  lienMsg?: string | null;
  lienUrl?: string | null;
  onCloturer?: () => void;
  onReouvrir?: () => void;
  onReprendreImport?: () => void;
  onRestitutionRefresh?: () => void;
};

function libelleSens(sens: string | null | undefined): string {
  if (sens === "reintegration") return "Réintégration";
  if (sens === "deduction") return "Déduction";
  return sens || "—";
}

function libelleRisque(n: string | null | undefined): string {
  const m: Record<string, string> = {
    eleve: "Élevé",
    moyen: "Moyen",
    faible: "Faible",
  };
  return m[(n || "").toLowerCase()] ?? (n || "—");
}

function libelleActionAudit(action: string): string {
  const m: Record<string, string> = {
    creation_mission: "Création de mission",
    import_balance: "Import balance",
    execution_moteur: "Exécution moteur",
    changement_statut: "Changement de statut",
  };
  return m[action] ?? action;
}

function fmtHorodatage(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("fr-FR", {
    dateStyle: "short",
    timeStyle: "medium",
  });
}

function resumeCharge(entree: AuditEntree): string {
  const c = entree.charge_utile || {};
  if (entree.action === "changement_statut") {
    const a = String(c.statut_precedent || "?");
    const b = String(c.statut || "?");
    const d = c.declencheur ? ` · ${c.declencheur}` : "";
    return `${a} → ${b}${d}`;
  }
  if (entree.action === "execution_moteur") {
    const n = c.nb_conclusions != null ? `${c.nb_conclusions} conclusion(s)` : "";
    const e = c.execution_id != null ? `ex.#${c.execution_id}` : "";
    return [e, n].filter(Boolean).join(" · ") || "Exécution enregistrée";
  }
  if (entree.action === "import_balance") {
    const st = String(c.statut || "—");
    const n = c.nb_comptes != null ? `${c.nb_comptes} compte(s)` : "";
    return [st, n].filter(Boolean).join(" · ");
  }
  if (entree.action === "creation_mission") {
    const ex = c.exercice != null ? `Exercice ${c.exercice}` : "";
    const v =
      c.version_referentiel_id != null
        ? `réf. #${c.version_referentiel_id}`
        : "";
    return [ex, v].filter(Boolean).join(" · ") || "Mission créée";
  }
  const keys = Object.keys(c);
  if (!keys.length) return "—";
  return keys
    .slice(0, 3)
    .map((k) => `${k}=${String(c[k])}`)
    .join(" · ");
}

function conclusionSensible(c: ConclusionRestitution): boolean {
  const st = String(c.statut || "anomalie").toLowerCase();
  return STATUTS_SENSIBLES.has(st);
}

function intensiteScore(score: number, maxAttendus: number): number {
  if (maxAttendus <= 0) return score === 0 ? 0 : 100;
  return Math.min(100, Math.round((100 * score) / maxAttendus));
}

function libelleTraitement(
  statut: StatutTache,
  pieceAttendue?: string | null,
): string {
  return libelleStatutTache(statut, pieceAttendue);
}

function scrollPref(): ScrollBehavior {
  if (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    return "auto";
  }
  return "smooth";
}

const SECTIONS: Array<{ id: SectionId; label: string; tip: string }> = [
  {
    id: "synthese",
    label: "Synthèse",
    tip: "Priorités de revue et pipeline de traitement — triage humain, hors montants moteur.",
  },
  { id: "passage", label: "Passage", tip: PROCESS_TIPS.passage },
  {
    id: "risques",
    label: "Risques",
    tip: "Workspace réviseur : suivre chaque conclusion sans modifier le calcul déterministe.",
  },
  { id: "rapport", label: "Rapport", tip: PROCESS_TIPS.rapport },
  { id: "audit", label: "Audit", tip: PROCESS_TIPS.audit },
];

export function RestitutionVue({
  restitution: r,
  jeton,
  missionStatus,
  versionEpinglee,
  auditJournal,
  busy,
  estLecteur,
  collaborateurs: collaborateursProp,
  onExport,
  onAudit,
  onOuvrirClient,
  onLienClient,
  onCopierLien,
  lienMsg,
  lienUrl,
  onCloturer,
  onReouvrir,
  onReprendreImport,
  onRestitutionRefresh,
}: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [sectionActive, setSectionActive] = useState<SectionId>("synthese");
  const [filtreRisque, setFiltreRisque] = useState<string>("tous");
  const [filtreTraitement, setFiltreTraitement] = useState<string>("tous");
  const [filtreAuditAction, setFiltreAuditAction] = useState<string>("tous");
  const [acDetailOuvert, setAcDetailOuvert] = useState(false);
  const [alertesOuvertes, setAlertesOuvertes] = useState(false);
  const [filtreSensPassage, setFiltreSensPassage] = useState<string>("tous");
  const [noteDraft, setNoteDraft] = useState<Record<string, string>>({});
  const [pieces, setPieces] = useState<PieceMissionOpt[]>([]);
  const [fiabSource, setFiabSource] = useState<ControlesFecOut | null>(null);
  const [revueAnalytique, setRevueAnalytique] =
    useState<RevueAnalytiqueOut | null>(null);
  const [collaborateursLocaux, setCollaborateursLocaux] = useState<
    CollaborateurOpt[]
  >([]);
  const [patchErr, setPatchErr] = useState<string | null>(null);
  const [patchBusyId, setPatchBusyId] = useState<number | null>(null);
  const [validerBusyId, setValiderBusyId] = useState<number | null>(null);
  const [actionErrId, setActionErrId] = useState<number | null>(null);
  const [pointBusyId, setPointBusyId] = useState<number | null>(null);
  const [pointMsg, setPointMsg] = useState<{
    conclusionId: number;
    texte: string;
  } | null>(null);
  const [cadrageType, setCadrageType] = useState("autre");
  const [cadragePerimetre, setCadragePerimetre] = useState<string[]>([]);
  const [cadrageExclusions, setCadrageExclusions] = useState("");
  const [cadrageSeuil, setCadrageSeuil] = useState("");
  const [cadrageObjectifs, setCadrageObjectifs] = useState<string[]>([""]);
  const [cadrageBusy, setCadrageBusy] = useState(false);
  const [cadrageMsg, setCadrageMsg] = useState<string | null>(null);
  const [cadrageErr, setCadrageErr] = useState<string | null>(null);
  const [lettreBusy, setLettreBusy] = useState(false);
  const [lettreErr, setLettreErr] = useState<string | null>(null);
  const [demandeBusy, setDemandeBusy] = useState(false);
  const [demandeErr, setDemandeErr] = useState<string | null>(null);
  const [dossierBusy, setDossierBusy] = useState(false);
  const [dossierErr, setDossierErr] = useState<string | null>(null);
  const [courrierEnvoiBusy, setCourrierEnvoiBusy] = useState(false);
  const [courrierEnvoiErr, setCourrierEnvoiErr] = useState<string | null>(null);
  const [affirmationBusy, setAffirmationBusy] = useState(false);
  const [affirmationErr, setAffirmationErr] = useState<string | null>(null);
  const [comparatifOuvert, setComparatifOuvert] = useState(false);
  const [comparatif, setComparatif] = useState<ComparatifOut | null>(null);
  const [comparatifErr, setComparatifErr] = useState<string | null>(null);
  const [comparatifBusy, setComparatifBusy] = useState(false);
  const [suiviOuvert, setSuiviOuvert] = useState(false);
  const [suivi, setSuivi] = useState<SuiviOut | null>(null);
  const [suiviErr, setSuiviErr] = useState<string | null>(null);
  const [suiviBusyCle, setSuiviBusyCle] = useState<string | null>(null);
  const [suiviNotes, setSuiviNotes] = useState<Record<string, string>>({});
  const [reportCle, setReportCle] = useState<string | null>(null);
  const [reportDate, setReportDate] = useState("");
  const [relanceItemMsg, setRelanceItemMsg] = useState<string | null>(null);
  const [reponses, setReponses] = useState<Record<string, ReponseClient>>({});
  const [reponseOuverteCle, setReponseOuverteCle] = useState<string | null>(
    null,
  );
  const [reponseContenu, setReponseContenu] = useState("");
  const [reponsePieces, setReponsePieces] = useState("");
  const [reponseBusy, setReponseBusy] = useState(false);
  const [reponseErr, setReponseErr] = useState<string | null>(null);
  const [relanceBusy, setRelanceBusy] = useState(false);
  const [relanceErr, setRelanceErr] = useState<string | null>(null);
  const [planifDate, setPlanifDate] = useState("");
  const [planifBusy, setPlanifBusy] = useState(false);
  const [planifErr, setPlanifErr] = useState<string | null>(null);
  const [planifOut, setPlanifOut] = useState<{
    planifiees: number;
    deja_planifiees: number;
  } | null>(null);
  const [relancesFaitesBusy, setRelancesFaitesBusy] = useState(false);
  const [tempsOuvert, setTempsOuvert] = useState(false);
  const [tempsRecap, setTempsRecap] = useState<TempsRecap | null>(null);
  const [tempsErr, setTempsErr] = useState<string | null>(null);
  const [tempsBusy, setTempsBusy] = useState(false);
  const [tempsSupprId, setTempsSupprId] = useState<number | null>(null);
  const [tempsPhase, setTempsPhase] = useState<TempsPhase>("controles");
  const [tempsDate, setTempsDate] = useState(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [tempsHeures, setTempsHeures] = useState("");
  const [tempsNote, setTempsNote] = useState("");
  const [renta, setRenta] = useState<RentabiliteMission | null>(null);
  const [rentaHonoraires, setRentaHonoraires] = useState("");
  const [rentaTaux, setRentaTaux] = useState("");
  const [rentaBusy, setRentaBusy] = useState(false);
  const [rentaErr, setRentaErr] = useState<string | null>(null);
  const [visasOuvert, setVisasOuvert] = useState(false);
  const [visasEtat, setVisasEtat] = useState<VisasEtat | null>(null);
  const [visasErr, setVisasErr] = useState<string | null>(null);
  const [visaBusy, setVisaBusy] = useState<string | null>(null);
  const [sourcesOuvert, setSourcesOuvert] = useState(false);
  const [sourcesTypeDepot, setSourcesTypeDepot] = useState("autre");
  const [sourcesDepotBusy, setSourcesDepotBusy] = useState(false);
  const [sourcesDepotMsg, setSourcesDepotMsg] = useState<string | null>(null);
  const [sourcesDepotErr, setSourcesDepotErr] = useState<string | null>(null);
  const [progOuvert, setProgOuvert] = useState(false);
  const [progEtat, setProgEtat] = useState<ProgrammeEtat | null>(null);
  const [progErr, setProgErr] = useState<string | null>(null);
  const [progBusy, setProgBusy] = useState<string | null>(null);
  const [echeancierOuvert, setEcheancierOuvert] = useState(false);
  const [pilotageOuvert, setPilotageOuvert] = useState(false);
  const [prescriptionOuverte, setPrescriptionOuverte] = useState(false);
  const [civismeOuvert, setCivismeOuvert] = useState(false);
  const [planActionsOuvert, setPlanActionsOuvert] = useState(false);
  const [bilanClotureOuvert, setBilanClotureOuvert] = useState(false);
  const [ctrlClotureOuvert, setCtrlClotureOuvert] = useState(false);
  const [ctrlCloture, setCtrlCloture] = useState<ControleClotureOut | null>(
    null,
  );
  const [ctrlClotureBusy, setCtrlClotureBusy] = useState(false);
  const [ctrlClotureErr, setCtrlClotureErr] = useState<string | null>(null);
  const [noteOuverte, setNoteOuverte] = useState(false);
  const [noteVersions, setNoteVersions] = useState<NoteSyntheseVersion[]>([]);
  const [noteVersionSel, setNoteVersionSel] = useState<number | null>(null);
  const [noteDetail, setNoteDetail] = useState<NoteSyntheseDetail | null>(
    null,
  );
  const [noteBusy, setNoteBusy] = useState(false);
  const [noteErr, setNoteErr] = useState<string | null>(null);
  const notePollRef = useRef(false);
  const [comAnaOuvert, setComAnaOuvert] = useState(false);
  const [comAnaVersions, setComAnaVersions] = useState<
    CommentaireAnalytiqueVersion[]
  >([]);
  const [comAnaVersionSel, setComAnaVersionSel] = useState<number | null>(
    null,
  );
  const [comAnaDetail, setComAnaDetail] =
    useState<CommentaireAnalytiqueDetail | null>(null);
  const [comAnaBusy, setComAnaBusy] = useState(false);
  const [comAnaErr, setComAnaErr] = useState<string | null>(null);
  const comAnaPollRef = useRef(false);

  const chargerComAnaVersions = async (): Promise<
    CommentaireAnalytiqueVersion[]
  > => {
    if (!jeton || !r.mission_id) return [];
    const liste = await api<CommentaireAnalytiqueVersion[]>(
      `/api/v1/missions/${r.mission_id}/commentaires-analytiques`,
      { jeton },
    );
    const versions = Array.isArray(liste) ? liste : [];
    setComAnaVersions(versions);
    return versions;
  };

  /** Polling 5 s / 90 s (même cadence que la note de synthèse). */
  async function surveillerComAna() {
    if (comAnaPollRef.current || !jeton || !r.mission_id) return;
    comAnaPollRef.current = true;
    const idsTerminesConnus = new Set(
      comAnaVersions.filter((v) => v.statut !== "en_cours").map((v) => v.id),
    );
    const debut = Date.now();
    try {
      while (Date.now() - debut < 90_000) {
        await new Promise((res) => setTimeout(res, 5_000));
        let liste: CommentaireAnalytiqueVersion[] = [];
        try {
          liste = await api<CommentaireAnalytiqueVersion[]>(
            `/api/v1/missions/${r.mission_id}/commentaires-analytiques`,
            { jeton },
          );
        } catch {
          continue;
        }
        const nouvelle = (Array.isArray(liste) ? liste : []).find(
          (v) => !idsTerminesConnus.has(v.id) && v.statut !== "en_cours",
        );
        if (nouvelle) {
          setComAnaVersions(liste);
          setComAnaVersionSel(nouvelle.version);
          return;
        }
      }
    } finally {
      comAnaPollRef.current = false;
    }
  }

  async function genererComAna() {
    if (!jeton || !r.mission_id || comAnaBusy) return;
    setComAnaBusy(true);
    setComAnaErr(null);
    try {
      const commentaire = await api<CommentaireAnalytiqueDetail>(
        `/api/v1/missions/${r.mission_id}/commentaire-analytique`,
        { method: "POST", jeton },
      );
      await chargerComAnaVersions();
      setComAnaVersionSel(commentaire.version);
      if (commentaire.statut === "echec" && commentaire.erreur) {
        setComAnaErr(commentaire.erreur);
      }
    } catch (e) {
      setComAnaErr(e instanceof Error ? e.message : String(e));
      void surveillerComAna();
    } finally {
      setComAnaBusy(false);
    }
  }

  useEffect(() => {
    if (!comAnaOuvert || !jeton || !r.mission_id) return;
    let annule = false;
    void (async () => {
      try {
        const versions = await chargerComAnaVersions();
        if (annule) return;
        const derniere = versions.find((v) => v.statut === "disponible");
        setComAnaVersionSel((sel) => sel ?? derniere?.version ?? null);
      } catch (e) {
        if (!annule) {
          setComAnaErr(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      annule = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [comAnaOuvert, jeton, r.mission_id]);

  useEffect(() => {
    if (
      !comAnaOuvert ||
      !jeton ||
      !r.mission_id ||
      comAnaVersionSel == null
    ) {
      setComAnaDetail(null);
      return;
    }
    let annule = false;
    void (async () => {
      try {
        const detail = await api<CommentaireAnalytiqueDetail>(
          `/api/v1/missions/${r.mission_id}/commentaires-analytiques/${comAnaVersionSel}`,
          { jeton },
        );
        if (!annule) setComAnaDetail(detail);
      } catch (e) {
        if (!annule) {
          setComAnaDetail(null);
          setComAnaErr(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      annule = true;
    };
  }, [comAnaOuvert, jeton, r.mission_id, comAnaVersionSel]);

  const chargerNoteVersions = async (): Promise<NoteSyntheseVersion[]> => {
    if (!jeton || !r.mission_id) return [];
    const liste = await api<NoteSyntheseVersion[]>(
      `/api/v1/missions/${r.mission_id}/notes-synthese`,
      { jeton },
    );
    const versions = Array.isArray(liste) ? liste : [];
    setNoteVersions(versions);
    return versions;
  };

  /** Polling 5 s / 90 s (même cadence que la synthèse Data Room). */
  async function surveillerNote() {
    if (notePollRef.current || !jeton || !r.mission_id) return;
    notePollRef.current = true;
    const idsTerminesConnus = new Set(
      noteVersions.filter((v) => v.statut !== "en_cours").map((v) => v.id),
    );
    const debut = Date.now();
    try {
      while (Date.now() - debut < 90_000) {
        await new Promise((res) => setTimeout(res, 5_000));
        let liste: NoteSyntheseVersion[] = [];
        try {
          liste = await api<NoteSyntheseVersion[]>(
            `/api/v1/missions/${r.mission_id}/notes-synthese`,
            { jeton },
          );
        } catch {
          continue;
        }
        const nouvelle = (Array.isArray(liste) ? liste : []).find(
          (v) => !idsTerminesConnus.has(v.id) && v.statut !== "en_cours",
        );
        if (nouvelle) {
          setNoteVersions(liste);
          setNoteVersionSel(nouvelle.version);
          return;
        }
      }
    } finally {
      notePollRef.current = false;
    }
  }

  async function genererNote() {
    if (!jeton || !r.mission_id || noteBusy) return;
    setNoteBusy(true);
    setNoteErr(null);
    try {
      const note = await api<NoteSyntheseDetail>(
        `/api/v1/missions/${r.mission_id}/note-synthese`,
        { method: "POST", jeton },
      );
      await chargerNoteVersions();
      setNoteVersionSel(note.version);
      if (note.statut === "echec" && note.erreur) {
        setNoteErr(note.erreur);
      }
    } catch (e) {
      setNoteErr(e instanceof Error ? e.message : String(e));
      void surveillerNote();
    } finally {
      setNoteBusy(false);
    }
  }

  useEffect(() => {
    if (!noteOuverte || !jeton || !r.mission_id) return;
    let annule = false;
    void (async () => {
      try {
        const versions = await chargerNoteVersions();
        if (annule) return;
        const derniere = versions.find((v) => v.statut === "disponible");
        setNoteVersionSel((sel) => sel ?? derniere?.version ?? null);
      } catch (e) {
        if (!annule) {
          setNoteErr(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      annule = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noteOuverte, jeton, r.mission_id]);

  useEffect(() => {
    if (!noteOuverte || !jeton || !r.mission_id || noteVersionSel == null) {
      setNoteDetail(null);
      return;
    }
    let annule = false;
    void (async () => {
      try {
        const detail = await api<NoteSyntheseDetail>(
          `/api/v1/missions/${r.mission_id}/notes-synthese/${noteVersionSel}`,
          { jeton },
        );
        if (!annule) setNoteDetail(detail);
      } catch (e) {
        if (!annule) {
          setNoteDetail(null);
          setNoteErr(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      annule = true;
    };
  }, [noteOuverte, jeton, r.mission_id, noteVersionSel]);

  /**
   * Poste de travail : un seul panneau ouvert à la fois.
   * Ferme tous les panneaux d'outil sauf celui passé en argument.
   */
  type PanneauId =
    | "sources"
    | "pilotage"
    | "suivi"
    | "temps"
    | "programme"
    | "echeancier"
    | "civisme"
    | "prescription"
    | "plan_actions"
    | "visas"
    | "note"
    | "comparatif"
    | "bilan_cloture"
    | "ctrlCloture";

  function fermerPanneaux(sauf?: PanneauId) {
    if (sauf !== "sources") setSourcesOuvert(false);
    if (sauf !== "pilotage") setPilotageOuvert(false);
    if (sauf !== "suivi") setSuiviOuvert(false);
    if (sauf !== "temps") setTempsOuvert(false);
    if (sauf !== "programme") setProgOuvert(false);
    if (sauf !== "echeancier") setEcheancierOuvert(false);
    if (sauf !== "civisme") setCivismeOuvert(false);
    if (sauf !== "prescription") setPrescriptionOuverte(false);
    if (sauf !== "plan_actions") setPlanActionsOuvert(false);
    if (sauf !== "visas") setVisasOuvert(false);
    if (sauf !== "note") setNoteOuverte(false);
    if (sauf !== "comparatif") setComparatifOuvert(false);
    if (sauf !== "bilan_cloture") setBilanClotureOuvert(false);
    if (sauf !== "ctrlCloture" && ctrlClotureOuvert) {
      setCtrlClotureOuvert(false);
      setCtrlCloture(null);
      setCtrlClotureErr(null);
    }
  }

  /** Toggle standard d'un panneau : ferme les autres, ouvre/ferme celui-ci. */
  function togglePanneau(
    id: PanneauId,
    ouvert: boolean,
    setOuvert: (v: boolean) => void,
    onOuverture?: () => void,
  ) {
    fermerPanneaux(id);
    if (ouvert) {
      setOuvert(false);
    } else {
      setOuvert(true);
      onOuverture?.();
    }
  }

  /** Recharge la liste des pièces de la mission (data room). */
  async function rechargerPiecesMission() {
    if (!jeton || !r.mission_id) return;
    try {
      const list = await api<PieceMissionOpt[]>(
        `/api/v1/missions/${r.mission_id}/pieces`,
        { jeton },
      );
      setPieces(list);
    } catch {
      /* liste conservée en l'état */
    }
  }

  /** Dépose une ou plusieurs pièces dans la data room de la mission. */
  async function deposerPiecesMission(fichiers: FileList | null) {
    if (!fichiers || fichiers.length === 0 || sourcesDepotBusy) return;
    if (!jeton || !r.mission_id) return;
    const liste = Array.from(fichiers);
    setSourcesDepotBusy(true);
    setSourcesDepotMsg(null);
    setSourcesDepotErr(null);
    let envoyees = 0;
    let derniereErreur: string | null = null;
    for (const fichier of liste) {
      try {
        await apiUpload<PieceMissionOpt>(
          `/api/v1/missions/${r.mission_id}/pieces`,
          fichier,
          jeton,
          { type_piece: sourcesTypeDepot },
        );
        envoyees += 1;
      } catch (e) {
        derniereErreur = e instanceof Error ? e.message : String(e);
      }
    }
    if (envoyees > 0) {
      setSourcesDepotMsg(
        envoyees === 1 ? "1 pièce déposée." : `${envoyees} pièces déposées.`,
      );
      await rechargerPiecesMission();
    }
    if (derniereErreur) {
      setSourcesDepotErr(
        envoyees > 0
          ? `Certaines pièces ont été refusées : ${derniereErreur}`
          : `Dépôt impossible : ${derniereErreur}`,
      );
    }
    setSourcesDepotBusy(false);
  }

  /** Étape intermédiaire avant clôture : revue qualité consultative. */
  async function ouvrirControleCloture() {
    if (ctrlClotureBusy) return;
    setCtrlClotureBusy(true);
    setCtrlClotureErr(null);
    setCtrlCloture(null);
    setCtrlClotureOuvert(true);
    try {
      if (!jeton || !r.mission_id) {
        throw new Error("Session requise pour le contrôle de pré-clôture.");
      }
      const out = await api<ControleClotureOut>(
        `/api/v1/missions/${r.mission_id}/controle-cloture`,
        { jeton },
      );
      setCtrlCloture(out);
    } catch (e) {
      setCtrlClotureErr(e instanceof Error ? e.message : String(e));
    } finally {
      setCtrlClotureBusy(false);
    }
  }

  function confirmerCloture() {
    setCtrlClotureOuvert(false);
    setCtrlCloture(null);
    onCloturer?.();
  }

  function allerRegleNote(regleId: string) {
    const el = document.getElementById(`rest-regle-${regleId}`);
    if (el) {
      el.scrollIntoView({ behavior: scrollPref(), block: "center" });
    } else {
      setSectionActive("risques");
      rootRef.current
        ?.querySelector("#rest-risques")
        ?.scrollIntoView({ behavior: scrollPref(), block: "start" });
    }
  }

  async function telechargerLettreMission() {
    if (!jeton || !r.mission_id || lettreBusy) return;
    setLettreBusy(true);
    setLettreErr(null);
    try {
      const denom = (
        r.identification?.contribuable_denomination || "client"
      )
        .normalize("NFKD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^A-Za-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "")
        .toUpperCase() || "CLIENT";
      const exo = r.identification?.exercice ?? "exercice";
      await telecharger(
        `/api/v1/missions/${r.mission_id}/lettre-mission.docx`,
        jeton,
        `lettre_mission_${denom}_${exo}.docx`,
      );
    } catch (e) {
      setLettreErr(
        e instanceof Error ? e.message : "téléchargement impossible",
      );
    } finally {
      setLettreBusy(false);
    }
  }

  async function telechargerDemandeRenseignements() {
    if (!jeton || !r.mission_id || demandeBusy) return;
    setDemandeBusy(true);
    setDemandeErr(null);
    try {
      const denom = (
        r.identification?.contribuable_denomination || "client"
      )
        .normalize("NFKD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^A-Za-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "")
        .toUpperCase() || "CLIENT";
      const exo = r.identification?.exercice ?? "exercice";
      await telecharger(
        `/api/v1/missions/${r.mission_id}/demande-renseignements.docx`,
        jeton,
        `demande_renseignements_${denom}_${exo}.docx`,
      );
    } catch (e) {
      setDemandeErr(
        e instanceof Error ? e.message : "téléchargement impossible",
      );
    } finally {
      setDemandeBusy(false);
    }
  }

  async function telechargerCourrierRelance() {
    if (!jeton || !r.mission_id || relanceBusy) return;
    setRelanceBusy(true);
    setRelanceErr(null);
    try {
      const denom = (
        r.identification?.contribuable_denomination || "client"
      )
        .normalize("NFKD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^A-Za-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "")
        .toUpperCase() || "CLIENT";
      const exo = r.identification?.exercice ?? "exercice";
      await telecharger(
        `/api/v1/missions/${r.mission_id}/courrier-relance.docx`,
        jeton,
        `relance_${denom}_${exo}.docx`,
      );
    } catch (e) {
      setRelanceErr(
        e instanceof Error ? e.message : "téléchargement impossible",
      );
    } finally {
      setRelanceBusy(false);
    }
  }

  async function telechargerCourrierRelanceTxt() {
    if (!jeton || !r.mission_id || relanceBusy) return;
    setRelanceBusy(true);
    setRelanceErr(null);
    try {
      await telecharger(
        `/api/v1/missions/${r.mission_id}/courrier-relance.txt`,
        jeton,
        `courrier-relance-mission-${r.mission_id}.txt`,
      );
    } catch (e) {
      setRelanceErr(
        e instanceof Error ? e.message : "téléchargement impossible",
      );
    } finally {
      setRelanceBusy(false);
    }
  }

  async function telechargerCourrierEnvoi() {
    if (!jeton || !r.mission_id || courrierEnvoiBusy) return;
    setCourrierEnvoiBusy(true);
    setCourrierEnvoiErr(null);
    try {
      const denom = (
        r.identification?.contribuable_denomination || "client"
      )
        .normalize("NFKD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^A-Za-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "")
        .toUpperCase() || "CLIENT";
      const exo = r.identification?.exercice ?? "exercice";
      await telecharger(
        `/api/v1/missions/${r.mission_id}/courrier-envoi.docx`,
        jeton,
        `courrier_envoi_rapport_${denom}_${exo}.docx`,
      );
    } catch (e) {
      setCourrierEnvoiErr(
        e instanceof Error ? e.message : "téléchargement impossible",
      );
    } finally {
      setCourrierEnvoiBusy(false);
    }
  }

  async function telechargerLettreAffirmation() {
    if (!jeton || !r.mission_id || affirmationBusy) return;
    setAffirmationBusy(true);
    setAffirmationErr(null);
    try {
      const denom = (
        r.identification?.contribuable_denomination || "client"
      )
        .normalize("NFKD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^A-Za-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "")
        .toUpperCase() || "CLIENT";
      const exo = r.identification?.exercice ?? "exercice";
      await telecharger(
        `/api/v1/missions/${r.mission_id}/lettre-affirmation.docx`,
        jeton,
        `lettre_affirmation_${denom}_${exo}.docx`,
      );
    } catch (e) {
      setAffirmationErr(
        e instanceof Error ? e.message : "téléchargement impossible",
      );
    } finally {
      setAffirmationBusy(false);
    }
  }

  async function telechargerDossierTravail() {
    if (!jeton || !r.mission_id || dossierBusy) return;
    setDossierBusy(true);
    setDossierErr(null);
    try {
      const denom = (
        r.identification?.contribuable_denomination || "client"
      )
        .normalize("NFKD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^A-Za-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "")
        .toUpperCase() || "CLIENT";
      const exo = r.identification?.exercice ?? "exercice";
      await telecharger(
        `/api/v1/missions/${r.mission_id}/dossier-travail.zip`,
        jeton,
        `dossier_travail_${denom}_${exo}.zip`,
      );
    } catch (e) {
      setDossierErr(
        e instanceof Error ? e.message : "téléchargement impossible",
      );
    } finally {
      setDossierBusy(false);
    }
  }

  async function chargerComparatif(): Promise<void> {
    if (!jeton || !r.mission_id || comparatifBusy) return;
    setComparatifBusy(true);
    setComparatifErr(null);
    try {
      const out = await api<ComparatifOut>(
        `/api/v1/missions/${r.mission_id}/comparatif-executions`,
        { jeton },
      );
      setComparatif(out ?? null);
    } catch (e) {
      setComparatif(null);
      setComparatifErr(
        e instanceof Error ? e.message : "comparatif indisponible",
      );
    } finally {
      setComparatifBusy(false);
    }
  }

  async function chargerSuivi(): Promise<void> {
    if (!jeton || !r.mission_id) return;
    try {
      const out = await api<SuiviOut>(
        `/api/v1/missions/${r.mission_id}/suivi-renseignements`,
        { jeton },
      );
      setSuivi(out ?? null);
      setSuiviErr(null);
      const notes: Record<string, string> = {};
      for (const it of out?.items ?? []) notes[it.cle_item] = it.note ?? "";
      setSuiviNotes(notes);
    } catch (e) {
      setSuivi(null);
      setSuiviErr(e instanceof Error ? e.message : "suivi indisponible");
    }
  }

  async function majSuiviItem(
    item: SuiviItem,
    champs: Partial<{
      statut: SuiviStatut;
      date_relance: string | null;
      note: string | null;
    }>,
  ): Promise<void> {
    if (!jeton || !r.mission_id || suiviBusyCle) return;
    setSuiviBusyCle(item.cle_item);
    setSuiviErr(null);
    try {
      const out = await api<{ item: SuiviItem; synthese: SuiviSynthese }>(
        `/api/v1/missions/${r.mission_id}/suivi-renseignements/${encodeURIComponent(item.cle_item)}`,
        {
          jeton,
          method: "PATCH",
          json: {
            statut: champs.statut ?? item.statut,
            date_relance:
              champs.date_relance !== undefined
                ? champs.date_relance
                : item.date_relance,
            note: champs.note !== undefined ? champs.note : item.note,
          },
        },
      );
      setSuivi((prev) =>
        prev
          ? {
              synthese: out.synthese,
              items: prev.items.map((it) =>
                it.cle_item === out.item.cle_item ? out.item : it,
              ),
            }
          : prev,
      );
    } catch (e) {
      setSuiviErr(
        e instanceof Error ? e.message : "mise à jour du suivi impossible",
      );
    } finally {
      setSuiviBusyCle(null);
    }
  }

  async function planifierRelances(): Promise<void> {
    if (!jeton || !r.mission_id || planifBusy || !planifDate) return;
    setPlanifBusy(true);
    setPlanifErr(null);
    setPlanifOut(null);
    try {
      const out = await api<{
        planifiees: number;
        deja_planifiees: number;
      }>(
        `/api/v1/missions/${r.mission_id}/suivi-renseignements/planifier-relances`,
        { jeton, method: "POST", json: { date_relance: planifDate } },
      );
      setPlanifOut(out ?? null);
      await chargerSuivi();
    } catch (e) {
      setPlanifErr(
        e instanceof Error
          ? e.message
          : "planification des relances impossible",
      );
    } finally {
      setPlanifBusy(false);
    }
  }

  async function marquerRelancesFaites(): Promise<void> {
    if (!jeton || !r.mission_id || relancesFaitesBusy) return;
    setRelancesFaitesBusy(true);
    setSuiviErr(null);
    setRelanceItemMsg(null);
    try {
      const out = await api<{ effectuees: number; ignorees: number }>(
        `/api/v1/missions/${r.mission_id}/suivi-renseignements/relances-effectuees`,
        { jeton, method: "POST" },
      );
      const n = out?.effectuees ?? 0;
      setRelanceItemMsg(
        n > 0
          ? `${n} relance${n > 1 ? "s" : ""} marquée${n > 1 ? "s" : ""} faite${n > 1 ? "s" : ""} — dates planifiées effacées (re-planifiez pour la prochaine échéance)`
          : "Aucune relance planifiée à marquer",
      );
      await chargerSuivi();
    } catch (e) {
      setSuiviErr(
        e instanceof Error
          ? e.message
          : "marquage groupé des relances impossible",
      );
    } finally {
      setRelancesFaitesBusy(false);
    }
  }

  async function relanceFaite(it: SuiviItem): Promise<void> {
    if (!jeton || !r.mission_id || suiviBusyCle) return;
    setSuiviBusyCle(it.cle_item);
    setSuiviErr(null);
    setRelanceItemMsg(null);
    try {
      const out = await api<{ item: SuiviItem; synthese: SuiviSynthese }>(
        `/api/v1/missions/${r.mission_id}/suivi-renseignements/${encodeURIComponent(it.cle_item)}/relance-effectuee`,
        { jeton, method: "POST" },
      );
      const n = out?.item.nb_relances ?? 0;
      setRelanceItemMsg(
        `Relance enregistrée (${n} relance${n > 1 ? "s" : ""} au total)`,
      );
      await chargerSuivi();
    } catch (e) {
      setSuiviErr(
        e instanceof Error ? e.message : "relance impossible à enregistrer",
      );
    } finally {
      setSuiviBusyCle(null);
    }
  }

  async function reporterRelance(it: SuiviItem): Promise<void> {
    if (!jeton || !r.mission_id || suiviBusyCle || !reportDate) return;
    setSuiviBusyCle(it.cle_item);
    setSuiviErr(null);
    setRelanceItemMsg(null);
    try {
      const out = await api<{ item: SuiviItem; synthese: SuiviSynthese }>(
        `/api/v1/missions/${r.mission_id}/suivi-renseignements/${encodeURIComponent(it.cle_item)}/reporter`,
        { jeton, method: "POST", json: { date_relance: reportDate } },
      );
      setRelanceItemMsg(
        `Relance reportée au ${out?.item.date_relance ?? reportDate}`,
      );
      setReportCle(null);
      setReportDate("");
      await chargerSuivi();
    } catch (e) {
      setSuiviErr(
        e instanceof Error ? e.message : "report de la relance impossible",
      );
    } finally {
      setSuiviBusyCle(null);
    }
  }

  async function chargerReponses(): Promise<void> {
    if (!jeton || !r.mission_id) return;
    try {
      const out = await api<{ reponses: ReponseClient[] }>(
        `/api/v1/missions/${r.mission_id}/reponses`,
        { jeton },
      );
      const map: Record<string, ReponseClient> = {};
      for (const rep of out?.reponses ?? []) map[rep.cle_item] = rep;
      setReponses(map);
    } catch {
      /* réponses indisponibles : le suivi reste utilisable */
    }
  }

  function ouvrirReponse(cle: string): void {
    if (reponseOuverteCle === cle) {
      setReponseOuverteCle(null);
      return;
    }
    const rep = reponses[cle];
    setReponseContenu(rep?.contenu ?? "");
    setReponsePieces(rep?.pieces_recues ?? "");
    setReponseErr(null);
    setReponseOuverteCle(cle);
  }

  async function enregistrerReponse(cle: string): Promise<void> {
    if (!jeton || !r.mission_id || reponseBusy) return;
    const contenu = reponseContenu.trim();
    if (!contenu) {
      setReponseErr("Le contenu de la réponse est obligatoire.");
      return;
    }
    setReponseBusy(true);
    setReponseErr(null);
    try {
      const out = await api<{ reponse: ReponseClient }>(
        `/api/v1/missions/${r.mission_id}/reponses/${encodeURIComponent(cle)}`,
        {
          jeton,
          method: "PUT",
          json: {
            contenu,
            pieces_recues: reponsePieces.trim() || null,
          },
        },
      );
      setReponses((prev) => ({ ...prev, [cle]: out.reponse }));
      setReponseOuverteCle(null);
      // La saisie passe l'item « recu » côté serveur : recharger le suivi
      // (statuts + synthèse) et les réponses (statut_derniere_execution).
      await chargerSuivi();
      await chargerReponses();
    } catch (e) {
      setReponseErr(
        e instanceof Error
          ? e.message
          : "enregistrement de la réponse impossible",
      );
    } finally {
      setReponseBusy(false);
    }
  }

  async function chargerTemps(): Promise<void> {
    if (!jeton || !r.mission_id) return;
    try {
      const out = await api<TempsRecap>(
        `/api/v1/missions/${r.mission_id}/temps`,
        { jeton },
      );
      setTempsRecap(out ?? null);
      setTempsErr(null);
    } catch (e) {
      setTempsRecap(null);
      setTempsErr(
        e instanceof Error ? e.message : "temps passés indisponibles",
      );
    }
    await chargerRentabilite();
  }

  async function chargerRentabilite(): Promise<void> {
    if (!jeton || !r.mission_id) return;
    try {
      const out = await api<RentabiliteMission>(
        `/api/v1/missions/${r.mission_id}/rentabilite`,
        { jeton },
      );
      setRenta(out ?? null);
      setRentaHonoraires(out?.honoraires ?? "");
      setRentaTaux(out?.taux_horaire ?? "");
      setRentaErr(null);
    } catch (e) {
      setRenta(null);
      setRentaErr(
        e instanceof Error ? e.message : "rentabilité indisponible",
      );
    }
  }

  async function enregistrerRentabilite(): Promise<void> {
    if (!jeton || !r.mission_id || rentaBusy) return;
    const versNombre = (brut: string): number | null => {
      const t = brut.trim().replace(",", ".");
      if (!t) return null;
      const n = Number(t);
      return Number.isFinite(n) ? n : Number.NaN;
    };
    const honoraires = versNombre(rentaHonoraires);
    const taux = versNombre(rentaTaux);
    if (Number.isNaN(honoraires) || Number.isNaN(taux)) {
      setRentaErr("Montants invalides : nombres positifs attendus (FCFA).");
      return;
    }
    setRentaBusy(true);
    setRentaErr(null);
    try {
      const out = await api<RentabiliteMission>(
        `/api/v1/missions/${r.mission_id}/rentabilite`,
        {
          jeton,
          method: "PUT",
          json: { honoraires, taux_horaire: taux },
        },
      );
      setRenta(out ?? null);
      setRentaHonoraires(out?.honoraires ?? "");
      setRentaTaux(out?.taux_horaire ?? "");
    } catch (e) {
      setRentaErr(
        e instanceof Error
          ? e.message
          : "enregistrement de la rentabilité impossible",
      );
    } finally {
      setRentaBusy(false);
    }
  }

  async function saisirTemps(): Promise<void> {
    if (!jeton || !r.mission_id || tempsBusy) return;
    const heures = Number(tempsHeures.replace(",", "."));
    if (!tempsHeures.trim() || !Number.isFinite(heures)) {
      setTempsErr("Heures obligatoires (nombre entre 0 et 24).");
      return;
    }
    setTempsBusy(true);
    setTempsErr(null);
    try {
      await api<{ entree: TempsEntree }>(
        `/api/v1/missions/${r.mission_id}/temps`,
        {
          jeton,
          method: "POST",
          json: {
            phase: tempsPhase,
            date_jour: tempsDate,
            heures,
            note: tempsNote.trim() || null,
          },
        },
      );
      setTempsHeures("");
      setTempsNote("");
      await chargerTemps();
    } catch (e) {
      setTempsErr(
        e instanceof Error ? e.message : "saisie du temps impossible",
      );
    } finally {
      setTempsBusy(false);
    }
  }

  async function supprimerTemps(tempsId: number): Promise<void> {
    if (!jeton || !r.mission_id || tempsSupprId !== null) return;
    setTempsSupprId(tempsId);
    setTempsErr(null);
    try {
      await api<{ entree: TempsEntree }>(
        `/api/v1/missions/${r.mission_id}/temps/${tempsId}`,
        { jeton, method: "DELETE" },
      );
      await chargerTemps();
    } catch (e) {
      setTempsErr(
        e instanceof Error ? e.message : "suppression du temps impossible",
      );
    } finally {
      setTempsSupprId(null);
    }
  }

  async function chargerProgramme(): Promise<void> {
    if (!jeton || !r.mission_id) return;
    try {
      const out = await api<ProgrammeEtat>(
        `/api/v1/missions/${r.mission_id}/programme`,
        { jeton },
      );
      setProgEtat(out ?? null);
      setProgErr(null);
    } catch (e) {
      setProgEtat(null);
      setProgErr(
        e instanceof Error ? e.message : "programme de travail indisponible",
      );
    }
  }

  async function cocherDiligence(code: string, fait: boolean): Promise<void> {
    if (!jeton || !r.mission_id || progBusy !== null) return;
    setProgBusy(code);
    setProgErr(null);
    try {
      await api<{ diligence: DiligenceProgramme }>(
        `/api/v1/missions/${r.mission_id}/programme/${code}`,
        { jeton, method: "PUT", json: { fait } },
      );
      await chargerProgramme();
    } catch (e) {
      setProgErr(
        e instanceof Error ? e.message : "mise à jour de la diligence impossible",
      );
    } finally {
      setProgBusy(null);
    }
  }

  async function chargerVisas(): Promise<void> {
    if (!jeton || !r.mission_id) return;
    try {
      const out = await api<VisasEtat>(
        `/api/v1/missions/${r.mission_id}/visas`,
        { jeton },
      );
      setVisasEtat(out ?? null);
      setVisasErr(null);
    } catch (e) {
      setVisasEtat(null);
      setVisasErr(
        e instanceof Error ? e.message : "visas de supervision indisponibles",
      );
    }
  }

  async function poserVisa(phase: VisaPhase, role: VisaRole): Promise<void> {
    if (!jeton || !r.mission_id || visaBusy !== null) return;
    setVisaBusy(`${phase}/${role}`);
    setVisasErr(null);
    try {
      await api<{ visa: VisaMission }>(
        `/api/v1/missions/${r.mission_id}/visas`,
        { jeton, method: "POST", json: { phase, role } },
      );
      await chargerVisas();
    } catch (e) {
      setVisasErr(
        e instanceof Error ? e.message : "pose du visa impossible",
      );
    } finally {
      setVisaBusy(null);
    }
  }

  async function revoquerVisa(
    phase: VisaPhase,
    role: VisaRole,
  ): Promise<void> {
    if (!jeton || !r.mission_id || visaBusy !== null) return;
    setVisaBusy(`${phase}/${role}`);
    setVisasErr(null);
    try {
      await api<{ visa: VisaMission }>(
        `/api/v1/missions/${r.mission_id}/visas/${phase}/${role}`,
        { jeton, method: "DELETE" },
      );
      await chargerVisas();
    } catch (e) {
      setVisasErr(
        e instanceof Error ? e.message : "révocation du visa impossible",
      );
    } finally {
      setVisaBusy(null);
    }
  }

  useEffect(() => {
    if (!jeton || !r.mission_id) {
      setSuivi(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const out = await api<SuiviOut>(
          `/api/v1/missions/${r.mission_id}/suivi-renseignements`,
          { jeton },
        );
        if (cancelled) return;
        setSuivi(out ?? null);
        const notes: Record<string, string> = {};
        for (const it of out?.items ?? []) notes[it.cle_item] = it.note ?? "";
        setSuiviNotes(notes);
      } catch {
        if (!cancelled) setSuivi(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [jeton, r.mission_id]);

  useEffect(() => {
    if (!jeton || !r.mission_id) {
      setPieces([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const list = await api<PieceMissionOpt[]>(
          `/api/v1/missions/${r.mission_id}/pieces`,
          { jeton },
        );
        if (!cancelled) setPieces(list);
      } catch {
        if (!cancelled) setPieces([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [jeton, r.mission_id]);

  useEffect(() => {
    if (!jeton || !r.mission_id) {
      setFiabSource(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const out = await api<ControlesFecOut>(
          `/api/v1/missions/${r.mission_id}/controles-fec`,
          { jeton },
        );
        if (!cancelled) setFiabSource(out?.disponible ? out : null);
      } catch {
        if (!cancelled) setFiabSource(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [jeton, r.mission_id]);

  useEffect(() => {
    if (!jeton || !r.mission_id) {
      setRevueAnalytique(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const out = await api<RevueAnalytiqueOut>(
          `/api/v1/missions/${r.mission_id}/revue-analytique`,
          { jeton },
        );
        if (!cancelled) setRevueAnalytique(out ?? null);
      } catch {
        if (!cancelled) setRevueAnalytique(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [jeton, r.mission_id]);

  useEffect(() => {
    if (collaborateursProp && collaborateursProp.length > 0) {
      setCollaborateursLocaux([]);
      return;
    }
    if (!jeton || estLecteur) {
      setCollaborateursLocaux([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const list = await api<CollaborateurOpt[]>(
          "/api/v1/collaborateurs",
          { jeton },
        );
        if (!cancelled) setCollaborateursLocaux(Array.isArray(list) ? list : []);
      } catch {
        try {
          const list = await api<CollaborateurOpt[]>(
            "/api/v1/utilisateurs",
            { jeton },
          );
          if (!cancelled) {
            setCollaborateursLocaux(Array.isArray(list) ? list : []);
          }
        } catch {
          if (!cancelled) setCollaborateursLocaux([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [jeton, estLecteur, collaborateursProp]);

  const collaborateurs =
    collaborateursProp && collaborateursProp.length > 0
      ? collaborateursProp
      : collaborateursLocaux;

  async function patchConclusion(
    conclusionId: number,
    corps: { statut?: string; piece_mission_id?: number | null },
  ) {
    if (!jeton || estLecteur) return;
    setPatchBusyId(conclusionId);
    setPatchErr(null);
    setActionErrId(null);
    try {
      await api(`/api/v1/missions/${r.mission_id}/conclusions/${conclusionId}`, {
        method: "PATCH",
        jeton,
        json: corps,
      });
      onRestitutionRefresh?.();
    } catch (err) {
      setActionErrId(conclusionId);
      setPatchErr(err instanceof Error ? err.message : String(err));
    } finally {
      setPatchBusyId(null);
    }
  }

  async function validerConclusion(conclusionId: number) {
    if (!jeton || estLecteur) return;
    setValiderBusyId(conclusionId);
    setPatchErr(null);
    setActionErrId(null);
    try {
      await api(
        `/api/v1/missions/${r.mission_id}/conclusions/${conclusionId}/validation`,
        { method: "POST", jeton },
      );
      onRestitutionRefresh?.();
    } catch (err) {
      setActionErrId(conclusionId);
      setPatchErr(err instanceof Error ? err.message : String(err));
    } finally {
      setValiderBusyId(null);
    }
  }

  async function patchTache(
    tacheId: number,
    corps: {
      statut?: string;
      piece_attendue?: string | null;
      assignee_a?: number | null;
    },
  ) {
    if (!jeton || estLecteur) return;
    try {
      await api(`/api/v1/missions/${r.mission_id}/taches/${tacheId}`, {
        method: "PATCH",
        jeton,
        json: corps,
      });
      onRestitutionRefresh?.();
    } catch (err) {
      setPatchErr(err instanceof Error ? err.message : String(err));
    }
  }

  const tachesServeur = useMemo(() => {
    const list = r.identification?.taches;
    return Array.isArray(list) ? list : [];
  }, [r.identification?.taches]);

  const relancesClient = useMemo(() => {
    const list = r.identification?.relances_client;
    if (Array.isArray(list) && list.length > 0) return list;
    return tachesServeur.filter(
      (t) => t.statut === "bloquee" && t.piece_attendue,
    );
  }, [r.identification?.relances_client, tachesServeur]);

  const tachesParObjectif = useMemo(() => {
    const ouverts = new Set([
      "a_faire",
      "en_cours",
      "bloquee",
      "anomalie",
      "non_verifiable",
    ]);
    const filtered = tachesServeur.filter((t) => ouverts.has(t.statut));
    const map = new Map<string, typeof filtered>();
    for (const t of filtered) {
      const key = String(t.impot || "—");
      const arr = map.get(key) || [];
      arr.push(t);
      map.set(key, arr);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [tachesServeur]);

  const tachesBloquees = useMemo(
    () => tachesServeur.filter((t) => t.statut === "bloquee"),
    [tachesServeur],
  );

  const tacheParRegle = useMemo(() => {
    const m = new Map<string, (typeof tachesServeur)[0]>();
    for (const t of tachesServeur) {
      if (t.regle_id) m.set(String(t.regle_id), t);
    }
    return m;
  }, [tachesServeur]);

  useEffect(() => {
    const ident = r.identification || {};
    setCadrageType(String(ident.type_engagement || "autre"));
    setCadragePerimetre(
      Array.isArray(ident.perimetre_impots)
        ? ident.perimetre_impots.map(String)
        : [],
    );
    setCadrageExclusions(String(ident.exclusions_declarees || ""));
    setCadrageSeuil(
      ident.seuil_signification != null && ident.seuil_signification !== ""
        ? String(ident.seuil_signification)
        : "",
    );
    const objs = Array.isArray(ident.objectifs)
      ? ident.objectifs
          .map((o: { libelle?: string } | string) =>
            typeof o === "string" ? o : String(o?.libelle || ""),
          )
          .filter((s: string) => s.trim())
      : [];
    setCadrageObjectifs(objs.length > 0 ? objs : [""]);
    setCadrageMsg(null);
    setCadrageErr(null);
    // Sync depuis serveur — champs primitifs pour ne pas écraser la saisie
    // à chaque re-render si la référence identification change sans contenu.
  }, [
    r.mission_id,
    r.identification?.type_engagement,
    r.identification?.exclusions_declarees,
    r.identification?.seuil_signification,
    (r.identification?.perimetre_impots || []).join(","),
    (r.identification?.objectifs || [])
      .map((o: { libelle?: string } | string) =>
        typeof o === "string" ? o : String(o?.libelle || ""),
      )
      .join("|"),
  ]);

  async function sauverCadrage() {
    if (!jeton || estLecteur) return;
    setCadrageBusy(true);
    setCadrageErr(null);
    setCadrageMsg(null);
    try {
      await api(`/api/v1/missions/${r.mission_id}/cadrage`, {
        method: "PATCH",
        jeton,
        json: {
          type_engagement: cadrageType || "autre",
          perimetre_impots:
            cadragePerimetre.length > 0 ? cadragePerimetre : null,
          exclusions_declarees: cadrageExclusions.trim() || null,
          seuil_signification: cadrageSeuil.trim()
            ? Number(cadrageSeuil)
            : null,
          objectifs: cadrageObjectifs
            .map((l) => l.trim())
            .filter(Boolean)
            .map((libelle) => ({ libelle })),
        },
      });
      setCadrageMsg("Cadrage enregistré.");
      onRestitutionRefresh?.();
    } catch (err) {
      setCadrageErr(err instanceof Error ? err.message : String(err));
    } finally {
      setCadrageBusy(false);
    }
  }

  async function creerRisqueDepuisConclusion(
    conclusionId: number,
    c: ConclusionRestitution,
  ) {
    if (!jeton || estLecteur) return;
    const ident = r.identification || {};
    const contribId = ident.contribuable_id;
    if (contribId == null) {
      setActionErrId(conclusionId);
      setPatchErr("contribuable_id manquant dans la restitution");
      return;
    }
    setPointBusyId(conclusionId);
    setPointMsg(null);
    setPatchErr(null);
    setActionErrId(null);
    try {
      const tache = tacheParRegle.get(c.regle_id);
      const impot =
        (tache?.impot && String(tache.impot).trim()) ||
        (Array.isArray(ident.perimetre_impots) && ident.perimetre_impots[0]
          ? String(ident.perimetre_impots[0])
          : null);
      if (!impot) {
        throw new Error(
          "impôt introuvable pour ce risque (tâche / périmètre)",
        );
      }
      const libelle = c.commentaire?.trim()
        ? `Anomalie — ${c.regle_id} — ${c.commentaire.trim().slice(0, 200)}`
        : `Anomalie — ${c.regle_id}`;
      const risque = await api<{ id: number }>("/api/v1/risques", {
        method: "POST",
        jeton,
        json: {
          contribuable_id: contribId,
          impot,
          libelle,
          exercice_origine: (() => {
            const ex = Number(ident.exercice);
            if (!Number.isFinite(ex) || ex < 2000) {
              throw new Error("exercice mission manquant pour créer le risque");
            }
            return ex;
          })(),
          probabilite: "possible",
          montant_estime: c.montant != null ? Number(c.montant) : null,
          origine_conclusion_id: conclusionId,
          origine_mission_id: r.mission_id,
          origine_tache_id: tache?.id ?? null,
        },
      });
      setPointMsg({
        conclusionId,
        texte: `Risque #${risque.id} créé au registre contribuable.`,
      });
    } catch (err) {
      setActionErrId(conclusionId);
      setPatchErr(err instanceof Error ? err.message : String(err));
    } finally {
      setPointBusyId(null);
    }
  }

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const nodes = SECTIONS.map((s) =>
      root.querySelector<HTMLElement>(`#rest-${s.id}`),
    ).filter(Boolean) as HTMLElement[];
    if (!nodes.length) return;

    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort(
            (a, b) =>
              (a.boundingClientRect.top ?? 0) - (b.boundingClientRect.top ?? 0),
          );
        const top = visible[0]?.target as HTMLElement | undefined;
        const id = top?.id?.replace(/^rest-/, "") as SectionId | undefined;
        if (id && SECTIONS.some((s) => s.id === id)) setSectionActive(id);
      },
      {
        root: null,
        rootMargin: "-20% 0px -55% 0px",
        threshold: [0, 0.1, 0.25, 0.5],
      },
    );
    nodes.forEach((n) => io.observe(n));
    return () => io.disconnect();
  }, [r.mission_id, r.execution_id]);

  const id = r.identification || {};
  const profil = (id.profil || {}) as Record<string, unknown>;
  const conclusions = r.conclusions || [];
  const score = r.score_risque;
  const comptages = score.comptages || {};
  const nEleve = comptages.eleve ?? 0;
  const nMoyen = comptages.moyen ?? 0;
  const nFaible = comptages.faible ?? 0;
  const nTotalRisque = nEleve + nMoyen + nFaible;
  const maxScore = Math.max(1, nTotalRisque * 3);
  const jauge = intensiteScore(score.score, maxScore);
  const statutMission = String(id.statut || "cadrage").toLowerCase();
  const cadrageEditable = statutMission === "cadrage";
  const cadrageGele =
    statutMission === "en_cours" ||
    statutMission === "cloturee" ||
    statutMission === "cloture" ||
    statutMission === "terminee";
  const estCloturee =
    statutMission === "cloturee" ||
    statutMission === "cloture" ||
    statutMission === "terminee";
  const sansExecution = r.execution_id == null;
  const refLibelle =
    versionEpinglee?.libelle ?? r.version_referentiel_libelle ?? null;
  const refId = versionEpinglee?.id ?? r.version_referentiel_id ?? null;

  const regleIds = useMemo(
    () => [...new Set(conclusions.map((c) => c.regle_id))],
    [conclusions],
  );

  const traitements = useMemo(() => {
    const map: Record<string, TraitementRisque> = {};
    for (const rid of regleIds) {
      const t = tacheParRegle.get(rid);
      map[rid] = {
        regle_id: rid,
        statut: statutTacheVersTraitement(t?.statut, t?.piece_attendue),
        note: t?.piece_attendue ? String(t.piece_attendue) : "",
        maj_le: "",
        tache_id: t?.id,
      };
    }
    return map;
  }, [regleIds, tacheParRegle]);

  const reglesDonsAllegements = useMemo(() => {
    const ids = [
      ...regleIds,
      ...(r.a_confirmer_regles || []).map((x) => x.regle_id),
    ];
    return extraireReglesDonsEtAllegements(ids);
  }, [regleIds, r.a_confirmer_regles]);

  const synthTrait = useMemo(
    () => synthetiserTraitements(regleIds, traitements),
    [regleIds, traitements],
  );

  const conclusionsFiltrees = useMemo(() => {
    return conclusions.filter((c) => {
      const niv = (c.niveau_risque || "").toLowerCase();
      if (filtreRisque !== "tous" && niv !== filtreRisque) return false;
      const st = traitements[c.regle_id]?.statut ?? "a_faire";
      if (filtreTraitement !== "tous" && st !== filtreTraitement) return false;
      return true;
    });
  }, [conclusions, filtreRisque, filtreTraitement, traitements]);

  const topRisques = useMemo(
    () =>
      [...conclusions]
        .sort((a, b) => Number(b.montant ?? 0) - Number(a.montant ?? 0))
        .slice(0, 3),
    [conclusions],
  );

  const auditEntrees = auditJournal?.entrees || [];
  const auditActionsDispo = useMemo(() => {
    const s = new Set(auditEntrees.map((e) => e.action).filter(Boolean));
    return [...s].sort();
  }, [auditEntrees]);

  const auditFiltre = useMemo(() => {
    if (filtreAuditAction === "tous") return auditEntrees;
    return auditEntrees.filter((e) => e.action === filtreAuditAction);
  }, [auditEntrees, filtreAuditAction]);

  const { ouverts, clotures } = compterOuvertsClotures(synthTrait);
  const progressionTrait =
    regleIds.length === 0
      ? 100
      : Math.round((100 * clotures) / regleIds.length);

  async function majTraitement(
    regleId: string,
    patch: { statut?: StatutTache; note?: string },
  ) {
    const tache = tacheParRegle.get(regleId);
    if (!tache || !jeton || estLecteur) return;
    const prev = traitements[regleId];
    const statutServeur =
      patch.statut ?? prev?.statut ?? normaliserStatutTache(tache.statut);
    const note = patch.note ?? prev?.note ?? "";
    const corps: {
      statut?: string;
      piece_attendue?: string | null;
    } = {};
    if (patch.statut != null) {
      corps.statut = statutServeur;
    }
    if (patch.note != null) {
      corps.piece_attendue = note.trim() || null;
      // UX « documenté » = en_cours + piece_attendue (pas un statut serveur)
      if (patch.statut == null && note.trim()) {
        const courant = normaliserStatutTache(prev?.statut ?? tache.statut);
        if (courant === "a_faire" || courant === "en_cours" || courant === "bloquee") {
          corps.statut = "en_cours";
        }
      }
    }
    await patchTache(tache.id, corps);
  }

  function allerSection(sid: SectionId) {
    setSectionActive(sid);
    const el = rootRef.current?.querySelector(`#rest-${sid}`);
    el?.scrollIntoView({ behavior: scrollPref(), block: "start" });
  }

  const soldePositif = Number(r.passage.solde_net) >= 0;
  const lignesPassage = r.passage.lignes || [];
  const lignesPassageFiltrees = useMemo(() => {
    if (filtreSensPassage === "tous") return lignesPassage;
    return lignesPassage.filter(
      (l) => String(l.sens || "").toLowerCase() === filtreSensPassage,
    );
  }, [lignesPassage, filtreSensPassage]);
  const nbReintPassage = lignesPassage.filter(
    (l) => String(l.sens || "").toLowerCase() === "reintegration",
  ).length;
  const nbDedPassage = lignesPassage.filter(
    (l) => String(l.sens || "").toLowerCase() === "deduction",
  ).length;

  return (
    <div className="rest-artifact rest-vue" ref={rootRef}>
      <div className="dossier2-bandeau" role="region" aria-label="Bandeau mission">
        <div className="dossier2-bandeau-id">
          <span className="dossier2-mark" aria-hidden="true" />
          {onOuvrirClient && id.contribuable_id != null ? (
            <Tooltip label="Ouvrir la fiche client">
              <button
                type="button"
                className="dossier2-client-lien"
                onClick={() => onOuvrirClient(id.contribuable_id!)}
              >
                {id.contribuable_denomination || `Mission #${r.mission_id}`}
              </button>
            </Tooltip>
          ) : (
            <strong className="dossier2-client-nom">
              {id.contribuable_denomination || `Mission #${r.mission_id}`}
            </strong>
          )}
          {id.exercice != null && (
            <span className="dossier2-bandeau-meta">
              Exercice {id.exercice}
            </span>
          )}
          <span className={`badge statut-${statutMission}`}>
            {libelleStatut(statutMission)}
          </span>
          {id.type_engagement_libelle ? (
            <span className="dossier2-bandeau-meta">
              {id.type_engagement_libelle}
            </span>
          ) : null}
          {id.contribuable_regime_fiscal || profil.regime ? (
            <span className="dossier2-bandeau-meta">
              {id.contribuable_regime_fiscal || String(profil.regime)}
            </span>
          ) : null}
          <InfoTip
            label={PROCESS_TIPS.artefact}
            ariaLabel="Aide : artefact restitution"
          />
        </div>
        <div className="dossier2-bandeau-indics">
          {r.execution_id != null && (
            <span className="dossier2-indic">
              Exécution #{r.execution_id}
            </span>
          )}
          <button
            type="button"
            className="dossier2-indic dossier2-indic--btn"
            onClick={() =>
              togglePanneau("sources", sourcesOuvert, setSourcesOuvert, () =>
                void rechargerPiecesMission(),
              )
            }
            disabled={!jeton}
            aria-expanded={sourcesOuvert}
            title="Ouvrir les sources & la data room de la mission"
          >
            Sources : {pieces.length}
          </button>
          {progEtat && (
            <span className="dossier2-indic">
              Programme {progEtat.synthese.faites}/{progEtat.synthese.total}
            </span>
          )}
          {suivi && suivi.synthese.total > 0 && (
            <span
              className={`dossier2-indic${
                suivi.synthese.a_relancer > 0 ? " is-alerte" : ""
              }`}
            >
              Relances {suivi.synthese.recu}/{suivi.synthese.total} reçues
              {suivi.synthese.a_relancer > 0
                ? ` · ${suivi.synthese.a_relancer} à relancer`
                : ""}
            </span>
          )}
        </div>
      </div>

      <div
        className="dossier2-groupes"
        role="toolbar"
        aria-label="Actions du dossier"
      >
        <div className="dossier2-groupe" role="group" aria-label="Travailler">
          <span className="dossier2-groupe-lbl">Travailler</span>
          <div className="dossier2-groupe-actions">
            <Tooltip label="Sources & data room de la mission : toutes les pièces du dossier (source active et annexes), avec dépôt de nouvelles pièces à tout moment — tout type, tout format.">
              <button
                type="button"
                className={`btn btn-ghost btn-sm dossier2-action rest-sources-btn${
                  sourcesOuvert ? " is-actif" : ""
                }`}
                onClick={() =>
                  togglePanneau("sources", sourcesOuvert, setSourcesOuvert, () =>
                    void rechargerPiecesMission(),
                  )
                }
                disabled={!jeton}
                aria-expanded={sourcesOuvert}
              >
                Sources &amp; data room
              </button>
            </Tooltip>
            <Tooltip label="Programme de travail standard : diligences par phase que le collaborateur coche au fil de l'exécution — avancement par phase et global. Complète les visas de supervision.">
              <button
                type="button"
                className={`btn btn-ghost btn-sm dossier2-action rest-programme-btn${
                  progOuvert ? " is-actif" : ""
                }`}
                onClick={() =>
                  togglePanneau("programme", progOuvert, setProgOuvert, () =>
                    void chargerProgramme(),
                  )
                }
                disabled={!jeton}
                aria-expanded={progOuvert}
              >
                Programme
              </button>
            </Tooltip>
            <Tooltip label="Visas de supervision par phase : le préparateur atteste son travail, le réviseur revoit, l'associé signe — dans cet ordre. Registre formel exigé par les normes d'exercice professionnel.">
              <button
                type="button"
                className={`btn btn-ghost btn-sm dossier2-action rest-visas-btn${
                  visasOuvert ? " is-actif" : ""
                }`}
                onClick={() =>
                  togglePanneau("visas", visasOuvert, setVisasOuvert, () =>
                    void chargerVisas(),
                  )
                }
                disabled={!jeton}
                aria-expanded={visasOuvert}
              >
                Visas
              </button>
            </Tooltip>
            <Tooltip label="Comparatif déterministe entre les deux dernières exécutions : constats améliorés, dégradés, inchangés à risque, nouveaux et disparus — avec évolution des montants.">
              <button
                type="button"
                className={`btn btn-ghost btn-sm dossier2-action rest-comparatif-btn${
                  comparatifOuvert ? " is-actif" : ""
                }`}
                onClick={() =>
                  togglePanneau(
                    "comparatif",
                    comparatifOuvert,
                    setComparatifOuvert,
                    () => void chargerComparatif(),
                  )
                }
                disabled={!jeton || comparatifBusy}
                aria-expanded={comparatifOuvert}
              >
                {comparatifBusy ? "Comparatif…" : "Comparer les exécutions"}
              </button>
            </Tooltip>
            <Tooltip label="Dossier de travail complet (ZIP) : tous les livrables de la mission pour archivage probant">
              <button
                type="button"
                className="btn btn-ghost btn-sm dossier2-action rest-dossier-btn"
                onClick={() => void telechargerDossierTravail()}
                disabled={dossierBusy || !jeton}
              >
                {dossierBusy ? "Dossier…" : "Dossier de travail"}
              </button>
            </Tooltip>
            {dossierErr && (
              <span className="rest-lettre-err" role="alert">
                {dossierErr}
              </span>
            )}
            <Tooltip label="Temps passés sur la mission : chaque collaborateur saisit ses heures par phase et par jour — total, répartition et valorisation pour piloter la rentabilité.">
              <button
                type="button"
                className={`btn btn-ghost btn-sm dossier2-action rest-temps-btn${
                  tempsOuvert ? " is-actif" : ""
                }`}
                onClick={() =>
                  togglePanneau("temps", tempsOuvert, setTempsOuvert, () =>
                    void chargerTemps(),
                  )
                }
                disabled={!jeton}
                aria-expanded={tempsOuvert}
              >
                Temps passés
              </button>
            </Tooltip>
          </div>
        </div>

        <div className="dossier2-groupe" role="group" aria-label="Analyser">
          <span className="dossier2-groupe-lbl">Analyser</span>
          <div className="dossier2-groupe-actions">
            <Tooltip label="Pilotage de mission : synthèse transverse en un coup d'œil — avancement du programme, contrôle de pré-clôture, temps passés, rentabilité, visas et conclusions de la dernière exécution.">
              <button
                type="button"
                className={`btn btn-ghost btn-sm dossier2-action rest-pilotage-btn${
                  pilotageOuvert ? " is-actif" : ""
                }`}
                onClick={() =>
                  togglePanneau("pilotage", pilotageOuvert, setPilotageOuvert)
                }
                disabled={!jeton}
                aria-expanded={pilotageOuvert}
              >
                Pilotage
              </button>
            </Tooltip>
            <Tooltip label="Échéancier fiscal de l'exercice revu : calendrier déterministe des obligations déclaratives et de paiement selon le régime du profil mission — dates indicatives, sans calcul d'impôt.">
              <button
                type="button"
                className={`btn btn-ghost btn-sm dossier2-action rest-echeancier-btn${
                  echeancierOuvert ? " is-actif" : ""
                }`}
                onClick={() =>
                  togglePanneau(
                    "echeancier",
                    echeancierOuvert,
                    setEcheancierOuvert,
                  )
                }
                disabled={!jeton}
                aria-expanded={echeancierOuvert}
              >
                Échéancier fiscal
              </button>
            </Tooltip>
            <Tooltip label="Civisme déclaratif : rapprochement déterministe entre l'échéancier fiscal théorique de l'exercice revu et les pièces collectées en data room — taux de civisme, échéances couvertes, en attente ou manquantes. Consultatif : à vérifier auprès du client.">
              <button
                type="button"
                className={`btn btn-ghost btn-sm dossier2-action rest-civisme-btn${
                  civismeOuvert ? " is-actif" : ""
                }`}
                onClick={() =>
                  togglePanneau("civisme", civismeOuvert, setCivismeOuvert)
                }
                disabled={!jeton}
                aria-expanded={civismeOuvert}
              >
                Civisme déclaratif
              </button>
            </Tooltip>
            <Tooltip label="Prescription des risques : analyse déterministe du délai de reprise de droit commun — risques prescrits à basculer, proches de prescription (<12 mois) et non prescrits, avec exposition prescrite. Consultative : l'humain décide.">
              <button
                type="button"
                className={`btn btn-ghost btn-sm dossier2-action rest-prescription-btn${
                  prescriptionOuverte ? " is-actif" : ""
                }`}
                onClick={() =>
                  togglePanneau(
                    "prescription",
                    prescriptionOuverte,
                    setPrescriptionOuverte,
                  )
                }
                disabled={!jeton}
                aria-expanded={prescriptionOuverte}
              >
                Prescription
              </button>
            </Tooltip>
            <Tooltip label="Plan d'actions post-revue : une action suggérée par risque non clos du client — déclaration rectificative, provision à documenter, justificatif à collecter ou point à discuter, avec priorité et motifs. Consultatif : le fiscaliste apprécie, le client décide.">
              <button
                type="button"
                className={`btn btn-ghost btn-sm dossier2-action rest-planactions-btn${
                  planActionsOuvert ? " is-actif" : ""
                }`}
                onClick={() =>
                  togglePanneau(
                    "plan_actions",
                    planActionsOuvert,
                    setPlanActionsOuvert,
                  )
                }
                disabled={!jeton}
                aria-expanded={planActionsOuvert}
              >
                Plan d'actions
              </button>
            </Tooltip>
            <Tooltip label="Demande de renseignements et de documents au client — questions de la revue analytique et pièces manquantes, numérotées pour réponse">
              <button
                type="button"
                className="btn btn-ghost btn-sm dossier2-action rest-demande-btn"
                onClick={() => void telechargerDemandeRenseignements()}
                disabled={demandeBusy || !jeton}
              >
                {demandeBusy ? "Demande…" : "Demande de renseignements"}
              </button>
            </Tooltip>
            {demandeErr && (
              <span className="rest-lettre-err" role="alert">
                {demandeErr}
              </span>
            )}
            {suivi && suivi.synthese.total > 0 && (
              <Tooltip label="Suivi des réponses client à la demande de renseignements : marquez chaque item reçu / sans objet, planifiez les relances.">
                <button
                  type="button"
                  className={`btn btn-ghost btn-sm dossier2-action rest-suivi-btn${
                    suiviOuvert ? " is-actif" : ""
                  }`}
                  onClick={() =>
                    togglePanneau("suivi", suiviOuvert, setSuiviOuvert, () => {
                      void chargerSuivi();
                      void chargerReponses();
                    })
                  }
                  aria-expanded={suiviOuvert}
                >
                  <span
                    className={`rest-suivi-compteur${
                      suivi.synthese.a_relancer > 0 ? " relance" : ""
                    }`}
                  >
                    {suivi.synthese.recu}/{suivi.synthese.total} reçues
                    {suivi.synthese.a_relancer > 0
                      ? ` · ${suivi.synthese.a_relancer} à relancer`
                      : ""}
                  </span>
                </button>
              </Tooltip>
            )}
          </div>
        </div>

        <div className="dossier2-groupe" role="group" aria-label="Restituer">
          <span className="dossier2-groupe-lbl">Restituer</span>
          <div className="dossier2-groupe-actions">
            <Tooltip label={PROCESS_TIPS.exportWord}>
              <button
                type="button"
                className="btn btn-ghost btn-sm dossier2-action"
                onClick={() => onExport("docx")}
                disabled={sansExecution}
              >
                Word
              </button>
            </Tooltip>
            <Tooltip label={PROCESS_TIPS.exportPdf}>
              <button
                type="button"
                className="btn btn-ghost btn-sm dossier2-action"
                onClick={() => onExport("pdf")}
                disabled={sansExecution}
              >
                PDF
              </button>
            </Tooltip>
            <Tooltip label="Note de synthèse de mission (executive summary IA) pour l'associé signataire — versionnée, chaque constat cite sa règle. Consultative : l'humain valide.">
              <button
                type="button"
                className={`btn btn-ghost btn-sm dossier2-action rest-note-btn${
                  noteOuverte ? " is-actif" : ""
                }`}
                onClick={() =>
                  togglePanneau("note", noteOuverte, setNoteOuverte)
                }
                disabled={!jeton}
                aria-expanded={noteOuverte}
              >
                Note de synthèse
              </button>
            </Tooltip>
            <Tooltip label="Lettre de mission (.docx) générée depuis le cadrage — à personnaliser et faire signer avant les travaux. Champs manquants : [à compléter].">
              <button
                type="button"
                className="btn btn-ghost btn-sm dossier2-action rest-lettre-btn"
                onClick={() => void telechargerLettreMission()}
                disabled={lettreBusy || !jeton}
              >
                {lettreBusy ? "Lettre…" : "Lettre de mission"}
              </button>
            </Tooltip>
            {lettreErr && (
              <span className="rest-lettre-err" role="alert">
                {lettreErr}
              </span>
            )}
            <Tooltip label="Courrier d'envoi du rapport (.docx) — lettre d'accompagnement à en-tête du cabinet : livrables remis, principaux constats chiffrés, invitation à la réunion de restitution, signature associé.">
              <button
                type="button"
                className="btn btn-ghost btn-sm dossier2-action rest-courrier-envoi-btn"
                onClick={() => void telechargerCourrierEnvoi()}
                disabled={courrierEnvoiBusy || !jeton}
              >
                {courrierEnvoiBusy ? "Courrier…" : "Courrier d'envoi"}
              </button>
            </Tooltip>
            {courrierEnvoiErr && (
              <span className="rest-lettre-err" role="alert">
                {courrierEnvoiErr}
              </span>
            )}
            <Tooltip label="Lettre d'affirmation de la direction (.docx) — à en-tête du client, adressée au cabinet : la direction confirme l'exhaustivité des informations transmises (comptabilité/FEC, déclarations, litiges et contrôles en cours, passifs fiscaux, réponses). À faire signer par le représentant légal avant la clôture.">
              <button
                type="button"
                className="btn btn-ghost btn-sm dossier2-action rest-affirmation-btn"
                onClick={() => void telechargerLettreAffirmation()}
                disabled={affirmationBusy || !jeton}
              >
                {affirmationBusy ? "Lettre…" : "Lettre d'affirmation"}
              </button>
            </Tooltip>
            {affirmationErr && (
              <span className="rest-lettre-err" role="alert">
                {affirmationErr}
              </span>
            )}
            <Tooltip label={PROCESS_TIPS.audit}>
              <button
                type="button"
                className="btn btn-ghost btn-sm dossier2-action"
                disabled={busy}
                onClick={() => {
                  onAudit();
                  allerSection("audit");
                }}
              >
                Audit
              </button>
            </Tooltip>
          </div>
        </div>

        {!estLecteur &&
          (onLienClient ||
            (!estCloturee && onCloturer && !sansExecution) ||
            (estCloturee && onReouvrir)) && (
            <div className="dossier2-groupe" role="group" aria-label="Clôturer">
              <span className="dossier2-groupe-lbl">Clôturer</span>
              <div className="dossier2-groupe-actions">
                <Tooltip label="Bilan de pré-clôture consultatif : ce qui reste en suspens (visas, temps, demande de renseignements, note de synthèse, data room, risques). Jamais bloquant — la clôture reste possible telle quelle.">
                  <button
                    type="button"
                    className={`btn btn-ghost btn-sm dossier2-action${
                      bilanClotureOuvert ? " is-actif" : ""
                    }`}
                    disabled={busy}
                    aria-expanded={bilanClotureOuvert}
                    onClick={() =>
                      togglePanneau(
                        "bilan_cloture",
                        bilanClotureOuvert,
                        setBilanClotureOuvert,
                      )
                    }
                  >
                    Bilan de clôture
                  </button>
                </Tooltip>
                {onLienClient && (
                  <Tooltip label={PROCESS_TIPS.lienClient}>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm dossier2-action"
                      onClick={onLienClient}
                      disabled={busy}
                    >
                      Lien client
                    </button>
                  </Tooltip>
                )}
                {!estCloturee && onCloturer && !sansExecution && (
                  <Tooltip label="Revue qualité de pré-clôture (consultative) puis clôture du dossier (statut serveur). Réouverture possible — l’épinglage référentiel est conservé.">
                    <button
                      type="button"
                      className={`btn btn-ghost btn-sm dossier2-action${
                        ctrlClotureOuvert ? " is-actif" : ""
                      }`}
                      disabled={busy || ctrlClotureBusy}
                      aria-expanded={ctrlClotureOuvert}
                      onClick={() => {
                        if (ctrlClotureOuvert) {
                          setCtrlClotureOuvert(false);
                          setCtrlCloture(null);
                          setCtrlClotureErr(null);
                        } else {
                          fermerPanneaux("ctrlCloture");
                          void ouvrirControleCloture();
                        }
                      }}
                    >
                      {ctrlClotureBusy ? "Contrôle…" : "Clôturer"}
                    </button>
                  </Tooltip>
                )}
                {estCloturee && onReouvrir && (
                  <Tooltip label="Repasse la mission en cours pour permettre une nouvelle exécution sur la même version épinglée.">
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm dossier2-action"
                      disabled={busy}
                      onClick={onReouvrir}
                    >
                      Réouvrir
                    </button>
                  </Tooltip>
                )}
              </div>
            </div>
          )}
      </div>

      {ctrlClotureOuvert && (
        <section
          className="rest-ctrl-cloture"
          aria-label="Contrôle qualité de pré-clôture"
        >
          <div className="rest-ctrl-cloture-head">
            <h3 className="rest-ctrl-cloture-titre label-with-tip">
              Contrôle qualité de pré-clôture
              <InfoTip
                label="Revue déterministe avant clôture (esprit NEP / ISQM) : points instruits, risques traités ou acceptés, livrables produits. Consultatif : la clôture reste toujours possible — l'associé décide."
                ariaLabel="Aide : contrôle de pré-clôture"
              />
            </h3>
            {ctrlCloture && (
              <span
                className={`badge rest-ctrl-cloture-verdict ${
                  ctrlCloture.cloture_recommandee ? "ok" : "bloquant"
                }`}
              >
                {ctrlCloture.cloture_recommandee
                  ? "Clôture recommandée"
                  : "Clôture non recommandée"}
              </span>
            )}
          </div>
          {ctrlClotureBusy && <p className="muted">Contrôle en cours…</p>}
          {ctrlClotureErr && (
            <p className="rest-lettre-err" role="alert">
              Contrôle indisponible : {ctrlClotureErr}
            </p>
          )}
          {ctrlCloture && (
            <>
              <ul className="rest-ctrl-cloture-points">
                {ctrlCloture.points.map((p) => (
                  <li key={p.code} className="rest-ctrl-cloture-point">
                    <span
                      className={`rest-ctrl-cloture-pastille ${p.statut}`}
                      aria-label={libelleStatutControle(p.statut)}
                      title={libelleStatutControle(p.statut)}
                    />
                    <span className="rest-ctrl-cloture-libelle">
                      {p.libelle}
                    </span>
                    <span className="rest-ctrl-cloture-detail">
                      {p.detail}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="rest-ctrl-cloture-synthese muted">
                {ctrlCloture.synthese.ok} OK ·{" "}
                {ctrlCloture.synthese.attention} attention ·{" "}
                {ctrlCloture.synthese.bloquant} bloquant
                {ctrlCloture.synthese.bloquant > 1 ? "s" : ""}
              </p>
            </>
          )}
          <div className="rest-ctrl-cloture-actions">
            <Tooltip label="Clôture le dossier malgré les éventuels points en attente — le contrôle est consultatif, la décision reste humaine.">
              <button
                type="button"
                className="btn btn-sm"
                disabled={busy || ctrlClotureBusy}
                onClick={confirmerCloture}
              >
                Confirmer la clôture
              </button>
            </Tooltip>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setCtrlClotureOuvert(false);
                setCtrlCloture(null);
                setCtrlClotureErr(null);
              }}
            >
              Annuler
            </button>
          </div>
        </section>
      )}

      {comparatifOuvert && (
        <section
          className="rest-comparatif"
          aria-label="Comparatif entre deux exécutions"
        >
          <div className="rest-comparatif-head">
            <h3 className="rest-comparatif-titre label-with-tip">
              Comparatif des exécutions
              {comparatif && (
                <span className="rest-comparatif-execs">
                  Exécution #{comparatif.execution_a.id} → #
                  {comparatif.execution_b.id}
                </span>
              )}
              <InfoTip
                label="Comparaison déterministe des conclusions règle par règle entre l'avant-dernière et la dernière exécution : ce qui s'est amélioré après les réponses client, ce qui s'est dégradé, ce qui reste à instruire."
                ariaLabel="Aide : comparatif des exécutions"
              />
            </h3>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setComparatifOuvert(false)}
            >
              Fermer
            </button>
          </div>
          {comparatifBusy && <p className="muted">Comparaison en cours…</p>}
          {comparatifErr && (
            <p className="rest-lettre-err" role="alert">
              Comparatif indisponible : {comparatifErr}
            </p>
          )}
          {comparatif && (
            <>
              <p className="rest-comparatif-synthese">
                <span className="badge rest-comparatif-badge amelioration">
                  {comparatif.synthese.ameliorations} amélioration
                  {comparatif.synthese.ameliorations > 1 ? "s" : ""}
                </span>{" "}
                <span className="badge rest-comparatif-badge degradation">
                  {comparatif.synthese.degradations} dégradation
                  {comparatif.synthese.degradations > 1 ? "s" : ""}
                </span>{" "}
                <span className="badge rest-comparatif-badge inchange">
                  {comparatif.synthese.inchanges_a_risque} inchangé
                  {comparatif.synthese.inchanges_a_risque > 1 ? "s" : ""} à
                  risque
                </span>{" "}
                <span className="muted">
                  · {comparatif.synthese.nouveaux} nouveau
                  {comparatif.synthese.nouveaux > 1 ? "x" : ""} ·{" "}
                  {comparatif.synthese.disparus} disparu
                  {comparatif.synthese.disparus > 1 ? "s" : ""} · Δ montant
                  anomalies :{" "}
                  {fmtMontant(comparatif.synthese.delta_montant_anomalies)}
                </span>
              </p>
              {(
                [
                  {
                    cle: "amelioration",
                    titre: "Améliorations",
                    items: comparatif.ameliorations,
                    vide: "Aucune amélioration entre les deux exécutions.",
                  },
                  {
                    cle: "degradation",
                    titre: "Dégradations",
                    items: comparatif.degradations,
                    vide: "Aucune dégradation entre les deux exécutions.",
                  },
                  {
                    cle: "inchange",
                    titre: "Inchangés à risque",
                    items: comparatif.inchanges_a_risque,
                    vide: "Aucun constat toujours à risque dans les deux exécutions.",
                  },
                ] as const
              ).map((bloc) => (
                <div
                  key={bloc.cle}
                  className={`rest-comparatif-bloc ${bloc.cle}`}
                >
                  <h4 className="rest-comparatif-bloc-titre">
                    {bloc.titre} ({bloc.items.length})
                  </h4>
                  {bloc.items.length === 0 ? (
                    <p className="muted">{bloc.vide}</p>
                  ) : (
                    <ul className="rest-comparatif-items">
                      {bloc.items.map((it) => (
                        <li
                          key={`${bloc.cle}:${it.regle_id}`}
                          className="rest-comparatif-item"
                        >
                          <span className="rest-comparatif-regle">
                            {it.regle_id}
                          </span>
                          <span className="rest-comparatif-transition">
                            {libelleStatutComparatif(it.avant)} →{" "}
                            {libelleStatutComparatif(it.apres)}
                          </span>
                          <span className="rest-comparatif-montants muted">
                            {it.montant_avant !== null
                              ? fmtMontant(it.montant_avant)
                              : "—"}{" "}
                            →{" "}
                            {it.montant_apres !== null
                              ? fmtMontant(it.montant_apres)
                              : "—"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
              {(comparatif.nouveaux.length > 0 ||
                comparatif.disparus.length > 0) && (
                <div className="rest-comparatif-bloc neutre">
                  <h4 className="rest-comparatif-bloc-titre">
                    Nouveaux et disparus
                  </h4>
                  <ul className="rest-comparatif-items">
                    {comparatif.nouveaux.map((it) => (
                      <li
                        key={`nouveau:${it.regle_id}`}
                        className="rest-comparatif-item"
                      >
                        <span className="rest-comparatif-regle">
                          {it.regle_id}
                        </span>
                        <span className="rest-comparatif-transition">
                          Nouveau constat :{" "}
                          {libelleStatutComparatif(it.apres)}
                        </span>
                        <span className="rest-comparatif-montants muted">
                          {it.montant_apres !== null
                            ? fmtMontant(it.montant_apres)
                            : "—"}
                        </span>
                      </li>
                    ))}
                    {comparatif.disparus.map((it) => (
                      <li
                        key={`disparu:${it.regle_id}`}
                        className="rest-comparatif-item"
                      >
                        <span className="rest-comparatif-regle">
                          {it.regle_id}
                        </span>
                        <span className="rest-comparatif-transition">
                          Constat disparu (était{" "}
                          {libelleStatutComparatif(it.avant)})
                        </span>
                        <span className="rest-comparatif-montants muted">
                          {it.montant_avant !== null
                            ? fmtMontant(it.montant_avant)
                            : "—"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </section>
      )}

      {suiviOuvert && (
        <section
          className="rest-suivi"
          aria-label="Suivi des réponses client"
        >
          <div className="rest-suivi-head">
            <h3 className="rest-suivi-titre label-with-tip">
              Suivi des réponses client
              <InfoTip
                label="Circularisation de la demande de renseignements : la liste reprend les items du document (questions analytiques + pièces attendues). Statuts et relances sont enregistrés par mission."
                ariaLabel="Aide : suivi des réponses client"
              />
            </h3>
            <div className="rest-suivi-outils">
              {suivi && (
                <span className="muted">
                  {suivi.synthese.recu} reçue{suivi.synthese.recu > 1 ? "s" : ""} ·{" "}
                  {suivi.synthese.en_attente} en attente ·{" "}
                  {suivi.synthese.sans_objet} sans objet
                  {suivi.synthese.a_relancer > 0
                    ? ` · ${suivi.synthese.a_relancer} à relancer`
                    : ""}
                </span>
              )}
              {suivi && suivi.synthese.en_attente > 0 && (
                <Tooltip label="Courrier de relance DOCX listant les éléments toujours en attente, avec nouveau délai de 8 jours">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm rest-relance-btn"
                    onClick={() => void telechargerCourrierRelance()}
                    disabled={relanceBusy || !jeton}
                  >
                    {relanceBusy ? "Relance…" : "Courrier de relance"}
                  </button>
                </Tooltip>
              )}
              {suivi && suivi.synthese.en_attente > 0 && (
                <Tooltip label="Courrier de relance en texte brut (.txt) listant les éléments encore en attente — à relire et adapter avant envoi">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm rest-relance-btn"
                    onClick={() => void telechargerCourrierRelanceTxt()}
                    disabled={relanceBusy || !jeton}
                  >
                    {relanceBusy ? "Relance…" : "Courrier de relance (.txt)"}
                  </button>
                </Tooltip>
              )}
              {suivi &&
                suivi.items.some(
                  (it) => it.statut === "en_attente" && it.date_relance,
                ) && (
                  <Tooltip label="Après envoi du courrier : marque en un clic toutes les relances planifiées comme effectuées (trace la date, incrémente le compteur, efface les dates planifiées) — réversible en re-planifiant">
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm rest-relance-btn"
                      onClick={() => void marquerRelancesFaites()}
                      disabled={
                        estLecteur ||
                        estCloturee ||
                        relancesFaitesBusy ||
                        !jeton
                      }
                    >
                      {relancesFaitesBusy
                        ? "Marquage…"
                        : "Marquer les relances faites"}
                    </button>
                  </Tooltip>
                )}
              {relanceErr && (
                <span className="rest-lettre-err" role="alert">
                  {relanceErr}
                </span>
              )}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setSuiviOuvert(false)}
              >
                Fermer
              </button>
            </div>
          </div>
          {suivi && suivi.synthese.en_attente > 0 && (
            <div className="rest-suivi-controles rest-suivi-planif">
              <span className="muted">Planifier les relances</span>
              <label className="rest-suivi-champ">
                Date{" "}
                <input
                  type="date"
                  value={planifDate}
                  disabled={estLecteur || estCloturee || planifBusy}
                  onChange={(e) => setPlanifDate(e.target.value)}
                />
              </label>
              <Tooltip label="Fixe cette date de relance sur tous les items encore en attente qui n'ont pas déjà de date — les dates déjà saisies ne sont pas modifiées">
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => void planifierRelances()}
                  disabled={
                    estLecteur ||
                    estCloturee ||
                    planifBusy ||
                    !planifDate ||
                    !jeton
                  }
                >
                  {planifBusy
                    ? "Planification…"
                    : "Planifier (items sans date)"}
                </button>
              </Tooltip>
              {estCloturee && (
                <span className="muted">
                  Mission clôturée — action indisponible.
                </span>
              )}
              {planifOut && (
                <span className="muted" role="status">
                  {planifOut.planifiees} planifiée
                  {planifOut.planifiees > 1 ? "s" : ""} (
                  {planifOut.deja_planifiees} déjà planifiée
                  {planifOut.deja_planifiees > 1 ? "s" : ""})
                </span>
              )}
              {planifErr && (
                <span className="rest-lettre-err" role="alert">
                  {planifErr}
                </span>
              )}
            </div>
          )}
          {suiviErr && (
            <p className="rest-lettre-err" role="alert">
              {suiviErr}
            </p>
          )}
          {relanceItemMsg && (
            <p className="muted rest-suivi-relance-msg" role="status">
              {relanceItemMsg}
            </p>
          )}
          {suivi && suivi.items.length === 0 && (
            <p className="muted">
              Aucun item demandable : générez d'abord le commentaire
              analytique ou exécutez la mission.
            </p>
          )}
          {suivi && suivi.items.length > 0 && (
            <ul className="rest-suivi-items">
              {suivi.items.map((it) => {
                const relance = itemARelancer(it);
                return (
                  <li
                    key={it.cle_item}
                    className={`rest-suivi-item ${it.statut}${
                      relance ? " a-relancer" : ""
                    }`}
                  >
                    <div className="rest-suivi-libelle">
                      <span className="rest-suivi-cle">{it.cle_item}</span>
                      {it.libelle}
                      {relance && (
                        <span className="badge rest-suivi-badge-relance">
                          À relancer
                        </span>
                      )}
                    </div>
                    <div className="rest-suivi-controles">
                      <label className="rest-suivi-champ">
                        Statut{" "}
                        <select
                          value={it.statut}
                          disabled={estLecteur || suiviBusyCle === it.cle_item}
                          onChange={(e) =>
                            void majSuiviItem(it, {
                              statut: e.target.value as SuiviStatut,
                            })
                          }
                        >
                          {STATUTS_SUIVI.map((s) => (
                            <option key={s.value} value={s.value}>
                              {s.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="rest-suivi-champ">
                        Relance{" "}
                        <input
                          type="date"
                          value={it.date_relance ?? ""}
                          disabled={estLecteur || suiviBusyCle === it.cle_item}
                          onChange={(e) =>
                            void majSuiviItem(it, {
                              date_relance: e.target.value || null,
                            })
                          }
                        />
                      </label>
                      {it.statut === "en_attente" && it.date_relance && (
                        <span className="rest-suivi-relance-actions">
                          <Tooltip label="Marque la relance comme effectuée : la date de dernière relance est tracée, le compteur incrémenté et la date planifiée effacée">
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm rest-suivi-relance-faite"
                              disabled={
                                estLecteur ||
                                estCloturee ||
                                suiviBusyCle === it.cle_item ||
                                !jeton
                              }
                              onClick={() => void relanceFaite(it)}
                            >
                              Relance faite
                            </button>
                          </Tooltip>
                          {reportCle === it.cle_item ? (
                            <>
                              <input
                                type="date"
                                className="rest-suivi-report-date"
                                aria-label="Nouvelle date de relance"
                                value={reportDate}
                                disabled={
                                  estLecteur ||
                                  estCloturee ||
                                  suiviBusyCle === it.cle_item
                                }
                                onChange={(e) =>
                                  setReportDate(e.target.value)
                                }
                              />
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                disabled={
                                  estLecteur ||
                                  estCloturee ||
                                  suiviBusyCle === it.cle_item ||
                                  !reportDate ||
                                  !jeton
                                }
                                onClick={() => void reporterRelance(it)}
                              >
                                Confirmer le report
                              </button>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                disabled={suiviBusyCle === it.cle_item}
                                onClick={() => {
                                  setReportCle(null);
                                  setReportDate("");
                                }}
                              >
                                Annuler
                              </button>
                            </>
                          ) : (
                            <Tooltip label="Reporte la relance de cet item à une nouvelle date (à partir d'aujourd'hui)">
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm rest-suivi-relance-report"
                                disabled={
                                  estLecteur ||
                                  estCloturee ||
                                  suiviBusyCle === it.cle_item ||
                                  !jeton
                                }
                                onClick={() => {
                                  setReportCle(it.cle_item);
                                  setReportDate(it.date_relance ?? "");
                                }}
                              >
                                Reporter
                              </button>
                            </Tooltip>
                          )}
                        </span>
                      )}
                      {it.nb_relances > 0 && (
                        <span className="muted rest-suivi-relance-trace">
                          Relancé {it.nb_relances} fois
                          {it.derniere_relance_le
                            ? ` (dernière le ${it.derniere_relance_le
                                .split("-")
                                .reverse()
                                .join("/")})`
                            : ""}
                        </span>
                      )}
                      <label className="rest-suivi-champ rest-suivi-note">
                        Note{" "}
                        <input
                          type="text"
                          placeholder="ex : reçu par mail le…"
                          value={suiviNotes[it.cle_item] ?? ""}
                          disabled={estLecteur || suiviBusyCle === it.cle_item}
                          onChange={(e) =>
                            setSuiviNotes((prev) => ({
                              ...prev,
                              [it.cle_item]: e.target.value,
                            }))
                          }
                          onBlur={(e) => {
                            const note = e.target.value.trim() || null;
                            if (note !== (it.note ?? null)) {
                              void majSuiviItem(it, { note });
                            }
                          }}
                        />
                      </label>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm rest-reponse-btn"
                        disabled={estLecteur && !reponses[it.cle_item]}
                        onClick={() => ouvrirReponse(it.cle_item)}
                        aria-expanded={reponseOuverteCle === it.cle_item}
                      >
                        {reponses[it.cle_item]
                          ? "Réponse client ✓"
                          : "Saisir la réponse"}
                      </button>
                    </div>
                    {reponses[it.cle_item] &&
                      reponseOuverteCle !== it.cle_item && (
                        <div className="rest-reponse-resume">
                          <span className="rest-reponse-contenu">
                            {reponses[it.cle_item].contenu}
                          </span>
                          {reponses[it.cle_item].pieces_recues && (
                            <span className="muted">
                              {" "}
                              — Pièces : {reponses[it.cle_item].pieces_recues}
                            </span>
                          )}
                          <span className="muted">
                            {" "}
                            (saisie par {reponses[it.cle_item].saisie_par})
                          </span>
                          {reponses[it.cle_item]
                            .statut_derniere_execution ===
                            "non_verifiable" && (
                            <span className="badge rest-reponse-badge-attente">
                              Règle toujours non vérifiable — relancer une
                              exécution
                            </span>
                          )}
                        </div>
                      )}
                    {reponseOuverteCle === it.cle_item && (
                      <div className="rest-reponse-form">
                        <label className="rest-reponse-champ">
                          Réponse du client
                          <textarea
                            rows={3}
                            placeholder="Contenu de la réponse reçue…"
                            value={reponseContenu}
                            disabled={estLecteur || reponseBusy}
                            onChange={(e) =>
                              setReponseContenu(e.target.value)
                            }
                          />
                        </label>
                        <label className="rest-reponse-champ">
                          Pièces reçues (optionnel)
                          <input
                            type="text"
                            placeholder="ex : relevés bancaires, tableau d'amortissement…"
                            value={reponsePieces}
                            disabled={estLecteur || reponseBusy}
                            onChange={(e) =>
                              setReponsePieces(e.target.value)
                            }
                          />
                        </label>
                        {reponseErr && (
                          <p className="rest-lettre-err" role="alert">
                            {reponseErr}
                          </p>
                        )}
                        <div className="rest-reponse-actions">
                          <button
                            type="button"
                            className="btn btn-primary btn-sm"
                            disabled={
                              estLecteur ||
                              reponseBusy ||
                              !reponseContenu.trim()
                            }
                            onClick={() =>
                              void enregistrerReponse(it.cle_item)
                            }
                          >
                            {reponseBusy
                              ? "Enregistrement…"
                              : "Enregistrer la réponse"}
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            disabled={reponseBusy}
                            onClick={() => setReponseOuverteCle(null)}
                          >
                            Annuler
                          </button>
                          <span className="muted rest-reponse-aide">
                            L'enregistrement marque l'item « Reçu ».
                          </span>
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}

      {tempsOuvert && (
        <section className="rest-suivi rest-temps" aria-label="Temps passés">
          <div className="rest-suivi-head">
            <h3 className="rest-suivi-titre label-with-tip">
              Temps passés
              <InfoTip
                label="Saisie des heures par phase et par jour, par collaborateur. Le récapitulatif (total, répartition par phase et par collaborateur) sert au pilotage de la rentabilité de la mission."
                ariaLabel="Aide : temps passés"
              />
            </h3>
            <div className="rest-suivi-outils">
              {tempsRecap && (
                <span className="muted">
                  Total : {tempsRecap.total_heures} h
                  {Object.entries(tempsRecap.par_phase).length > 0 &&
                    " · " +
                      PHASES_TEMPS.filter(
                        (p) => tempsRecap.par_phase[p.value],
                      )
                        .map(
                          (p) =>
                            `${p.label} ${tempsRecap.par_phase[p.value]} h`,
                        )
                        .join(" · ")}
                </span>
              )}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setTempsOuvert(false)}
              >
                Fermer
              </button>
            </div>
          </div>
          {tempsErr && (
            <p className="rest-lettre-err" role="alert">
              {tempsErr}
            </p>
          )}
          {!estLecteur && (
            <div className="rest-suivi-controles rest-temps-form">
              <label className="rest-suivi-champ">
                Phase{" "}
                <select
                  value={tempsPhase}
                  disabled={tempsBusy}
                  onChange={(e) =>
                    setTempsPhase(e.target.value as TempsPhase)
                  }
                >
                  {PHASES_TEMPS.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="rest-suivi-champ">
                Date{" "}
                <input
                  type="date"
                  value={tempsDate}
                  disabled={tempsBusy}
                  onChange={(e) => setTempsDate(e.target.value)}
                />
              </label>
              <label className="rest-suivi-champ">
                Heures{" "}
                <input
                  type="number"
                  min={0.25}
                  max={24}
                  step={0.25}
                  placeholder="ex : 3.5"
                  value={tempsHeures}
                  disabled={tempsBusy}
                  onChange={(e) => setTempsHeures(e.target.value)}
                />
              </label>
              <label className="rest-suivi-champ rest-suivi-note">
                Note{" "}
                <input
                  type="text"
                  placeholder="ex : pointage des factures fournisseurs…"
                  value={tempsNote}
                  disabled={tempsBusy}
                  onChange={(e) => setTempsNote(e.target.value)}
                />
              </label>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={tempsBusy || !tempsHeures.trim() || !tempsDate}
                onClick={() => void saisirTemps()}
              >
                {tempsBusy ? "Saisie…" : "Ajouter"}
              </button>
            </div>
          )}
          {tempsRecap && tempsRecap.entrees.length === 0 && (
            <p className="muted">
              Aucun temps saisi sur cette mission pour l'instant.
            </p>
          )}
          {tempsRecap && tempsRecap.entrees.length > 0 && (
            <>
              <ul className="rest-suivi-items rest-temps-items">
                {tempsRecap.entrees.map((e) => (
                  <li key={e.id} className="rest-suivi-item">
                    <div className="rest-suivi-libelle">
                      <span className="rest-suivi-cle">{e.date_jour}</span>
                      {libellePhaseTemps(e.phase)} · {e.heures} h ·{" "}
                      {e.collaborateur}
                      {e.note && (
                        <span className="muted"> — {e.note}</span>
                      )}
                    </div>
                    {!estLecteur && (
                      <div className="rest-suivi-controles">
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          disabled={tempsSupprId !== null}
                          onClick={() => void supprimerTemps(e.id)}
                        >
                          {tempsSupprId === e.id
                            ? "Suppression…"
                            : "Supprimer"}
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
              <p className="muted rest-temps-collabs">
                Par collaborateur :{" "}
                {Object.entries(tempsRecap.par_collaborateur)
                  .map(([c, hres]) => `${c} ${hres} h`)
                  .join(" · ")}
              </p>
            </>
          )}
          <div className="rest-temps-renta">
            <h4 className="rest-suivi-titre label-with-tip">
              Rentabilité
              <InfoTip
                label="Honoraires forfaitaires convenus pour la mission et taux horaire standard du cabinet. Marge estimée = honoraires − (heures saisies × taux horaire)."
                ariaLabel="Aide : rentabilité"
              />
            </h4>
            {rentaErr && (
              <p className="rest-lettre-err" role="alert">
                {rentaErr}
              </p>
            )}
            {!estLecteur && (
              <div className="rest-suivi-controles rest-temps-form">
                <label className="rest-suivi-champ">
                  Honoraires convenus (FCFA){" "}
                  <input
                    type="number"
                    min={0}
                    step={1000}
                    placeholder="ex : 5000000"
                    value={rentaHonoraires}
                    disabled={rentaBusy}
                    onChange={(e) => setRentaHonoraires(e.target.value)}
                  />
                </label>
                <label className="rest-suivi-champ">
                  Taux horaire (FCFA){" "}
                  <input
                    type="number"
                    min={0}
                    step={1000}
                    placeholder="ex : 40000"
                    value={rentaTaux}
                    disabled={rentaBusy}
                    onChange={(e) => setRentaTaux(e.target.value)}
                  />
                </label>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={rentaBusy}
                  onClick={() => void enregistrerRentabilite()}
                >
                  {rentaBusy ? "Enregistrement…" : "Enregistrer"}
                </button>
              </div>
            )}
            {renta && (
              <p className="muted">
                {renta.cout_estime !== null && (
                  <>Coût estimé : {renta.cout_estime} FCFA</>
                )}
                {renta.marge_estimee !== null && (
                  <>
                    {" · "}Marge estimée :{" "}
                    <span
                      className={`badge rest-comparatif-badge ${
                        renta.marge_estimee.startsWith("-")
                          ? "degradation"
                          : "amelioration"
                      }`}
                    >
                      {renta.marge_estimee} FCFA
                      {renta.taux_marge_pct !== null &&
                        ` (${renta.taux_marge_pct} %)`}
                    </span>
                  </>
                )}
                {renta.cout_estime === null &&
                  renta.marge_estimee === null &&
                  "Renseignez le taux horaire (et les honoraires) pour estimer coût et marge."}
              </p>
            )}
          </div>
        </section>
      )}

      {sourcesOuvert && (
        <section
          className="rest-suivi rest-sources"
          aria-label="Sources et data room de la mission"
        >
          <div className="rest-suivi-head">
            <h3 className="rest-suivi-titre label-with-tip">
              Sources &amp; data room
              <InfoTip
                label="Pièces de la mission : la source comptable active et toutes les annexes déposées. La data room s'enrichit à tout moment de la mission."
                ariaLabel="Aide : sources et data room"
              />
            </h3>
            <div className="rest-suivi-outils">
              <span className="muted">
                {pieces.length} pièce{pieces.length !== 1 ? "s" : ""}
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setSourcesOuvert(false)}
              >
                Fermer
              </button>
            </div>
          </div>

          {estCloturee ? (
            <p className="muted">
              Mission clôturée — le dépôt de nouvelles pièces est désactivé.
            </p>
          ) : estLecteur ? (
            <p className="muted">
              Accès en lecture seule — dépôt de pièces indisponible.
            </p>
          ) : (
            <div className="rest-sources-depot">
              <label className="rest-sources-depot-type">
                Type de pièce{" "}
                <select
                  value={sourcesTypeDepot}
                  disabled={sourcesDepotBusy}
                  onChange={(e) => setSourcesTypeDepot(e.target.value)}
                >
                  {TYPES_PIECE_MISSION.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </label>
              <input
                type="file"
                multiple
                disabled={sourcesDepotBusy}
                aria-label="Déposer des pièces dans la data room"
                onChange={(e) => {
                  void deposerPiecesMission(e.target.files);
                  e.target.value = "";
                }}
              />
              <span className="muted">
                Tout format accepté — les pièces déposées ici enrichissent la
                revue sans remplacer la source comptable active.
              </span>
              {sourcesDepotBusy && (
                <span className="muted">Dépôt en cours…</span>
              )}
            </div>
          )}
          {sourcesDepotMsg && !sourcesDepotBusy && (
            <p className="rest-maj">{sourcesDepotMsg}</p>
          )}
          {sourcesDepotErr && !sourcesDepotBusy && (
            <p className="rest-lettre-err" role="alert">
              {sourcesDepotErr}
            </p>
          )}

          {pieces.length > 0 ? (
            <ul className="rest-suivi-items rest-sources-items">
              {pieces.map((p) => (
                <li key={p.id} className="rest-suivi-item">
                  <div className="rest-suivi-libelle">
                    <span className="rest-suivi-cle">
                      <span className="muted">#{p.id}</span> {p.nom_fichier}
                      {p.role === "source_active" && (
                        <span className="badge"> Source active</span>
                      )}
                    </span>
                    <span className="muted">
                      {libelleTypePieceMission(p.type_piece)}
                      {p.cree_le ? ` · déposée le ${p.cree_le.slice(0, 10)}` : ""}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">
              Aucune pièce dans la data room — déposez un premier document
              ci-dessus.
            </p>
          )}
        </section>
      )}

      {progOuvert && (
        <section
          className="rest-suivi rest-programme"
          aria-label="Programme de travail"
        >
          <div className="rest-suivi-head">
            <h3 className="rest-suivi-titre label-with-tip">
              Programme de travail
              <InfoTip
                label="Diligences standard par phase, cochées au fil de l'exécution — l'avancement par phase éclaire les visas de supervision."
                ariaLabel="Aide : programme de travail"
              />
            </h3>
            <div className="rest-suivi-outils">
              {progEtat && (
                <span className="muted">
                  {progEtat.synthese.faites}/{progEtat.synthese.total}{" "}
                  diligences · {progEtat.synthese.avancement_pct}%
                </span>
              )}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setProgOuvert(false)}
              >
                Fermer
              </button>
            </div>
          </div>
          {progErr && (
            <p className="rest-lettre-err" role="alert">
              {progErr}
            </p>
          )}
          {progEtat && (
            <ul className="rest-suivi-items rest-programme-items">
              {progEtat.phases.map((ph) => (
                <li key={ph.phase} className="rest-suivi-item">
                  <div className="rest-suivi-libelle">
                    <span className="rest-suivi-cle">
                      {libellePhaseTemps(ph.phase)}
                      <span className="muted">
                        {" "}
                        — {ph.faites}/{ph.total} · {ph.avancement_pct}%
                      </span>
                    </span>
                    <ul className="rest-programme-diligences">
                      {ph.diligences.map((d) => (
                        <li key={d.code} className="rest-programme-diligence">
                          <label>
                            <input
                              type="checkbox"
                              checked={d.fait}
                              disabled={estLecteur || progBusy !== null}
                              onChange={() =>
                                void cocherDiligence(d.code, !d.fait)
                              }
                            />{" "}
                            <span className="muted">{d.code}</span>{" "}
                            {d.libelle}
                            {d.fait && d.fait_par && d.fait_le && (
                              <span className="muted">
                                {" "}
                                — fait par {d.fait_par} le{" "}
                                {d.fait_le.slice(0, 10)}
                              </span>
                            )}
                          </label>
                        </li>
                      ))}
                    </ul>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {pilotageOuvert && (
        <PilotageVue
          missionId={r.mission_id}
          jeton={jeton}
          onFermer={() => setPilotageOuvert(false)}
          onOuvrirPanneau={(id) => {
            if (id === "civisme") {
              togglePanneau("civisme", civismeOuvert, setCivismeOuvert);
            } else {
              togglePanneau(
                "plan_actions",
                planActionsOuvert,
                setPlanActionsOuvert,
              );
            }
          }}
        />
      )}

      {echeancierOuvert && (
        <EcheancierFiscalVue
          missionId={r.mission_id}
          jeton={jeton}
          onFermer={() => setEcheancierOuvert(false)}
        />
      )}

      {civismeOuvert && (
        <CivismeVue
          missionId={r.mission_id}
          jeton={jeton}
          missionCloturee={estCloturee}
          onFermer={() => setCivismeOuvert(false)}
        />
      )}

      {prescriptionOuverte && (
        <PrescriptionVue
          missionId={r.mission_id}
          jeton={jeton}
          onFermer={() => setPrescriptionOuverte(false)}
        />
      )}

      {planActionsOuvert && (
        <PlanActionsVue
          missionId={r.mission_id}
          jeton={jeton}
          estCloturee={estCloturee}
          estLecteur={estLecteur}
          onFermer={() => setPlanActionsOuvert(false)}
        />
      )}

      {bilanClotureOuvert && (
        <BilanClotureVue
          missionId={r.mission_id}
          jeton={jeton}
          onFermer={() => setBilanClotureOuvert(false)}
        />
      )}

      {visasOuvert && (
        <section
          className="rest-suivi rest-visas"
          aria-label="Visas de supervision"
        >
          <div className="rest-suivi-head">
            <h3 className="rest-suivi-titre label-with-tip">
              Visas de supervision
              <InfoTip
                label="Un visa par phase et par rôle, dans l'ordre : préparateur, puis réviseur, puis associé. La révocation suit l'ordre inverse (le rang supérieur d'abord)."
                ariaLabel="Aide : visas de supervision"
              />
            </h3>
            <div className="rest-suivi-outils">
              {visasEtat && (
                <span className="muted">
                  {visasEtat.synthese.phases_completes}/
                  {visasEtat.phases.length} phases complètes ·{" "}
                  {visasEtat.synthese.total_visas} visas
                </span>
              )}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setVisasOuvert(false)}
              >
                Fermer
              </button>
            </div>
          </div>
          {visasErr && (
            <p className="rest-lettre-err" role="alert">
              {visasErr}
            </p>
          )}
          {visasEtat && (
            <ul className="rest-suivi-items rest-visas-items">
              {visasEtat.phases.map((ph) => {
                const parRole = new Map(
                  ph.visas.map((v) => [v.role, v]),
                );
                return (
                  <li key={ph.phase} className="rest-suivi-item">
                    <div className="rest-suivi-libelle">
                      <span className="rest-suivi-cle">
                        {libellePhaseTemps(ph.phase)}
                        {ph.complet && (
                          <span className="muted"> — complète</span>
                        )}
                      </span>
                      <div className="rest-visas-roles">
                        {ROLES_VISA.map((rl) => {
                          const visa = parRole.get(rl.value);
                          const cle = `${ph.phase}/${rl.value}`;
                          return (
                            <span
                              key={rl.value}
                              className="rest-visas-role"
                            >
                              {rl.label} :{" "}
                              {visa ? (
                                <>
                                  visé par {visa.vise_par} le{" "}
                                  {visa.vise_le.slice(0, 10)}
                                  {visa.commentaire && (
                                    <span className="muted">
                                      {" "}
                                      — {visa.commentaire}
                                    </span>
                                  )}
                                  {!estLecteur && (
                                    <button
                                      type="button"
                                      className="btn btn-ghost btn-sm"
                                      disabled={visaBusy !== null}
                                      onClick={() =>
                                        void revoquerVisa(
                                          ph.phase,
                                          rl.value,
                                        )
                                      }
                                    >
                                      {visaBusy === cle
                                        ? "Révocation…"
                                        : "Révoquer"}
                                    </button>
                                  )}
                                </>
                              ) : estLecteur ? (
                                <span className="muted">non visé</span>
                              ) : (
                                <button
                                  type="button"
                                  className="btn btn-ghost btn-sm"
                                  disabled={visaBusy !== null}
                                  onClick={() =>
                                    void poserVisa(ph.phase, rl.value)
                                  }
                                >
                                  {visaBusy === cle ? "Visa…" : "Viser"}
                                </button>
                              )}
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}

      {noteOuverte && (
        <section
          className="rest-note"
          aria-label="Note de synthèse de mission"
        >
          <div className="rest-note-head">
            <h3 className="rest-note-titre label-with-tip">
              Note de synthèse
              <InfoTip
                label="Executive summary généré par IA à partir des seules données de la mission : chaque constat cite la règle (regle_id) dont il provient — rien n'est inventé. Document consultatif versionné, à relire avant signature."
                ariaLabel="Aide : note de synthèse"
              />
            </h3>
            <div className="rest-note-outils">
              {noteVersions.length > 0 && (
                <label className="rest-note-version">
                  Version{" "}
                  <select
                    value={noteVersionSel ?? ""}
                    onChange={(e) =>
                      setNoteVersionSel(
                        e.target.value ? Number(e.target.value) : null,
                      )
                    }
                  >
                    {noteVersions.map((v) => (
                      <option key={v.id} value={v.version}>
                        v{v.version} ·{" "}
                        {v.statut === "disponible"
                          ? "disponible"
                          : v.statut === "echec"
                            ? "échec"
                            : "en cours"}
                        {v.cree_le
                          ? ` · ${fmtHorodatage(v.cree_le)}`
                          : ""}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <button
                type="button"
                className="btn btn-sm rest-note-generer"
                onClick={() => void genererNote()}
                disabled={noteBusy || !jeton}
              >
                {noteBusy ? "Génération…" : "Générer"}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setNoteOuverte(false)}
              >
                Fermer
              </button>
            </div>
          </div>
          {noteErr && (
            <p className="rest-note-erreur" role="alert">
              {noteErr}
            </p>
          )}
          {noteVersions.length === 0 && !noteBusy && !noteErr && (
            <p className="rest-note-vide">
              Aucune note générée pour cette mission. Cliquez sur « Générer »
              pour produire la première version (quelques secondes).
            </p>
          )}
          {noteDetail?.statut === "echec" && (
            <p className="rest-note-erreur" role="alert">
              Génération v{noteDetail.version} en échec
              {noteDetail.erreur ? ` : ${noteDetail.erreur}` : "."}
            </p>
          )}
          {noteDetail?.statut === "disponible" && noteDetail.contenu && (
            <div className="rest-note-corps">
              {noteDetail.contenu.contexte && (
                <div className="rest-note-bloc">
                  <h4>Contexte et périmètre</h4>
                  <p>{noteDetail.contenu.contexte}</p>
                </div>
              )}
              <div className="rest-note-bloc">
                <h4>Principaux constats</h4>
                {noteDetail.contenu.constats.length === 0 ? (
                  <p className="rest-note-vide">
                    Aucun constat sourcé par une règle dans cette version.
                  </p>
                ) : (
                  <ul className="rest-note-constats">
                    {noteDetail.contenu.constats.map((c, i) => (
                      <li
                        key={`${c.regle_id}-${i}`}
                        className={`rest-note-constat ${c.gravite}`}
                      >
                        <span
                          className={`rest-note-gravite ${c.gravite}`}
                        >
                          {libelleGraviteNote(c.gravite)}
                        </span>
                        <button
                          type="button"
                          className="rest-note-regle"
                          onClick={() => allerRegleNote(c.regle_id)}
                          title="Voir la conclusion de cette règle dans la restitution"
                        >
                          {c.regle_id}
                        </button>
                        <span className="rest-note-resume">{c.resume}</span>
                        {c.montant && (
                          <span className="rest-note-montant">
                            {fmtMontant(c.montant)} FCFA
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              {noteDetail.contenu.exposition && (
                <div className="rest-note-bloc">
                  <h4>Exposition estimée</h4>
                  <p>{noteDetail.contenu.exposition}</p>
                </div>
              )}
              {noteDetail.contenu.points_attention.length > 0 && (
                <div className="rest-note-bloc">
                  <h4>Points d'attention</h4>
                  <ul className="rest-note-liste">
                    {noteDetail.contenu.points_attention.map((p, i) => (
                      <li key={i}>{p}</li>
                    ))}
                  </ul>
                </div>
              )}
              {noteDetail.contenu.recommandations.length > 0 && (
                <div className="rest-note-bloc">
                  <h4>Recommandations prioritaires</h4>
                  <ul className="rest-note-liste">
                    {noteDetail.contenu.recommandations.map((p, i) => (
                      <li key={i}>{p}</li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="rest-note-mention">
                Note générée par IA (v{noteDetail.version}
                {noteDetail.auteur ? ` · ${noteDetail.auteur}` : ""}) à
                partir des seules données de la mission — document
                consultatif, à relire et valider avant diffusion.
              </p>
            </div>
          )}
        </section>
      )}

      <header className="rest-hero">
        <p className="rest-eyebrow">Dossier de revue fiscale</p>
        <h2 className="rest-hero-title">
          {id.contribuable_denomination || `Mission #${r.mission_id}`}
        </h2>
        <div className="rest-hero-meta">
          <span>Mission #{r.mission_id}</span>
          {id.exercice != null && <span>Exercice {id.exercice}</span>}
          {r.execution_id != null && <span>Exécution #{r.execution_id}</span>}
          <span className={`badge statut-${statutMission}`}>
            {libelleStatut(statutMission)}
          </span>
          {id.revue_partielle ? (
            <span className="badge badge-partielle">Revue partielle</span>
          ) : null}
          {id.type_engagement_libelle ? (
            <span>{id.type_engagement_libelle}</span>
          ) : null}
          {id.contribuable_ncc && <span>NCC {id.contribuable_ncc}</span>}
        </div>
        {(refLibelle || refId != null) && (
          <p className="rest-ref-pin label-with-tip" role="status">
            Référentiel épinglé{" "}
            <strong>{refLibelle ?? "—"}</strong>
            {refId != null ? ` · id=${refId}` : ""}
            <InfoTip
              label={PROCESS_TIPS.epingle}
              ariaLabel="Aide : épinglage du référentiel"
            />
          </p>
        )}
        <dl className="rest-id-strip">
          <div>
            <dt className="label-with-tip">
              Forme
              <InfoTip
                label={PROCESS_TIPS.formeJuridique}
                ariaLabel="Aide : forme"
              />
            </dt>
            <dd>
              {(id.contribuable_forme || "—").toString().toUpperCase()}
              {id.contribuable_forme_juridique
                ? ` · ${id.contribuable_forme_juridique}`
                : ""}
            </dd>
          </div>
          <div>
            <dt className="label-with-tip">
              Régime
              <InfoTip
                label={PROCESS_TIPS.regime}
                ariaLabel="Aide : régime fiscal"
              />
            </dt>
            <dd>
              {id.contribuable_regime_fiscal || String(profil.regime ?? "—")}
            </dd>
          </div>
          {id.contribuable_rccm && (
            <div>
              <dt>RCCM</dt>
              <dd>{id.contribuable_rccm}</dd>
            </div>
          )}
          {id.contribuable_dfe && (
            <div>
              <dt>Réf. DFE</dt>
              <dd>{id.contribuable_dfe}</dd>
            </div>
          )}
          {(id.contribuable_commune || id.contribuable_siege) && (
            <div>
              <dt>Siège effectif</dt>
              <dd>
                {[id.contribuable_commune, id.contribuable_siege]
                  .filter(Boolean)
                  .join(" · ")}
              </dd>
            </div>
          )}
          {id.contribuable_centre_impots && (
            <div>
              <dt>Centre des impôts</dt>
              <dd>{id.contribuable_centre_impots}</dd>
            </div>
          )}
          <div>
            <dt className="label-with-tip">
              Profil
              <InfoTip
                label={
                  profil.cross_border
                    ? PROCESS_TIPS.crossBorder
                    : "Profil de mission (forme, secteur, cross-border) — cadrage pour le référentiel épinglé, pas un barème saisi à l’écran."
                }
                ariaLabel="Aide : profil mission"
              />
            </dt>
            <dd>
              {String(profil.forme_juridique ?? "—")}
              {profil.secteur ? ` · ${String(profil.secteur)}` : ""}
              {profil.cross_border ? " · cross-border" : ""}
            </dd>
          </div>
        </dl>
      </header>

      <section className="rest-cadrage engagement-block" aria-label="Cadrage mission">
        <div className="legal-block-head">
          <p className="picker-kicker label-with-tip">
            Cadrage d’engagement
            <InfoTip
              label={PROCESS_TIPS.typeEngagement}
              ariaLabel="Aide : cadrage mission"
            />
          </p>
          <p className="picker-hint">
            {cadrageEditable
              ? "Modifiable tant que la mission est en cadrage."
              : "Cadrage gelé — type, périmètre, objectifs, exclusions et seuil ne sont plus modifiables."}
            {cadragePerimetre.length > 0 ? (
              <>
                {" "}
                <span className="badge badge-partielle">Revue partielle</span>
              </>
            ) : null}
          </p>
        </div>
        {cadrageGele ? (
          <p className="rest-comment" role="status">
            Cadrage gelé (mission {libelleStatut(statutMission)}).
          </p>
        ) : null}
        <div className="field-grid field-grid-2">
          <label className="field">
            <span className="field-label-static">Type d’engagement</span>
            <select
              className="field-input"
              value={cadrageType}
              disabled={!cadrageEditable || estLecteur || cadrageBusy}
              onChange={(e) => setCadrageType(e.target.value)}
            >
              {TYPES_ENGAGEMENT.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label-static">
              Seuil de signification (FCFA)
            </span>
            <input
              className="field-input"
              type="number"
              min={0}
              step="1"
              value={cadrageSeuil}
              disabled={!cadrageEditable || estLecteur || cadrageBusy}
              onChange={(e) => setCadrageSeuil(e.target.value)}
            />
          </label>
        </div>
        <div className="impot-perimetre">
          <p className="label-with-tip impot-perimetre-lbl">Périmètre impôts</p>
          <div
            className="impot-chips"
            role="group"
            aria-label="Codes impôts du périmètre"
          >
            {CODES_IMPOT_PIVOT.map((code) => {
              const checked = cadragePerimetre.includes(code);
              return (
                <Tooltip key={code} label={tipImpot(code)} side="bottom">
                  <label
                    className={`impot-chip${checked ? " is-on" : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!cadrageEditable || estLecteur || cadrageBusy}
                      onChange={() => {
                        setCadragePerimetre((prev) =>
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
          {(reglesDonsAllegements.dons.length > 0 ||
            reglesDonsAllegements.allegements.length > 0) && (
            <p
              className="field-hint impot-ref-signale"
              role="status"
            >
              Règles du millésime déjà touchées / marquées
              {reglesDonsAllegements.dons.length > 0 && (
                <>
                  {" "}
                  · dons :{" "}
                  <code>{reglesDonsAllegements.dons.join(", ")}</code>
                </>
              )}
              {reglesDonsAllegements.allegements.length > 0 && (
                <>
                  {" "}
                  · allègements (id) :{" "}
                  <code>{reglesDonsAllegements.allegements.join(", ")}</code>
                </>
              )}
              {" "}
              — identifiants issus de la restitution / a_confirmer, sans
              barème affiché ici.
            </p>
          )}
        </div>
        <div className="field">
          <p className="label-with-tip impot-perimetre-lbl">
            Objectifs de la mission
            <InfoTip
              label={PROCESS_TIPS.objectifsMission}
              ariaLabel="Aide : objectifs mission"
            />
          </p>
          <ul className="objectifs-edit-list">
            {cadrageObjectifs.map((lib, idx) => (
              <li key={`rest-obj-${idx}`}>
                <input
                  className="field-input"
                  type="text"
                  value={lib}
                  maxLength={500}
                  placeholder={`Objectif ${idx + 1}`}
                  aria-label={`Objectif ${idx + 1}`}
                  disabled={!cadrageEditable || estLecteur || cadrageBusy}
                  onChange={(e) => {
                    const v = e.target.value;
                    setCadrageObjectifs((prev) =>
                      prev.map((x, i) => (i === idx ? v : x)),
                    );
                  }}
                />
                {cadrageEditable && !estLecteur ? (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={cadrageObjectifs.length <= 1 || cadrageBusy}
                    aria-label={`Retirer l’objectif ${idx + 1}`}
                    onClick={() => {
                      setCadrageObjectifs((prev) =>
                        prev.length <= 1
                          ? prev
                          : prev.filter((_, i) => i !== idx),
                      );
                    }}
                  >
                    Retirer
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
          {cadrageEditable && !estLecteur ? (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={cadrageObjectifs.length >= 50 || cadrageBusy}
              onClick={() =>
                setCadrageObjectifs((prev) => [...prev, ""])
              }
            >
              Ajouter un objectif
            </button>
          ) : null}
        </div>
        <div className="field">
          <label className="field-label-static" htmlFor="rest-exclusions">
            Exclusions déclarées
          </label>
          <textarea
            id="rest-exclusions"
            className="field-input field-textarea"
            rows={2}
            value={cadrageExclusions}
            disabled={!cadrageEditable || estLecteur || cadrageBusy}
            onChange={(e) => setCadrageExclusions(e.target.value)}
            placeholder="Ex. hors contrôles sur place…"
          />
        </div>
        {cadrageEditable && !estLecteur ? (
          <div className="cta-row" style={{ marginTop: "0.75rem" }}>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={cadrageBusy}
              onClick={() => void sauverCadrage()}
            >
              Enregistrer le cadrage
            </button>
          </div>
        ) : null}
        {cadrageMsg ? (
          <p className="rest-comment" role="status">
            {cadrageMsg}
          </p>
        ) : null}
        {cadrageErr ? (
          <p className="rest-comment" role="alert">
            {cadrageErr}
          </p>
        ) : null}
      </section>

      {sansExecution && (
        <div className="a-confirmer-banner rest-banner" role="status">
          <p>
            <strong>Aucune exécution encore</strong> — importez une balance et
            lancez la revue pour produire le passage et les conclusions.
          </p>
          {!estLecteur && onReprendreImport && (
            <div className="cta-row" style={{ marginTop: "0.6rem" }}>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={onReprendreImport}
              >
                Reprendre l&apos;import
              </button>
            </div>
          )}
        </div>
      )}

      <section className="rest-verdict" aria-label="Verdict fiscal">
        <div className="rest-verdict-grid">
          <div className="rest-verdict-main">
            <span className="rest-verdict-k label-with-tip">
              Solde net
              <InfoTip
                label={PROCESS_TIPS.soldeNet}
                ariaLabel="Aide : solde net"
              />
            </span>
            <strong
              className={`rest-verdict-solde${soldePositif ? " pos" : " neg"}`}
            >
              {fmtMontant(r.passage.solde_net)}
            </strong>
            <span className="rest-verdict-hint">
              Réintégrations − déductions · montants moteur
            </span>
          </div>
          <div className="rest-verdict-sides">
            <div className="rest-verdict-side">
              <span className="rest-verdict-k label-with-tip">
                Réintégrations
                <InfoTip
                  label={PROCESS_TIPS.reintegration}
                  ariaLabel="Aide : réintégrations"
                />
              </span>
              <strong>{fmtMontant(r.passage.total_reintegration)}</strong>
            </div>
            <div className="rest-verdict-side">
              <span className="rest-verdict-k label-with-tip">
                Déductions
                <InfoTip
                  label={PROCESS_TIPS.deduction}
                  ariaLabel="Aide : déductions"
                />
              </span>
              <strong>{fmtMontant(r.passage.total_deduction)}</strong>
            </div>
            <div className="rest-verdict-side rest-score-soft">
              <span className="rest-verdict-k label-with-tip">
                Score risque
                <InfoTip
                  label={score.avertissement || PROCESS_TIPS.scoreRisque}
                  ariaLabel="Aide : score risque"
                />
              </span>
              <strong>{score.score}</strong>
              <div className="rest-gauge" aria-hidden="true">
                <i
                  style={{ width: `${jauge}%` }}
                  className={
                    nEleve > 0 ? "hot" : nMoyen > 0 ? "warm" : "cool"
                  }
                />
              </div>
              <span className="rest-kpi-foot">
                {nEleve} élevé · {nMoyen} moyen · {nFaible} faible
              </span>
            </div>
            <div className="rest-verdict-side">
              <span className="rest-verdict-k label-with-tip">
                Traitement
                <InfoTip
                  label={PROCESS_TIPS.traitement}
                  ariaLabel="Aide : traitement"
                />
              </span>
              <strong>{progressionTrait}%</strong>
              <div className="rest-gauge" aria-hidden="true">
                <i
                  style={{ width: `${progressionTrait}%` }}
                  className="cool"
                />
              </div>
              <span className="rest-kpi-foot">
                {ouverts} ouvert{ouverts > 1 ? "s" : ""} · {clotures} clos
              </span>
            </div>
          </div>
        </div>
        <p className="rest-disclaimer" role="note">
          {score.avertissement} Le suivi de traitement est un workflow cabinet —
          il ne modifie pas les montants du moteur.
        </p>
      </section>

      <div className="rest-alerts">
        <button
          type="button"
          className="rest-alerts-toggle"
          aria-expanded={alertesOuvertes}
          onClick={() => setAlertesOuvertes((v) => !v)}
        >
          <span>
            Contexte &amp; alertes
            {(r.a_confirmer_total ?? 0) > 0 && (
              <em className="rest-alerts-chip">
                {r.a_confirmer_total} a_confirmer
              </em>
            )}
            {(lienMsg || lienUrl) && (
              <em className="rest-alerts-chip">lien client</em>
            )}
          </span>
          <span aria-hidden="true">{alertesOuvertes ? "▴" : "▾"}</span>
        </button>
        {alertesOuvertes && (
          <div className="rest-alerts-body">
            {(r.a_confirmer_total ?? 0) > 0 && (
              <div
                className={`a-confirmer-banner rest-banner${acDetailOuvert ? " is-open" : " is-compact"}`}
                role="status"
              >
                <div className="a-confirmer-banner-head">
                  <p className="label-with-tip">
                    <strong>
                      {r.a_confirmer_total} mention
                      {(r.a_confirmer_total ?? 0) > 1 ? "s" : ""} a_confirmer
                    </strong>
                    <span className="a-confirmer-banner-short">
                      {" "}
                      — paramètres non certifiés (pas un blocage).
                    </span>
                    <InfoTip
                      label={PROCESS_TIPS.aConfirmer}
                      ariaLabel="Aide : mentions a_confirmer"
                    />
                  </p>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => setAcDetailOuvert((v) => !v)}
                    aria-expanded={acDetailOuvert}
                  >
                    {acDetailOuvert ? "Masquer" : "Détail"}
                  </button>
                </div>
                {acDetailOuvert && (
                  <>
                    {r.avertissement_a_confirmer && (
                      <p className="a-confirmer-avert">
                        {r.avertissement_a_confirmer}
                      </p>
                    )}
                    <ul className="a-confirmer-regles">
                      {(r.a_confirmer_regles || []).slice(0, 40).map((x) => (
                        <li key={x.regle_id}>
                          <code>{x.regle_id}</code> · {x.nb} mention
                          {x.nb > 1 ? "s" : ""}
                          {x.mentions?.length > 0 && (
                            <ul className="a-confirmer-mentions">
                              {x.mentions.slice(0, 6).map((m, i) => (
                                <li key={`${x.regle_id}-${i}`}>
                                  <span title={m}>
                                    {m.length > 140
                                      ? `${m.slice(0, 140)}…`
                                      : m}
                                  </span>
                                </li>
                              ))}
                              {x.mentions.length > 6 && (
                                <li className="muted">
                                  +{x.mentions.length - 6} autre
                                  {x.mentions.length - 6 > 1 ? "s" : ""}
                                </li>
                              )}
                            </ul>
                          )}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            )}

            {missionStatus && (
              <p
                className={`status rest-banner rest-status-compact${missionStatus.err ? " err" : ""}`}
                role="status"
              >
                {missionStatus.msg}
              </p>
            )}

            {(lienMsg || lienUrl) && (
              <div
                className="token-box rest-banner"
                role="region"
                aria-label="Lien client"
              >
                {lienUrl ? (
                  <>
                    <div className="token-box-head">
                      <strong className="label-with-tip">
                        Lien client
                        <InfoTip
                          label={PROCESS_TIPS.lienClient}
                          ariaLabel="Aide : lien client"
                        />
                      </strong>
                    </div>
                    <code className="token-value" tabIndex={0}>
                      {lienUrl}
                    </code>
                    <div className="cta-row" style={{ marginTop: "0.45rem" }}>
                      {onCopierLien && (
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          onClick={onCopierLien}
                        >
                          Copier le lien
                        </button>
                      )}
                    </div>
                    <p className="token-hint">
                      Lecture seule pour le contribuable — jeton affiché une
                      fois.
                    </p>
                  </>
                ) : (
                  <p className="status rest-status-compact">{lienMsg}</p>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <nav className="rest-rail" aria-label="Sections de la restitution">
        {SECTIONS.map((s) => {
          const active = sectionActive === s.id;
          const label =
            s.id === "risques" ? `Risques (${conclusions.length})` : s.label;
          return (
            <Tooltip key={s.id} label={s.tip} side="bottom">
              <button
                type="button"
                className={`rest-rail-btn${active ? " active" : ""}`}
                aria-current={active ? "true" : undefined}
                onClick={() => allerSection(s.id)}
              >
                {label}
              </button>
            </Tooltip>
          );
        })}
      </nav>

      <div className="rest-body">
        {relancesClient.length > 0 && (
          <aside className="rest-banner-relances" role="status">
            <strong>Relances client</strong>
            <ul>
              {relancesClient.map((t) => (
                <li key={t.id}>
                  {t.regle_id ? <code>{t.regle_id}</code> : `Tâche #${t.id}`}
                  {" — "}
                  {t.piece_attendue}
                </li>
              ))}
            </ul>
          </aside>
        )}
        {tachesParObjectif.length > 0 && (
          <section className="rest-section rest-worklist" aria-label="Worklist">
            <header className="rest-section-head dossier2-sec-head">
              <h3>Tâches ouvertes</h3>
              <p>
                Groupées par objectif fiscal — plan dérivé (hors choix LLM).
                Sous-seuil replié hors liste.
              </p>
            </header>
            {tachesParObjectif.map(([impot, list]) => (
              <details key={impot} className="rest-obj-group" open>
                <summary>
                  <strong>{impot}</strong> — {list.length} tâche
                  {list.length > 1 ? "s" : ""}
                </summary>
                <ul className="rest-tache-list">
                  {list.map((t) => (
                    <li key={t.id}>
                      <code>{t.regle_id || "—"}</code>
                      <span className={`badge statut-${t.statut}`}>
                        {t.statut}
                      </span>
                      {t.piece_attendue ? (
                        <span className="muted"> · {t.piece_attendue}</span>
                      ) : null}
                      {!estLecteur && jeton ? (
                        <label className="rest-assignee">
                          <select
                            className="field-input field-input-sm"
                            value={t.assignee_a ?? ""}
                            aria-label={`Assigner la tâche ${t.regle_id || t.id}`}
                            onChange={(e) => {
                              const v = e.target.value;
                              void patchTache(t.id, {
                                assignee_a: v ? Number(v) : null,
                              });
                            }}
                          >
                            <option value="">Non assigné</option>
                            {collaborateurs
                              .filter((u) => u.actif !== false)
                              .map((u) => (
                                <option key={u.id} value={u.id}>
                                  {u.email}
                                </option>
                              ))}
                          </select>
                        </label>
                      ) : t.assignee_a != null ? (
                        <span className="muted">
                          {" "}
                          ·{" "}
                          {collaborateurs.find((u) => u.id === t.assignee_a)
                            ?.email ?? `#${t.assignee_a}`}
                        </span>
                      ) : null}
                      {!estLecteur && jeton && t.statut === "a_faire" ? (
                        <button
                          type="button"
                          className="btn ghost btn-xs"
                          onClick={() =>
                            void patchTache(t.id, { statut: "en_cours" })
                          }
                        >
                          Prendre
                        </button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </section>
        )}
        <section id="rest-synthese" className="rest-section">
          <header className="rest-section-head dossier2-sec-head">
            <h3>Synthèse</h3>
            <p>
              Priorités et pipeline — montants au Passage, suivi dans Risques.
            </p>
          </header>
          {fiabSource && fiabSource.controles.length > 0 && (
            <div
              className="rest-fiab"
              role="note"
              aria-label="Fiabilité de la source"
            >
              <div className="rest-fiab-head">
                <h4 className="rest-fiab-titre">Fiabilité de la source</h4>
                <span className="rest-fiab-meta">
                  Contrôles de vraisemblance FEC
                  {fiabSource.exercice
                    ? ` — exercice ${fiabSource.exercice}`
                    : ""}
                  {fiabSource.cree_le
                    ? ` · ${fmtHorodatage(fiabSource.cree_le)}`
                    : ""}{" "}
                  (informationnel, n'a pas bloqué l'import)
                </span>
              </div>
              <ul className="rest-fiab-liste">
                {fiabSource.controles.map((c) => (
                  <li
                    key={c.code}
                    className={`rest-fiab-item ${c.statut === "alerte" ? "alerte" : "ok"}`}
                  >
                    <span
                      className={`rest-fiab-pastille ${c.statut === "alerte" ? "alerte" : "ok"}`}
                      aria-hidden="true"
                    />
                    <span className="rest-fiab-libelle">{c.libelle}</span>
                    <span className="rest-fiab-compteur">
                      {c.statut === "alerte"
                        ? `${c.compteur} occurrence${c.compteur > 1 ? "s" : ""}`
                        : "OK"}
                    </span>
                    {c.echantillon.length > 0 && (
                      <details className="rest-fiab-echantillon">
                        <summary>
                          Échantillon ({c.echantillon.length}
                          {c.compteur > c.echantillon.length
                            ? ` sur ${c.compteur}`
                            : ""}
                          )
                        </summary>
                        <ul>
                          {c.echantillon.map((occ, idx) => (
                            <li key={`${c.code}-${idx}`}>
                              {occ.ligne != null ? (
                                <code>écriture {occ.ligne}</code>
                              ) : null}{" "}
                              {occ.valeur}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {revueAnalytique && (
            <div
              className="rest-analytique"
              role="note"
              aria-label="Revue analytique N / N-1"
            >
              <div className="rest-analytique-head">
                <h4 className="rest-analytique-titre">
                  Revue analytique {revueAnalytique.exercice_n} /{" "}
                  {revueAnalytique.exercice_n1}
                </h4>
                <span className="rest-analytique-meta">
                  Comparaison des soldes avec l'exercice précédent du même
                  client — chaque variation significative appelle une
                  explication.
                </span>
                {revueAnalytique.disponible && (
                  <Tooltip label="Commentaire IA des variations significatives : hypothèse explicative et question à poser au client pour chaque poste. Versionné, consultatif — l'humain valide.">
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm rest-note-btn"
                      onClick={() => setComAnaOuvert((o) => !o)}
                      disabled={!jeton}
                      aria-expanded={comAnaOuvert}
                    >
                      Commentaire IA
                    </button>
                  </Tooltip>
                )}
              </div>
              {comAnaOuvert && revueAnalytique.disponible && (
                <section
                  className="rest-note rest-comana"
                  aria-label="Commentaire IA de revue analytique"
                >
                  <div className="rest-note-head">
                    <h3 className="rest-note-titre label-with-tip">
                      Commentaire IA de revue analytique
                      <InfoTip
                        label="Lecture commentée générée par IA à partir des SEULES variations significatives calculées ci-dessous : toute explication citant un poste absent des variations est retirée. Document consultatif versionné, à relire avant instruction."
                        ariaLabel="Aide : commentaire IA de revue analytique"
                      />
                    </h3>
                    <div className="rest-note-outils">
                      {comAnaVersions.length > 0 && (
                        <label className="rest-note-version">
                          Version{" "}
                          <select
                            value={comAnaVersionSel ?? ""}
                            onChange={(e) =>
                              setComAnaVersionSel(
                                e.target.value
                                  ? Number(e.target.value)
                                  : null,
                              )
                            }
                          >
                            {comAnaVersions.map((v) => (
                              <option key={v.id} value={v.version}>
                                v{v.version} ·{" "}
                                {v.statut === "disponible"
                                  ? "disponible"
                                  : v.statut === "echec"
                                    ? "échec"
                                    : "en cours"}
                                {v.cree_le
                                  ? ` · ${fmtHorodatage(v.cree_le)}`
                                  : ""}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}
                      <button
                        type="button"
                        className="btn btn-sm rest-note-generer"
                        onClick={() => void genererComAna()}
                        disabled={comAnaBusy || !jeton}
                      >
                        {comAnaBusy ? "Génération…" : "Générer"}
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => setComAnaOuvert(false)}
                      >
                        Fermer
                      </button>
                    </div>
                  </div>
                  {comAnaErr && (
                    <p className="rest-note-erreur" role="alert">
                      {comAnaErr}
                    </p>
                  )}
                  {comAnaVersions.length === 0 &&
                    !comAnaBusy &&
                    !comAnaErr && (
                      <p className="rest-note-vide">
                        Aucun commentaire généré pour cette mission. Cliquez
                        sur « Générer » pour produire la première version
                        (quelques secondes).
                      </p>
                    )}
                  {comAnaDetail?.statut === "echec" && (
                    <p className="rest-note-erreur" role="alert">
                      Génération v{comAnaDetail.version} en échec
                      {comAnaDetail.erreur
                        ? ` : ${comAnaDetail.erreur}`
                        : "."}
                    </p>
                  )}
                  {comAnaDetail?.statut === "disponible" &&
                    comAnaDetail.contenu && (
                      <div className="rest-note-corps">
                        {comAnaDetail.contenu.resume && (
                          <div className="rest-note-bloc">
                            <h4>Lecture d'ensemble</h4>
                            <p>{comAnaDetail.contenu.resume}</p>
                          </div>
                        )}
                        <div className="rest-note-bloc">
                          <h4>Explications par poste</h4>
                          {comAnaDetail.contenu.explications.length === 0 ? (
                            <p className="rest-note-vide">
                              Aucune explication sourcée par une variation
                              dans cette version.
                            </p>
                          ) : (
                            <ul className="rest-note-constats">
                              {comAnaDetail.contenu.explications.map(
                                (ex, i) => (
                                  <li
                                    key={`${ex.poste}-${i}`}
                                    className={`rest-note-constat rest-comana-explication ${ex.gravite}`}
                                  >
                                    <span
                                      className={`rest-note-gravite ${ex.gravite}`}
                                    >
                                      {libelleGraviteNote(ex.gravite)}
                                    </span>
                                    <code className="rest-analytique-compte">
                                      {ex.poste}
                                    </code>
                                    <span className="rest-note-resume">
                                      {ex.hypothese_explicative}
                                    </span>
                                    {ex.question_a_poser_au_client && (
                                      <span className="rest-comana-question">
                                        Question au client :{" "}
                                        {ex.question_a_poser_au_client}
                                      </span>
                                    )}
                                  </li>
                                ),
                              )}
                            </ul>
                          )}
                        </div>
                        {comAnaDetail.contenu.alertes_coherence.length >
                          0 && (
                          <div className="rest-note-bloc">
                            <h4>Alertes de cohérence</h4>
                            <ul className="rest-note-liste">
                              {comAnaDetail.contenu.alertes_coherence.map(
                                (a, i) => (
                                  <li key={i}>{a}</li>
                                ),
                              )}
                            </ul>
                          </div>
                        )}
                        <p className="rest-note-mention">
                          Commentaire généré par IA (v{comAnaDetail.version}
                          {comAnaDetail.auteur
                            ? ` · ${comAnaDetail.auteur}`
                            : ""}
                          ) à partir des seules variations significatives —
                          document consultatif, à relire et instruire avec le
                          client.
                        </p>
                      </div>
                    )}
                </section>
              )}
              {!revueAnalytique.disponible ? (
                <p className="rest-analytique-vide">
                  Aucun exercice antérieur comparable
                </p>
              ) : (
                <>
                  <table className="rest-analytique-table">
                    <thead>
                      <tr>
                        <th>Compte</th>
                        <th>Libellé</th>
                        <th className="num">{revueAnalytique.exercice_n}</th>
                        <th className="num">{revueAnalytique.exercice_n1}</th>
                        <th className="num">Variation FCFA</th>
                        <th className="num">%</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {revueAnalytique.lignes
                        .slice(0, REVUE_ANALYTIQUE_MAX_LIGNES)
                        .map((l) => {
                          const badge = badgeAnalytique(l.classement);
                          return (
                            <tr key={l.compte}>
                              <td>
                                <code className="rest-analytique-compte">
                                  {l.compte}
                                </code>
                              </td>
                              <td className="rest-analytique-libelle">
                                {l.libelle || "—"}
                              </td>
                              <td className="num">{fmtMontant(l.solde_n)}</td>
                              <td className="num">{fmtMontant(l.solde_n1)}</td>
                              <td
                                className={`num rest-analytique-variation ${
                                  l.variation < 0 ? "negatif" : ""
                                }`}
                              >
                                {l.variation > 0 ? "+" : ""}
                                {fmtMontant(l.variation)}
                              </td>
                              <td className="num">
                                {l.variation_pct != null
                                  ? `${l.variation_pct > 0 ? "+" : ""}${l.variation_pct.toLocaleString("fr-FR")} %`
                                  : "—"}
                              </td>
                              <td>
                                {badge ? (
                                  <span
                                    className={`rest-analytique-badge ${badge.classe}`}
                                  >
                                    {badge.label}
                                  </span>
                                ) : null}
                              </td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                  {revueAnalytique.lignes.length >
                    REVUE_ANALYTIQUE_MAX_LIGNES && (
                    <p className="rest-analytique-compteur">
                      {REVUE_ANALYTIQUE_MAX_LIGNES} premières lignes affichées
                      sur {revueAnalytique.lignes.length} comptes comparés.
                    </p>
                  )}
                  {revueAnalytique.totaux_par_classe.length > 0 && (
                    <ul className="rest-analytique-totaux">
                      {revueAnalytique.totaux_par_classe.map((t) => (
                        <li key={t.classe}>
                          <span className="rest-analytique-totaux-classe">
                            Classe {t.classe}
                          </span>
                          <span className="rest-analytique-totaux-montants">
                            {fmtMontant(t.total_n)} vs {fmtMontant(t.total_n1)}{" "}
                            ({t.variation > 0 ? "+" : ""}
                            {fmtMontant(t.variation)})
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>
          )}
          {tachesBloquees.length > 0 && (
            <div className="taches-bloquees-panneau" role="alert">
              <p className="taches-bloquees-titre">
                {tachesBloquees.length} tâche
                {tachesBloquees.length > 1 ? "s" : ""} bloquée
                {tachesBloquees.length > 1 ? "s" : ""} en attente
              </p>
              <ul className="taches-bloquees-liste">
                {tachesBloquees.map((t) => (
                  <li key={t.id} className="taches-bloquees-item">
                    <code>{t.regle_id || `tâche #${t.id}`}</code>
                    {t.impot ? (
                      <span className="taches-bloquees-impot">{t.impot}</span>
                    ) : null}
                    <span className="taches-bloquees-motif">
                      {t.piece_attendue
                        ? `Pièce attendue : ${t.piece_attendue}`
                        : "Motif non renseigné — complétez la pièce attendue."}
                    </span>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => {
                        const el = t.regle_id
                          ? document.getElementById(
                              `rest-regle-${t.regle_id}`,
                            )
                          : null;
                        if (el) {
                          el.scrollIntoView({
                            behavior: scrollPref(),
                            block: "center",
                          });
                        } else {
                          allerSection("risques");
                        }
                      }}
                    >
                      Voir la tâche
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="rest-split">
            <div>
              <ul className="rest-priority">
                {nEleve > 0 && (
                  <li className="eleve">
                    <strong>{nEleve}</strong> conclusion
                    {nEleve > 1 ? "s" : ""} à risque élevé — instruire en
                    premier.
                  </li>
                )}
                {nMoyen > 0 && (
                  <li className="moyen">
                    <strong>{nMoyen}</strong> à risque moyen — documenter les
                    pièces.
                  </li>
                )}
                {nFaible > 0 && (
                  <li className="faible">
                    <strong>{nFaible}</strong> à risque faible — revue
                    proportionnée.
                  </li>
                )}
                {nTotalRisque === 0 && (
                  <li>Aucune conclusion scorée sur cette exécution.</li>
                )}
                {ouverts > 0 && (
                  <li>
                    <strong>{ouverts}</strong> point
                    {ouverts > 1 ? "s" : ""} encore ouvert
                    {ouverts > 1 ? "s" : ""} dans le suivi de traitement.
                  </li>
                )}
                {(r.a_confirmer_total ?? 0) > 0 && (
                  <li>
                    Mentions <code>a_confirmer</code> présentes — vérifier la
                    file éditoriale avant d’opposer un paramètre.
                  </li>
                )}
              </ul>
            </div>
            <div>
              <div className="rest-pipeline">
                {STATUTS_TRAITEMENT.map((s) => (
                  <Tooltip key={s.value} label={s.hint} side="bottom">
                    <button
                      type="button"
                      className="rest-pipe-chip"
                      onClick={() => {
                        setFiltreTraitement(s.value);
                        allerSection("risques");
                      }}
                    >
                      <span>{s.label}</span>
                      <strong>{synthTrait[s.value]}</strong>
                    </button>
                  </Tooltip>
                ))}
              </div>
            </div>
          </div>

          {topRisques.length > 0 && (
            <div className="rest-jump">
              <span className="rest-jump-label">Accès rapide</span>
              <ul className="rest-jump-list">
                {topRisques.map((c) => (
                  <li key={c.regle_id}>
                    <button
                      type="button"
                      className="rest-jump-btn"
                      onClick={() => {
                        setFiltreRisque("tous");
                        setFiltreTraitement("tous");
                        allerSection("risques");
                      }}
                    >
                      <code>{c.regle_id}</code>
                      <span
                        className={`badge-risque ${(c.niveau_risque || "").toLowerCase()}`}
                      >
                        {libelleRisque(c.niveau_risque)}
                      </span>
                      <span className="rest-jump-amt">
                        {c.montant != null ? fmtMontant(c.montant) : "—"}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        <section id="rest-passage" className="rest-section">
          <header className="rest-section-head dossier2-sec-head">
            <h3 className="label-with-tip">
              Passage
              <InfoTip
                label={PROCESS_TIPS.passage}
                ariaLabel="Aide : tableau de passage"
              />
            </h3>
            <p>
              Agrégation déterministe — source unique des montants moteur.
            </p>
          </header>
          <div className="rest-passage-toolbar">
            <p className="rest-passage-resume">
              <strong>{lignesPassage.length}</strong> ligne
              {lignesPassage.length > 1 ? "s" : ""}
              <span>
                {" "}
                · {nbReintPassage} réint. · {nbDedPassage} déd.
              </span>
              {filtreSensPassage !== "tous" && (
                <span>
                  {" "}
                  · affichage {lignesPassageFiltrees.length}/
                  {lignesPassage.length}
                </span>
              )}
            </p>
            <div className="rest-filters rest-passage-filters">
              <label>
                Sens
                <select
                  value={filtreSensPassage}
                  onChange={(e) => setFiltreSensPassage(e.target.value)}
                >
                  <option value="tous">Tous</option>
                  <option value="reintegration">Réintégration</option>
                  <option value="deduction">Déduction</option>
                </select>
              </label>
            </div>
          </div>
          <div className="balance-table-wrap">
            <table className="balance-table rest-passage-table">
              <thead>
                <tr>
                  <th>Règle</th>
                  <th>
                    <span className="label-with-tip">
                      Sens
                      <InfoTip
                        label="Réintégration : ajoute au résultat fiscal. Déduction : retranche. Sens issu de la règle épinglée — pas d’interprétation libre à l’écran."
                        ariaLabel="Aide : sens du passage"
                      />
                    </span>
                  </th>
                  <th>Risque</th>
                  <th>Montant</th>
                </tr>
              </thead>
              <tbody>
                {lignesPassageFiltrees.map((l, i) => (
                  <tr key={`${String(l.regle_id)}-${i}`}>
                    <td>
                      <code>{String(l.regle_id)}</code>
                    </td>
                    <td>{libelleSens(String(l.sens ?? ""))}</td>
                    <td>
                      <span
                        className={`badge-risque ${String(l.niveau_risque || "").toLowerCase()}`}
                      >
                        {libelleRisque(String(l.niveau_risque ?? ""))}
                      </span>
                    </td>
                    <td className="num">
                      {l.montant != null
                        ? fmtMontant(l.montant as string | number)
                        : "—"}
                    </td>
                  </tr>
                ))}
                {!lignesPassageFiltrees.length && (
                  <tr>
                    <td colSpan={4} className="empty-state">
                      Aucune ligne de passage
                      {filtreSensPassage !== "tous" ? " pour ce filtre" : ""}.
                    </td>
                  </tr>
                )}
              </tbody>
              <tfoot>
                <tr className="rest-passage-solde">
                  <td colSpan={3}>Solde net</td>
                  <td className="num">{fmtMontant(r.passage.solde_net)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </section>

        <section id="rest-risques" className="rest-section">
          <header className="rest-section-head dossier2-sec-head">
            <h3>Risques &amp; traitement</h3>
            <p>
              Workspace réviseur — suivi via statut tâche (serveur), hors calcul
              fiscal.
            </p>
          </header>
          <div className="rest-filters">
            <label>
              Niveau
              <select
                value={filtreRisque}
                onChange={(e) => setFiltreRisque(e.target.value)}
              >
                <option value="tous">Tous</option>
                <option value="eleve">Élevé</option>
                <option value="moyen">Moyen</option>
                <option value="faible">Faible</option>
              </select>
            </label>
            <label>
              Traitement
              <select
                value={filtreTraitement}
                onChange={(e) => setFiltreTraitement(e.target.value)}
              >
                <option value="tous">Tous</option>
                {STATUTS_TRAITEMENT.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
            <span className="rest-filters-meta">
              {conclusionsFiltrees.length} / {conclusions.length}
            </span>
          </div>

          <ul className="rest-risque-list">
            {conclusionsFiltrees.map((c) => {
              const tr =
                traitements[c.regle_id] ??
                ({
                  regle_id: c.regle_id,
                  statut: "a_faire" as const,
                  note: "",
                  maj_le: "",
                } satisfies TraitementRisque);
              const noteVal = noteDraft[c.regle_id] ?? tr.note;
              return (
                <li
                  key={c.regle_id}
                  id={`rest-regle-${c.regle_id}`}
                  className={`rest-risque-card risque-${(c.niveau_risque || "").toLowerCase()}`}
                >
                  <div className="rest-risque-top">
                    <div className="rest-risque-tags">
                      <code>{c.regle_id}</code>
                      <span
                        className={`badge-risque ${(c.niveau_risque || "").toLowerCase()}`}
                      >
                        {libelleRisque(c.niveau_risque)}
                      </span>
                      {c.statut && (
                        <span className="badge-traitement">
                          {STATUTS_CONCLUSION.find((s) => s.value === c.statut)
                            ?.label ?? c.statut}
                        </span>
                      )}
                      <span
                        className={classeBadgeTraitement(tr.statut, tr.note)}
                      >
                        {libelleTraitement(tr.statut, tr.note)}
                      </span>
                      <span className="rest-sens">{libelleSens(c.sens)}</span>
                    </div>
                    <strong className="rest-montant">
                      {c.montant != null ? fmtMontant(c.montant) : "—"}
                    </strong>
                  </div>
                  {c.commentaire && (
                    <p className="rest-comment">{c.commentaire}</p>
                  )}
                  {!!c.comptes_source?.length && (
                    <details className="rest-comptes-source">
                      <summary className="rest-comptes-titre">
                        Comptes à l’origine ({c.comptes_source.length})
                      </summary>
                      <ul className="rest-comptes-liste">
                        {c.comptes_source.map((cs) => (
                          <li key={cs.compte} className="rest-comptes-item">
                            <code className="rest-comptes-numero">
                              {cs.compte}
                            </code>
                            <span className="rest-comptes-libelle">
                              {cs.libelle || "—"}
                            </span>
                            <span className="rest-comptes-solde">
                              {cs.solde != null
                                ? `${fmtMontant(cs.solde)} FCFA`
                                : "—"}
                              {cs.sens ? (
                                <em className="rest-comptes-sens">
                                  {" "}
                                  ({cs.sens})
                                </em>
                              ) : null}
                            </span>
                          </li>
                        ))}
                      </ul>
                      <p className="rest-comptes-note">
                        Soldes figés au moment de l’exécution de la revue —
                        piste d’audit du montant conclu.
                      </p>
                    </details>
                  )}
                  {c.id != null && (
                    <div className="rest-conclusion-valide">
                      <label className="rest-statut">
                        Statut conclusion
                        <select
                          value={c.statut || "anomalie"}
                          disabled={estLecteur || patchBusyId === c.id}
                          onChange={(e) =>
                            void patchConclusion(c.id!, {
                              statut: e.target.value,
                            })
                          }
                        >
                          {STATUTS_CONCLUSION.map((s) => (
                            <option key={s.value} value={s.value}>
                              {s.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="rest-statut">
                        Pièce dossier
                        <select
                          value={c.piece_mission_id ?? ""}
                          disabled={estLecteur || patchBusyId === c.id}
                          onChange={(e) => {
                            const v = e.target.value;
                            void patchConclusion(c.id!, {
                              piece_mission_id: v ? Number(v) : null,
                            });
                          }}
                        >
                          <option value="">— aucune —</option>
                          {pieces.map((p) => (
                            <option key={p.id} value={p.id}>
                              #{p.id} · {p.nom_fichier} ({p.role})
                            </option>
                          ))}
                        </select>
                      </label>
                      {c.amendee_par && (
                        <span className="rest-maj">
                          Évalué par {c.amendee_par}
                        </span>
                      )}
                      {c.statut === "anomalie" &&
                        (c.valide_par ? (
                          <span className="rest-maj">
                            Validée par {c.valide_par}
                            {c.valide_le
                              ? ` le ${fmtHorodatage(c.valide_le)}`
                              : ""}
                          </span>
                        ) : (
                          !estLecteur &&
                          c.id != null && (
                            <Tooltip label="Second regard (« 4 yeux ») — requis sur chaque anomalie avant clôture du dossier.">
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                disabled={
                                  validerBusyId === c.id || !c.amendee_par
                                }
                                onClick={() => void validerConclusion(c.id!)}
                              >
                                Valider
                              </button>
                            </Tooltip>
                          )
                        ))}
                      {!estLecteur && conclusionSensible(c) && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          disabled={pointBusyId === c.id}
                          onClick={() =>
                            void creerRisqueDepuisConclusion(c.id!, c)
                          }
                        >
                          Créer risque registre
                        </button>
                      )}
                    </div>
                  )}
                  {pointMsg && pointMsg.conclusionId === c.id && (
                    <p className="rest-comment" role="status">
                      {pointMsg.texte}
                    </p>
                  )}
                  {patchErr && c.id === actionErrId && (
                    <p className="rest-comment" role="alert">
                      {patchErr}
                    </p>
                  )}
                  <div className="rest-traitement">
                    <label className="rest-statut">
                      Instruction (tâche)
                      <select
                        value={tr.statut}
                        disabled={estLecteur || !tr.tache_id}
                        onChange={(e) =>
                          void majTraitement(c.regle_id, {
                            statut: e.target.value as StatutTache,
                            note: noteVal,
                          })
                        }
                      >
                        {STATUTS_TRAITEMENT.map((s) => (
                          <option key={s.value} value={s.value}>
                            {s.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="rest-note">
                      Pièce / note attendue
                      <textarea
                        rows={1}
                        disabled={estLecteur || !tr.tache_id}
                        value={noteVal}
                        placeholder="Pièces, hypothèses, décision…"
                        onChange={(e) =>
                          setNoteDraft((d) => ({
                            ...d,
                            [c.regle_id]: e.target.value,
                          }))
                        }
                        onBlur={() =>
                          void majTraitement(c.regle_id, {
                            statut: tr.statut,
                            note: noteVal,
                          })
                        }
                      />
                    </label>
                    {!tr.tache_id && (
                      <span className="rest-maj">
                        Pas de tâche liée — exécutez la revue pour activer le
                        suivi serveur.
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
            {!conclusionsFiltrees.length && (
              <li className="empty-state">Aucun risque sur ce filtre.</li>
            )}
          </ul>
        </section>

        <section id="rest-rapport" className="rest-section">
          <header className="rest-section-head dossier2-sec-head">
            <h3 className="label-with-tip">
              Rapport
              <InfoTip
                label={PROCESS_TIPS.rapport}
                ariaLabel="Aide : rapport artefact"
              />
            </h3>
            <p>Artefact livrable — rendu typographique du markdown moteur.</p>
          </header>
          <RapportArtifact markdown={r.rapport_markdown || ""} />
        </section>

        <section id="rest-audit" className="rest-section">
          <header className="rest-section-head dossier2-sec-head">
            <h3 className="label-with-tip">
              Audit
              <InfoTip
                label={PROCESS_TIPS.audit}
                ariaLabel="Aide : journal d’audit"
              />
            </h3>
            <p>Journal en écriture seule — traçabilité intégrale.</p>
          </header>
          {auditJournal ? (
            <div className="rest-audit">
              {auditJournal.synthese && (
                <div className="rest-audit-synthese" role="status">
                  <div className="rest-audit-kpis">
                    <div>
                      <span className="rest-verdict-k">Entrées</span>
                      <strong>{auditJournal.synthese.total}</strong>
                    </div>
                    {Object.entries(auditJournal.synthese.par_action || {}).map(
                      ([act, n]) => (
                        <button
                          key={act}
                          type="button"
                          className={`rest-audit-chip${
                            filtreAuditAction === act ? " active" : ""
                          }`}
                          onClick={() =>
                            setFiltreAuditAction((prev) =>
                              prev === act ? "tous" : act,
                            )
                          }
                        >
                          <span>{libelleActionAudit(act)}</span>
                          <strong>{n}</strong>
                        </button>
                      ),
                    )}
                  </div>
                  <p className="rest-audit-note">
                    {auditJournal.synthese.note}
                    {auditJournal.synthese.ecriture_seule
                      ? " UPDATE/DELETE refusés en base."
                      : ""}
                  </p>
                </div>
              )}
              {auditActionsDispo.length > 1 && (
                <div className="rest-audit-filtre">
                  <label htmlFor="filtre-audit-action">Filtrer</label>
                  <select
                    id="filtre-audit-action"
                    value={filtreAuditAction}
                    onChange={(e) => setFiltreAuditAction(e.target.value)}
                  >
                    <option value="tous">Toutes les actions</option>
                    {auditActionsDispo.map((a) => (
                      <option key={a} value={a}>
                        {libelleActionAudit(a)}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={busy}
                    onClick={onAudit}
                  >
                    Actualiser
                  </button>
                </div>
              )}
              {auditFiltre.length === 0 ? (
                <p className="empty-state">
                  Aucune entrée pour ce filtre.
                </p>
              ) : (
                <ol className="rest-audit-timeline">
                  {auditFiltre.map((e, idx) => (
                    <li
                      key={e.id ?? `${e.horodatage}-${e.action}-${idx}`}
                      className="rest-audit-item"
                    >
                      <div className="rest-audit-item-head">
                        <span className="rest-audit-action">
                          {libelleActionAudit(e.action)}
                        </span>
                        <time dateTime={e.horodatage || undefined}>
                          {fmtHorodatage(e.horodatage)}
                        </time>
                      </div>
                      <p className="rest-audit-resume">{resumeCharge(e)}</p>
                      <div className="rest-audit-meta">
                        <span>Acteur · {e.acteur || "—"}</span>
                        {e.hash_court && (
                          <Tooltip label={e.hash || "Empreinte chaînée"}>
                            <code className="rest-audit-hash">
                              #{e.hash_court}
                            </code>
                          </Tooltip>
                        )}
                      </div>
                      {e.charge_utile &&
                        Object.keys(e.charge_utile).length > 0 && (
                          <details className="rest-audit-charge">
                            <summary>Charge utile</summary>
                            <pre>
                              {JSON.stringify(e.charge_utile, null, 2)}
                            </pre>
                          </details>
                        )}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          ) : (
            <div className="empty-state">
              <p>Chargez le journal d’audit de la mission.</p>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={busy}
                onClick={onAudit}
              >
                Charger l’audit
              </button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
