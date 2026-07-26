import { useEffect, useMemo, useRef, useState } from "react";
import { api, fmtMontant, telecharger } from "./api";
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
};

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
  const [noteOuverte, setNoteOuverte] = useState(false);
  const [noteVersions, setNoteVersions] = useState<NoteSyntheseVersion[]>([]);
  const [noteVersionSel, setNoteVersionSel] = useState<number | null>(null);
  const [noteDetail, setNoteDetail] = useState<NoteSyntheseDetail | null>(
    null,
  );
  const [noteBusy, setNoteBusy] = useState(false);
  const [noteErr, setNoteErr] = useState<string | null>(null);
  const notePollRef = useRef(false);

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
      <div className="rest-toolbar" role="toolbar" aria-label="Actions restitution">
        <div className="rest-toolbar-brand">
          <span className="rest-toolbar-mark" aria-hidden="true" />
          <span className="label-with-tip">
            Artefact · Restitution
            <InfoTip
              label={PROCESS_TIPS.artefact}
              ariaLabel="Aide : artefact restitution"
            />
          </span>
        </div>
        <div className="rest-toolbar-actions">
          <Tooltip label={PROCESS_TIPS.exportWord}>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => onExport("docx")}
              disabled={sansExecution}
            >
              Word
            </button>
          </Tooltip>
          <Tooltip label={PROCESS_TIPS.exportPdf}>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => onExport("pdf")}
              disabled={sansExecution}
            >
              PDF
            </button>
          </Tooltip>
          <Tooltip label="Lettre de mission (.docx) générée depuis le cadrage — à personnaliser et faire signer avant les travaux. Champs manquants : [à compléter].">
            <button
              type="button"
              className="btn btn-ghost btn-sm rest-lettre-btn"
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
          <Tooltip label="Note de synthèse de mission (executive summary IA) pour l'associé signataire — versionnée, chaque constat cite sa règle. Consultative : l'humain valide.">
            <button
              type="button"
              className="btn btn-ghost btn-sm rest-note-btn"
              onClick={() => setNoteOuverte((o) => !o)}
              disabled={!jeton}
              aria-expanded={noteOuverte}
            >
              Note de synthèse
            </button>
          </Tooltip>
          <Tooltip label={PROCESS_TIPS.audit}>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={busy}
              onClick={() => {
                onAudit();
                allerSection("audit");
              }}
            >
              Audit
            </button>
          </Tooltip>
          {!estLecteur && onLienClient && (
            <Tooltip label={PROCESS_TIPS.lienClient}>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={onLienClient}
                disabled={busy}
              >
                Lien client
              </button>
            </Tooltip>
          )}
          {!estLecteur && !estCloturee && onCloturer && !sansExecution && (
            <Tooltip label="Clôture le dossier (statut serveur). Réouverture possible — l’épinglage référentiel est conservé.">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={busy}
                onClick={onCloturer}
              >
                Clôturer
              </button>
            </Tooltip>
          )}
          {!estLecteur && estCloturee && onReouvrir && (
            <Tooltip label="Repasse la mission en cours pour permettre une nouvelle exécution sur la même version épinglée.">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={busy}
                onClick={onReouvrir}
              >
                Réouvrir
              </button>
            </Tooltip>
          )}
        </div>
      </div>

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
            <header className="rest-section-head">
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
          <header className="rest-section-head">
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
              </div>
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
          <header className="rest-section-head">
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
          <header className="rest-section-head">
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
          <header className="rest-section-head">
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
          <header className="rest-section-head">
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
