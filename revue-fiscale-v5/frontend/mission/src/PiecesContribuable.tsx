/** Pièces d'identité contribuable — upload, extraction brouillon, conformité. */
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { api, apiBlob, apiUpload } from "./api";
import type { FormePersonne } from "./legalite";
import { mapperFormeJuridique, mapperRegimeFiscal } from "./legalite";

/** Sous-ensemble du formulaire client (évite import circulaire ClientsVue). */
export type IdentiteEditPourPieces = {
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

export type TypePieceContribuable =
  | "dfe"
  | "rccm"
  | "bail"
  | "cie"
  | "sodeci"
  | "autre";

export const TYPES_PIECE_CONTRIBUABLE: {
  id: TypePieceContribuable;
  label: string;
}[] = [
  { id: "dfe", label: "DFE" },
  { id: "rccm", label: "RCCM" },
  { id: "bail", label: "Bail" },
  { id: "cie", label: "Facture CIE" },
  { id: "sodeci", label: "Facture SODECI" },
  { id: "autre", label: "Autre" },
];

export type PieceContribuable = {
  id: number;
  contribuable_id?: number | null;
  session_upload?: string | null;
  type_piece: TypePieceContribuable | string;
  nom_fichier: string;
  taille_octets?: number | null;
  content_type?: string | null;
  cree_le?: string | null;
  type_detecte?: string | null;
  type_source?: string | null;
  type_confiance?: number | null;
  type_detecte_auto?: boolean;
  type_motif?: string | null;
};

export type CitationChamp = {
  champ: string;
  piece_id: number;
  extrait: string;
  confiance?: number | null;
};

export type PropositionIdentite = {
  disponible: boolean;
  statut: string;
  proposition_id?: number;
  champs: Record<string, string | number | null>;
  champs_manquants?: string[];
  citations: CitationChamp[];
  message?: string | null;
  piece_ids: number[];
  provider?: string | null;
  failover_depuis?: string[];
  avertissements?: string[];
};

export type EcartConformite = {
  champ?: string | null;
  saisi?: string | null;
  lu_dans_piece?: string | null;
  piece_id?: number | null;
  severity: "ecart" | "info";
  message: string;
};

export type RapportConformite = {
  disponible: boolean;
  statut: string;
  ok: boolean | null;
  ecarts: EcartConformite[];
  message?: string | null;
  piece_ids: number[];
  provider?: string | null;
  failover_depuis?: string[];
  avertissements?: string[];
};

export type PropositionHistorique = {
  proposition_id: number;
  statut: string;
  message?: string | null;
  cree_le?: string | null;
  champs?: Record<string, unknown>;
  piece_ids?: number[];
};

type KindApercu = "pdf" | "image" | "autre";

type ApercuPiece = {
  pieceId: number;
  nom: string;
  kind: KindApercu;
  url: string;
};

function kindApercu(
  nom: string,
  contentType: string | null | undefined,
): KindApercu {
  const ct = (contentType || "").toLowerCase().split(";")[0].trim();
  if (ct === "application/pdf" || /\.pdf$/i.test(nom)) return "pdf";
  if (ct.startsWith("image/") || /\.(png|jpe?g|gif|webp|bmp|tiff?)$/i.test(nom)) {
    return "image";
  }
  return "autre";
}

const LIBELLES_CHAMP: Record<string, string> = {
  denomination: "Dénomination",
  ncc: "NCC",
  rccm: "RCCM",
  forme: "Forme (PM/PP)",
  dfe: "DFE",
  regime_fiscal: "Régime fiscal",
  forme_juridique: "Forme juridique",
  siege_social: "Siège social",
  commune: "Commune",
  centre_impots: "Centre des impôts",
  capital_social: "Capital social",
  mois_cloture: "Mois de clôture",
  activite_principale: "Activité",
  date_immatriculation: "Date d'immatriculation",
};

/** Trace ops uniquement — ne pas afficher au métier. */
function logProviderOps(
  contexte: string,
  provider: string | null | undefined,
  failover: string[] | null | undefined,
): void {
  if (!provider) return;
  console.debug(`[pieces-ia] ${contexte}`, {
    provider,
    failover_depuis: failover ?? [],
  });
}

/** Filet UI : jamais afficher noms de fournisseurs / variables d'env au métier. */
function messageMetierSansProvider(msg: string | null | undefined): string {
  if (!msg) return "";
  return msg
    .replace(/\s*\(?\s*via\s+(?:Moonshot|DeepSeek|Kimi|legacy|OpenAI)[^)]*\)?/gi, "")
    .replace(/\b(?:Moonshot|DeepSeek|Kimi|OpenAI)\b(?:\s*\([^)]*\))?/gi, "")
    .replace(/\b(?:MOONSHOT|DEEPSEEK|MODELE)_[A-Z0-9_]+\b/g, "")
    .replace(/\b(?:api\.moonshot\.(?:ai|cn)|platform\.kimi\.ai)\b/gi, "")
    .replace(/\bconsole\s*\/?\s*Kimi\b/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

export function nouvelleSessionUpload(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `sess-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function appliquerPropositionAuEdit<T extends IdentiteEditPourPieces>(
  edit: T,
  champs: Record<string, string | number | null>,
): T {
  const next = { ...edit };
  const str = (v: string | number | null | undefined) =>
    v === null || v === undefined ? "" : String(v);

  if (champs.denomination) next.denomination = str(champs.denomination);
  if (champs.ncc) next.ncc = str(champs.ncc);
  if (champs.rccm) next.rccm = str(champs.rccm);
  if (champs.forme === "pm" || champs.forme === "pp") {
    next.forme = champs.forme;
    if (champs.forme === "pp" && !champs.forme_juridique) {
      next.forme_juridique = "EI";
    }
  }
  if (champs.dfe) next.dfe = str(champs.dfe);
  const regime = mapperRegimeFiscal(str(champs.regime_fiscal));
  if (regime) next.regime_fiscal = regime;
  const fj = mapperFormeJuridique(str(champs.forme_juridique));
  if (fj) next.forme_juridique = fj;
  if (champs.siege_social) next.siege_social = str(champs.siege_social);
  if (champs.commune) next.commune = str(champs.commune);
  if (champs.centre_impots) next.centre_impots = str(champs.centre_impots);
  if (champs.capital_social != null && champs.capital_social !== "") {
    next.capital_social = str(champs.capital_social);
  }
  if (champs.mois_cloture != null && champs.mois_cloture !== "") {
    next.mois_cloture = str(champs.mois_cloture);
  }
  if (champs.activite_principale) {
    next.activite_principale = str(champs.activite_principale);
  }
  if (champs.date_immatriculation) {
    next.date_immatriculation = str(champs.date_immatriculation).slice(0, 10);
  }
  return next;
}

type Props = {
  jeton: string;
  /** Session d'upload (création) OU contribuable déjà créé. */
  sessionUpload?: string;
  contribuableId?: number;
  disabled?: boolean;
  edit: IdentiteEditPourPieces;
  setEdit: (
    updater: (prev: IdentiteEditPourPieces) => IdentiteEditPourPieces,
  ) => void;
  /** Affiche le bouton conformité (fiche existante). */
  modeConformite?: boolean;
};

export function PiecesContribuablePanel({
  jeton,
  sessionUpload,
  contribuableId,
  disabled,
  edit,
  setEdit,
  modeConformite = false,
}: Props) {
  const inputId = useId();
  const [pieces, setPieces] = useState<PieceContribuable[]>([]);
  const [busyMode, setBusyMode] = useState<
    null | "upload" | "extract" | "conformite" | "abandon"
  >(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [avertissements, setAvertissements] = useState<string[]>([]);
  const [proposition, setProposition] = useState<PropositionIdentite | null>(
    null,
  );
  const [conformite, setConformite] = useState<RapportConformite | null>(null);
  const [historique, setHistorique] = useState<PropositionHistorique[]>([]);
  const [champsAppliques, setChampsAppliques] = useState<Set<string>>(
    () => new Set(),
  );
  const [ttlHint, setTtlHint] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [apercu, setApercu] = useState<ApercuPiece | null>(null);
  const [apercuBusyId, setApercuBusyId] = useState<number | null>(null);
  const apercuUrlRef = useRef<string | null>(null);

  const busy = busyMode !== null;

  const libererApercuUrl = useCallback(() => {
    if (apercuUrlRef.current) {
      URL.revokeObjectURL(apercuUrlRef.current);
      apercuUrlRef.current = null;
    }
  }, []);

  const fermerApercu = useCallback(() => {
    libererApercuUrl();
    setApercu(null);
  }, [libererApercuUrl]);

  useEffect(() => () => libererApercuUrl(), [libererApercuUrl]);

  useEffect(() => {
    if (!apercu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") fermerApercu();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [apercu, fermerApercu]);

  const ouvrirApercu = useCallback(
    async (p: PieceContribuable) => {
      if (!p.id) return;
      setApercuBusyId(p.id);
      setErr(null);
      try {
        const { blob, contentType } = await apiBlob(
          `/api/v1/pieces-contribuable/${p.id}/contenu`,
          jeton,
        );
        const kind = kindApercu(p.nom_fichier, contentType || p.content_type);
        const url = URL.createObjectURL(blob);
        libererApercuUrl();
        apercuUrlRef.current = url;
        setApercu({ pieceId: p.id, nom: p.nom_fichier, kind, url });
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setApercuBusyId(null);
      }
    },
    [jeton, libererApercuUrl],
  );

  const charger = useCallback(async () => {
    if (!contribuableId && !sessionUpload) return;
    const q = contribuableId
      ? `contribuable_id=${contribuableId}`
      : `session_upload=${encodeURIComponent(sessionUpload!)}`;
    const liste = await api<PieceContribuable[]>(
      `/api/v1/pieces-contribuable?${q}`,
      { jeton },
    );
    setPieces(liste);
  }, [contribuableId, sessionUpload, jeton]);

  const chargerHistorique = useCallback(async () => {
    if (!contribuableId && !sessionUpload) return;
    const q = contribuableId
      ? `contribuable_id=${contribuableId}`
      : `session_upload=${encodeURIComponent(sessionUpload!)}`;
    try {
      const res = await api<{
        items: PropositionHistorique[];
        ttl_session_heures?: number;
      }>(`/api/v1/pieces-contribuable/propositions?${q}&limite=8`, { jeton });
      setHistorique(res.items || []);
      if (typeof res.ttl_session_heures === "number") {
        setTtlHint(res.ttl_session_heures);
      }
    } catch {
      /* historique non bloquant */
    }
  }, [contribuableId, sessionUpload, jeton]);

  useEffect(() => {
    void charger().catch((e) =>
      setErr(e instanceof Error ? e.message : String(e)),
    );
    void chargerHistorique();
  }, [charger, chargerHistorique]);

  async function uploader(files: FileList | File[] | null) {
    if (!files || disabled) return;
    const liste = Array.from(files);
    if (!liste.length) return;
    setBusyMode("upload");
    setErr(null);
    setMsg(null);
    setDragOver(false);
    try {
      for (const file of liste) {
        const champs: Record<string, string> = { type_piece: "auto" };
        if (contribuableId) champs.contribuable_id = String(contribuableId);
        if (sessionUpload) champs.session_upload = sessionUpload;
        await apiUpload<PieceContribuable>(
          "/api/v1/pieces-contribuable",
          file,
          jeton,
          champs,
        );
      }
      await charger();
      setMsg(
        liste.length === 1
          ? "1 pièce ajoutée."
          : `${liste.length} pièces ajoutées.`,
      );
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyMode(null);
    }
  }

  async function retirer(id: number) {
    if (disabled) return;
    setBusyMode("upload");
    setErr(null);
    try {
      await api(`/api/v1/pieces-contribuable/${id}`, {
        method: "DELETE",
        jeton,
      });
      await charger();
      setProposition(null);
      setChampsAppliques(new Set());
      setAvertissements([]);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyMode(null);
    }
  }

  async function abandonnerSession() {
    if (!sessionUpload || contribuableId || disabled) return;
    if (
      !window.confirm(
        "Abandonner cette session ? Les pièces non enregistrées seront supprimées.",
      )
    ) {
      return;
    }
    setBusyMode("abandon");
    setErr(null);
    try {
      await api("/api/v1/pieces-contribuable/abandonner-session", {
        method: "POST",
        jeton,
        json: { session_upload: sessionUpload },
      });
      setPieces([]);
      setProposition(null);
      setConformite(null);
      setHistorique([]);
      setChampsAppliques(new Set());
      setAvertissements([]);
      setMsg("Session abandonnée.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyMode(null);
    }
  }

  async function extraire() {
    if (!pieces.length || disabled) return;
    setBusyMode("extract");
    setErr(null);
    setMsg(null);
    setConformite(null);
    setAvertissements([]);
    try {
      const corps: Record<string, unknown> = {
        piece_ids: pieces.map((p) => p.id),
      };
      if (contribuableId) corps.contribuable_id = contribuableId;
      if (sessionUpload) corps.session_upload = sessionUpload;
      const prop = await api<PropositionIdentite>(
        "/api/v1/pieces-contribuable/proposer-identite",
        { method: "POST", jeton, json: corps },
      );
      setProposition(prop);
      setChampsAppliques(new Set());
      setAvertissements(prop.avertissements || []);
      logProviderOps("proposer-identite", prop.provider, prop.failover_depuis);
      if (prop.disponible) {
        setMsg(
          messageMetierSansProvider(prop.message) || "Brouillon prêt.",
        );
      } else {
        setErr(
          messageMetierSansProvider(
            prop.message || "Extraction indisponible.",
          ) || "Extraction indisponible.",
        );
        setMsg(null);
      }
      void chargerHistorique();
    } catch (e) {
      setErr(
        messageMetierSansProvider(
          e instanceof Error ? e.message : String(e),
        ) || "Extraction impossible.",
      );
    } finally {
      setBusyMode(null);
    }
  }

  async function appliquerBrouillon() {
    if (!proposition?.disponible || !proposition.champs) return;
    setEdit((prev) => appliquerPropositionAuEdit(prev, proposition.champs));
    const appliques = new Set(
      Object.entries(proposition.champs)
        .filter(([, v]) => v != null && v !== "")
        .map(([k]) => k),
    );
    setChampsAppliques(appliques);
    if (proposition.proposition_id) {
      try {
        await api("/api/v1/pieces-contribuable/marquer-applique", {
          method: "POST",
          jeton,
          json: { proposition_id: proposition.proposition_id },
        });
      } catch {
        /* trace non bloquante */
      }
    }
    setMsg("Enregistrement effectué avec succès.");
  }

  async function verifier() {
    if (!pieces.length) return;
    setBusyMode("conformite");
    setErr(null);
    setMsg(null);
    try {
      const champs: Record<string, string | number | null> = {
        denomination: edit.denomination || null,
        ncc: edit.ncc || null,
        rccm: edit.rccm || null,
        forme: edit.forme || null,
        dfe: edit.dfe || null,
        regime_fiscal: edit.regime_fiscal || null,
        forme_juridique: edit.forme_juridique || null,
        siege_social: edit.siege_social || null,
        commune: edit.commune || null,
        centre_impots: edit.centre_impots || null,
        capital_social: edit.capital_social
          ? Number(edit.capital_social.replace(/\s/g, "").replace(",", "."))
          : null,
        mois_cloture: edit.mois_cloture ? Number(edit.mois_cloture) : null,
        activite_principale: edit.activite_principale || null,
        date_immatriculation: edit.date_immatriculation || null,
      };
      const corps: Record<string, unknown> = {
        champs,
        piece_ids: pieces.map((p) => p.id),
      };
      if (contribuableId) corps.contribuable_id = contribuableId;
      if (sessionUpload) corps.session_upload = sessionUpload;
      const rapport = await api<RapportConformite>(
        "/api/v1/pieces-contribuable/verifier-conformite",
        { method: "POST", jeton, json: corps },
      );
      setConformite(rapport);
      setAvertissements(rapport.avertissements || []);
      logProviderOps(
        "verifier-conformite",
        rapport.provider,
        rapport.failover_depuis,
      );
      if (rapport.disponible) {
        setMsg(rapport.message || "Contrôle terminé.");
      } else {
        setErr(rapport.message || "Contrôle indisponible.");
        setMsg(null);
      }
      void chargerHistorique();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyMode(null);
    }
  }

  const citationParChamp = (champ: string) =>
    proposition?.citations?.find((c) => c.champ === champ);

  const champsLus = proposition?.disponible
    ? Object.entries(proposition.champs).filter(
        ([, v]) => v != null && v !== "",
      )
    : [];
  const champsNonLus = proposition?.champs_manquants ?? [];

  return (
    <div
      className="panel dense clients-pieces-panel"
      aria-busy={busyMode === "extract" || undefined}
    >
      <div className="clients-fiche-section-head clients-pieces-head">
        <p className="picker-kicker">Pièces</p>
      </div>

      {!disabled && (
        <div
          className={`field-upload balance-drop annexes-drop clients-pieces-drop${
            dragOver ? " drag" : ""
          }`}
          onDragEnter={(e) => {
            e.preventDefault();
            if (!busy) setDragOver(true);
          }}
          onDragOver={(e) => {
            e.preventDefault();
            if (!busy) setDragOver(true);
          }}
          onDragLeave={(e) => {
            e.preventDefault();
            if (e.currentTarget === e.target) setDragOver(false);
          }}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            void uploader(e.dataTransfer.files);
          }}
        >
          <input
            id={inputId}
            type="file"
            multiple
            accept=".pdf,.png,.jpg,.jpeg,.txt,.md,application/pdf,image/*"
            disabled={busy}
            onChange={(e) => {
              void uploader(e.target.files);
              e.target.value = "";
            }}
          />
          <label htmlFor={inputId} className="field-upload-label">
            <span className="field-upload-title">
              {busyMode === "upload" ? "Ajout…" : "Ajouter des fichiers"}
            </span>
            <span className="field-upload-meta">PDF ou image</span>
          </label>
        </div>
      )}

      {pieces.length > 0 && (
        <ul className="annexes-list clients-pieces-list">
          {pieces.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className="clients-pieces-nom clients-pieces-nom-btn"
                title={`Aperçu — ${p.nom_fichier}`}
                disabled={apercuBusyId === p.id}
                onClick={() => void ouvrirApercu(p)}
              >
                {p.nom_fichier}
              </button>
              <span className="clients-pieces-item-actions">
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  disabled={apercuBusyId === p.id}
                  onClick={() => void ouvrirApercu(p)}
                  aria-label={`Aperçu ${p.nom_fichier}`}
                >
                  {apercuBusyId === p.id ? "…" : "Aperçu"}
                </button>
                {!disabled && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={busy}
                    onClick={() => void retirer(p.id)}
                    aria-label={`Retirer ${p.nom_fichier}`}
                  >
                    Retirer
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      {apercu && (
        <div
          className="clients-pieces-apercu-overlay"
          role="dialog"
          aria-modal="true"
          aria-label={`Aperçu ${apercu.nom}`}
          onClick={fermerApercu}
        >
          <div
            className="clients-pieces-apercu"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="clients-pieces-apercu-head">
              <p className="clients-pieces-apercu-titre" title={apercu.nom}>
                {apercu.nom}
              </p>
              <span className="clients-pieces-apercu-actions">
                <a
                  className="btn btn-ghost btn-sm"
                  href={apercu.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Nouvel onglet
                </a>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={fermerApercu}
                >
                  Fermer
                </button>
              </span>
            </div>
            {apercu.kind === "pdf" && (
              <iframe
                className="clients-pieces-apercu-frame"
                title={apercu.nom}
                src={apercu.url}
              />
            )}
            {apercu.kind === "image" && (
              <img
                className="clients-pieces-apercu-img"
                src={apercu.url}
                alt={apercu.nom}
              />
            )}
            {apercu.kind === "autre" && (
              <p className="clients-pieces-msg">
                Aperçu intégré indisponible pour ce type — ouvrir dans un
                nouvel onglet.
              </p>
            )}
          </div>
        </div>
      )}

      {pieces.length > 0 && (
        <div className="cta-row clients-pieces-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || disabled}
            onClick={() => void extraire()}
          >
            {busyMode === "extract"
              ? "Extraction…"
              : err
                ? "Réessayer"
                : "Extraire"}
          </button>
          {modeConformite && (
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy}
              onClick={() => void verifier()}
            >
              {busyMode === "conformite" ? "Contrôle…" : "Vérifier"}
            </button>
          )}
          {sessionUpload && !contribuableId && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={busy || disabled}
              onClick={() => void abandonnerSession()}
            >
              {busyMode === "abandon" ? "Abandon…" : "Abandonner"}
            </button>
          )}
        </div>
      )}

      {busyMode === "extract" && (
        <div
          className="clients-pieces-extract-progress"
          role="status"
          aria-live="polite"
          aria-busy="true"
        >
          <div className="clients-pieces-extract-track" aria-hidden="true">
            <span className="clients-pieces-extract-bar" />
          </div>
          <p className="clients-pieces-msg clients-pieces-busy">
            Analyse du document…
          </p>
        </div>
      )}

      {avertissements.length > 0 && (
        <ul className="clients-pieces-avertissements" role="status">
          {avertissements.map((a) => (
            <li key={a.slice(0, 48)}>{messageMetierSansProvider(a)}</li>
          ))}
        </ul>
      )}

      {proposition && proposition.disponible && (
        <div className="clients-pieces-proposition">
          <p className="picker-kicker">Brouillon</p>
          {champsLus.length > 0 && (
            <ul className="clients-pieces-champs">
              {champsLus.map(([champ, val]) => {
                const cit = citationParChamp(champ);
                const applique = champsAppliques.has(champ);
                let affichage = String(val);
                if (champ === "regime_fiscal") {
                  affichage = mapperRegimeFiscal(affichage) || affichage;
                }
                if (champ === "forme_juridique") {
                  affichage = mapperFormeJuridique(affichage) || affichage;
                }
                return (
                  <li key={champ} className={applique ? "applique" : ""}>
                    <strong>{LIBELLES_CHAMP[champ] ?? champ}</strong>
                    <span>{affichage}</span>
                    {cit && (
                      <em title={cit.extrait}>
                        {cit.extrait.slice(0, 60)}
                        {cit.extrait.length > 60 ? "…" : ""}
                      </em>
                    )}
                    {applique && <mark>appliqué</mark>}
                  </li>
                );
              })}
            </ul>
          )}
          {champsNonLus.length > 0 && (
            <p className="clients-pieces-manquants-inline">
              <span>Non lus :</span>{" "}
              {champsNonLus
                .map((champ) => LIBELLES_CHAMP[champ] ?? champ)
                .join(", ")}
            </p>
          )}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={busy || disabled}
            onClick={() => void appliquerBrouillon()}
          >
            Appliquer
          </button>
        </div>
      )}

      {conformite && conformite.disponible && (
        <div
          className={`clients-pieces-conformite${conformite.ok ? " ok" : ""}`}
        >
          <p className="picker-kicker">
            Conformité {conformite.ok ? "— OK" : "— écarts"}
          </p>
          {conformite.ecarts.length === 0 ? (
            <p className="clients-pieces-msg">Aucun écart.</p>
          ) : (
            <ul className="clients-pieces-ecarts">
              {conformite.ecarts.map((e, i) => (
                <li key={`${e.champ}-${i}`} data-sev={e.severity}>
                  <strong>{LIBELLES_CHAMP[e.champ || ""] ?? e.champ}</strong>
                  <span>{e.message}</span>
                  {e.saisi != null && <em>Saisi : {e.saisi}</em>}
                  {e.lu_dans_piece != null && (
                    <em>Pièce : {e.lu_dans_piece}</em>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {msg && !err && (
        <p className="clients-pieces-msg clients-pieces-msg-succes" role="status">
          {msg}
        </p>
      )}
      {err && (
        <p className="clients-creation-error" role="alert">
          {err}
        </p>
      )}

      {(historique.length > 0 ||
        (sessionUpload && !contribuableId && ttlHint != null)) && (
        <details className="clients-pieces-historique">
          <summary>
            {historique.length > 0
              ? `Historique (${historique.length})`
              : "Session"}
          </summary>
          {sessionUpload && !contribuableId && ttlHint != null && (
            <p className="clients-pieces-msg">
              Purge auto après {ttlHint} h.
            </p>
          )}
          {historique.length > 0 && (
            <ul>
              {historique.map((h) => (
                <li key={h.proposition_id}>
                  <strong>#{h.proposition_id}</strong>
                  <span>{h.statut}</span>
                  {h.cree_le && (
                    <time dateTime={h.cree_le}>
                      {h.cree_le.replace("T", " ").slice(0, 19)}
                    </time>
                  )}
                  {h.message && (
                    <em>{messageMetierSansProvider(h.message).slice(0, 100)}</em>
                  )}
                </li>
              ))}
            </ul>
          )}
        </details>
      )}
    </div>
  );
}
