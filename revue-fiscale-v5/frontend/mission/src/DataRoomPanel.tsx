/** Data Room — synthèse IA, coffre documentaire, mémoire client, timeline. */
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, apiUpload, telecharger } from "./api";
import {
  TYPES_PIECE_CONTRIBUABLE,
  type PieceContribuable,
} from "./PiecesContribuable";
import { TexteJuridique } from "./TexteJuridique";

type TypeEntreeMemoire = "fait" | "contexte" | "alerte" | "note";

type MemoireEntree = {
  id: number;
  contribuable_id: number;
  type_entree: TypeEntreeMemoire | string;
  contenu: string;
  source_type: string;
  source_ref?: string | null;
  auteur?: string | null;
  cree_le?: string | null;
};

type EvenementTimeline = {
  id: number;
  horodatage?: string | null;
  acteur: string;
  action: string;
  mission_id?: number | null;
  charge_utile?: Record<string, unknown>;
};

const TYPES_ENTREE: { id: TypeEntreeMemoire; label: string }[] = [
  { id: "fait", label: "Fait" },
  { id: "contexte", label: "Contexte" },
  { id: "alerte", label: "Alerte" },
  { id: "note", label: "Note" },
];

const SOURCES_LABEL: Record<string, string> = {
  extraction: "Extraction",
  mission: "Mission",
  risque: "Risque",
  manuel: "Manuel",
  synthese: "Synthèse IA",
};

type SyntheseVersion = {
  id: number;
  contribuable_id: number;
  version: number;
  statut: "en_cours" | "disponible" | "echec" | string;
  modele?: string | null;
  erreur?: string | null;
  auteur?: string | null;
  cree_le?: string | null;
};

type SyntheseContenu = {
  resume?: string;
  points_cles?: { texte: string; sources: string[] }[];
  incoherences?: {
    description: string;
    sources: string[];
    gravite: "faible" | "moyenne" | "haute" | string;
  }[];
  recommandations?: { texte: string; sources: string[] }[];
};

type SyntheseDetail = SyntheseVersion & {
  contenu?: SyntheseContenu | null;
};

const GRAVITES_LABEL: Record<string, string> = {
  faible: "Faible",
  moyenne: "Moyenne",
  haute: "Haute",
};

function ancreSource(ref: string): string | null {
  const [prefixe, id] = ref.split(":");
  if (!id) return null;
  if (prefixe === "memoire") return `dataroom-memoire-${id}`;
  if (prefixe === "piece") return `dataroom-piece-${id}`;
  return null;
}

function libelleTypePiece(type: string): string {
  return (
    TYPES_PIECE_CONTRIBUABLE.find((t) => t.id === type)?.label || type
  );
}

function libelleTypeEntree(type: string): string {
  return TYPES_ENTREE.find((t) => t.id === type)?.label || type;
}

function formaterDate(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("fr-FR", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function formaterDateHeure(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("fr-FR", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function exercicePiece(p: PieceContribuable): string {
  if (!p.cree_le) return "Sans date";
  const annee = new Date(p.cree_le).getFullYear();
  return Number.isFinite(annee) ? String(annee) : "Sans date";
}

const ACTIONS_LABEL: Record<string, string> = {
  creation_contribuable: "Création de la fiche contribuable",
  creation_mission: "Création d’une mission",
  cadrage_mission: "Cadrage de la mission",
  changement_statut: "Changement de statut de mission",
  ajout_memoire_client: "Ajout d’une entrée mémoire",
  depot_piece_contribuable: "Dépôt d’une pièce au coffre documentaire",
  retrait_memoire_client: "Retrait d’une entrée mémoire",
  generation_synthese_client: "Génération d’une synthèse IA",
};

function libelleAction(action: string): string {
  return ACTIONS_LABEL[action] || action.replace(/_/g, " ");
}

export function DataRoomPanel({
  jeton,
  contribuableId,
  estLecteur,
}: {
  jeton: string;
  contribuableId: number;
  estLecteur: boolean;
}) {
  const [pieces, setPieces] = useState<PieceContribuable[]>([]);
  const [entrees, setEntrees] = useState<MemoireEntree[]>([]);
  const [evenements, setEvenements] = useState<EvenementTimeline[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [filtreTypePiece, setFiltreTypePiece] = useState("tous");
  const [filtreExercice, setFiltreExercice] = useState("tous");
  const [filtreTypeEntree, setFiltreTypeEntree] = useState("tous");

  const [noteType, setNoteType] = useState<TypeEntreeMemoire>("note");
  const [noteContenu, setNoteContenu] = useState("");
  const [confirmationId, setConfirmationId] = useState<number | null>(null);
  const [dlBusyId, setDlBusyId] = useState<number | null>(null);

  const [uploadEnCours, setUploadEnCours] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const [uploadErr, setUploadErr] = useState<string | null>(null);

  const [versions, setVersions] = useState<SyntheseVersion[]>([]);
  const [syntheseId, setSyntheseId] = useState<number | null>(null);
  const [synthese, setSynthese] = useState<SyntheseDetail | null>(null);
  const [analyseEnCours, setAnalyseEnCours] = useState(false);
  const [errSynthese, setErrSynthese] = useState<string | null>(null);

  const chargerPieces = useCallback(async () => {
    try {
      const liste = await api<PieceContribuable[]>(
        `/api/v1/pieces-contribuable?contribuable_id=${contribuableId}`,
        { jeton },
      );
      setPieces(Array.isArray(liste) ? liste : []);
    } catch {
      setPieces([]);
    }
  }, [contribuableId, jeton]);

  const chargerMemoire = useCallback(async () => {
    try {
      const liste = await api<MemoireEntree[]>(
        `/api/v1/contribuables/${contribuableId}/memoire`,
        { jeton },
      );
      setEntrees(Array.isArray(liste) ? liste : []);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [contribuableId, jeton]);

  const chargerTimeline = useCallback(async () => {
    try {
      const liste = await api<EvenementTimeline[]>(
        `/api/v1/contribuables/${contribuableId}/timeline`,
        { jeton },
      );
      setEvenements(Array.isArray(liste) ? liste : []);
    } catch {
      setEvenements([]);
    }
  }, [contribuableId, jeton]);

  const chargerVersions = useCallback(async () => {
    try {
      const liste = await api<SyntheseVersion[]>(
        `/api/v1/contribuables/${contribuableId}/syntheses`,
        { jeton },
      );
      const versions = Array.isArray(liste) ? liste : [];
      setVersions(versions);
      setSyntheseId((prec) =>
        prec != null && versions.some((v) => v.id === prec)
          ? prec
          : versions[0]?.id ?? null,
      );
    } catch {
      setVersions([]);
    }
  }, [contribuableId, jeton]);

  useEffect(() => {
    setErr(null);
    void chargerPieces();
    void chargerMemoire();
    void chargerTimeline();
    void chargerVersions();
  }, [chargerPieces, chargerMemoire, chargerTimeline, chargerVersions]);

  useEffect(() => {
    if (syntheseId == null) {
      setSynthese(null);
      return;
    }
    let annule = false;
    void (async () => {
      try {
        const detail = await api<SyntheseDetail>(
          `/api/v1/contribuables/${contribuableId}/syntheses/${syntheseId}`,
          { jeton },
        );
        if (!annule) setSynthese(detail);
      } catch (e) {
        if (!annule) {
          setSynthese(null);
          setErrSynthese(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      annule = true;
    };
  }, [contribuableId, jeton, syntheseId]);

  const exercices = useMemo(() => {
    const set = new Set(pieces.map(exercicePiece));
    return Array.from(set).sort().reverse();
  }, [pieces]);

  const typesPresents = useMemo(() => {
    const set = new Set(pieces.map((p) => String(p.type_piece)));
    return Array.from(set).sort();
  }, [pieces]);

  const piecesFiltrees = useMemo(
    () =>
      pieces.filter(
        (p) =>
          (filtreTypePiece === "tous" ||
            String(p.type_piece) === filtreTypePiece) &&
          (filtreExercice === "tous" || exercicePiece(p) === filtreExercice),
      ),
    [pieces, filtreTypePiece, filtreExercice],
  );

  const groupesPieces = useMemo(() => {
    const parType = new Map<string, Map<string, PieceContribuable[]>>();
    for (const p of piecesFiltrees) {
      const type = String(p.type_piece);
      const ex = exercicePiece(p);
      if (!parType.has(type)) parType.set(type, new Map());
      const parEx = parType.get(type)!;
      if (!parEx.has(ex)) parEx.set(ex, []);
      parEx.get(ex)!.push(p);
    }
    return Array.from(parType.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([type, parEx]) => ({
        type,
        exercices: Array.from(parEx.entries()).sort(([a], [b]) =>
          b.localeCompare(a),
        ),
      }));
  }, [piecesFiltrees]);

  const entreesFiltrees = useMemo(
    () =>
      entrees.filter(
        (e) =>
          filtreTypeEntree === "tous" ||
          String(e.type_entree) === filtreTypeEntree,
      ),
    [entrees, filtreTypeEntree],
  );

  async function uploaderPieces(fichiers: FileList | null) {
    if (!fichiers || fichiers.length === 0 || uploadEnCours) return;
    const liste = Array.from(fichiers);
    setUploadEnCours(true);
    setUploadMsg(null);
    setUploadErr(null);
    let envoyees = 0;
    let derniereErreur: string | null = null;
    for (const fichier of liste) {
      try {
        await apiUpload<PieceContribuable>(
          "/api/v1/pieces-contribuable",
          fichier,
          jeton,
          {
            type_piece: "auto",
            contribuable_id: String(contribuableId),
          },
        );
        envoyees += 1;
      } catch (e) {
        derniereErreur = e instanceof Error ? e.message : String(e);
      }
    }
    if (envoyees > 0) {
      setUploadMsg(
        envoyees === 1 ? "1 pièce ajoutée." : `${envoyees} pièces ajoutées.`,
      );
      await chargerPieces();
      await chargerMemoire();
      await chargerTimeline();
    }
    if (derniereErreur) {
      setUploadErr(
        envoyees > 0
          ? `Certaines pièces ont été refusées : ${derniereErreur}`
          : `Envoi impossible : ${derniereErreur}`,
      );
    }
    setUploadEnCours(false);
  }

  async function telechargerPiece(p: PieceContribuable) {
    setDlBusyId(p.id);
    setErr(null);
    try {
      await telecharger(
        `/api/v1/pieces-contribuable/${p.id}/contenu`,
        jeton,
        p.nom_fichier,
      );
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setDlBusyId(null);
    }
  }

  async function ajouterNote() {
    const contenu = noteContenu.trim();
    if (!contenu) return;
    setBusy(true);
    setErr(null);
    try {
      await api<MemoireEntree>(
        `/api/v1/contribuables/${contribuableId}/memoire`,
        {
          method: "POST",
          jeton,
          json: { type_entree: noteType, contenu },
        },
      );
      setNoteContenu("");
      await chargerMemoire();
      await chargerTimeline();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function retirerEntree(id: number) {
    setBusy(true);
    setErr(null);
    try {
      await api<MemoireEntree>(
        `/api/v1/contribuables/${contribuableId}/memoire/${id}`,
        { method: "DELETE", jeton },
      );
      setConfirmationId(null);
      await chargerMemoire();
      await chargerTimeline();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function lancerAnalyse() {
    setAnalyseEnCours(true);
    setErrSynthese(null);
    try {
      const creee = await api<SyntheseDetail>(
        `/api/v1/contribuables/${contribuableId}/syntheses`,
        { method: "POST", jeton },
      );
      setSynthese(creee);
      setSyntheseId(creee.id);
      await chargerVersions();
      await chargerMemoire();
      await chargerTimeline();
    } catch (e) {
      setErrSynthese(e instanceof Error ? e.message : String(e));
    } finally {
      setAnalyseEnCours(false);
    }
  }

  function allerVersSource(ref: string) {
    const ancre = ancreSource(ref);
    if (!ancre) return;
    document
      .getElementById(ancre)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function renduSources(sources?: string[]) {
    if (!sources || sources.length === 0) return null;
    return (
      <span className="dataroom-synthese-sources">
        {sources.map((ref) =>
          ancreSource(ref) ? (
            <button
              key={ref}
              type="button"
              className="dataroom-synthese-source"
              onClick={() => allerVersSource(ref)}
            >
              {ref}
            </button>
          ) : (
            <span key={ref} className="dataroom-synthese-source is-badge">
              {ref}
            </span>
          ),
        )}
      </span>
    );
  }

  const contenu = synthese?.statut === "disponible" ? synthese.contenu : null;

  return (
    <div className="dataroom">
      {err && (
        <p className="dataroom-erreur" role="alert">
          {err}
        </p>
      )}

      <div className="panel dense clients-fiche-panel dataroom-section">
        <div className="clients-fiche-section-head">
          <div>
            <p className="picker-kicker">Synthèse IA</p>
            <p className="picker-hint">
              Lecture d’ensemble du dossier : points clés, incohérences et
              recommandations, sourcés sur les éléments du Data Room.
            </p>
          </div>
          <div className="dataroom-synthese-actions">
            {versions.length > 0 && (
              <label className="dataroom-filtre">
                <span>Version</span>
                <select
                  value={syntheseId ?? ""}
                  onChange={(e) => setSyntheseId(Number(e.target.value))}
                  disabled={analyseEnCours}
                >
                  {versions.map((v) => (
                    <option key={v.id} value={v.id}>
                      v{v.version} · {formaterDateHeure(v.cree_le)}
                      {v.statut === "echec" ? " · échec" : ""}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {!estLecteur && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={analyseEnCours}
                onClick={() => void lancerAnalyse()}
              >
                {analyseEnCours ? "Analyse en cours…" : "Analyser"}
              </button>
            )}
          </div>
        </div>

        {errSynthese && (
          <p className="dataroom-erreur" role="alert">
            {errSynthese}
          </p>
        )}

        {synthese?.statut === "echec" && (
          <div className="dataroom-synthese-echec">
            <p>
              La génération de cette synthèse a échoué
              {synthese.erreur ? ` : ${synthese.erreur}` : "."}
            </p>
            {!estLecteur && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={analyseEnCours}
                onClick={() => void lancerAnalyse()}
              >
                Réessayer
              </button>
            )}
          </div>
        )}

        {contenu ? (
          <div className="dataroom-synthese-corps">
            {contenu.resume && (
              <p className="dataroom-synthese-resume">
                <TexteJuridique texte={contenu.resume} />
              </p>
            )}
            {(contenu.points_cles?.length ?? 0) > 0 && (
              <div className="dataroom-synthese-bloc">
                <p className="dataroom-synthese-bloc-titre">Points clés</p>
                <ul className="dataroom-synthese-liste">
                  {contenu.points_cles!.map((p, i) => (
                    <li key={i}>
                      <TexteJuridique texte={p.texte} />{" "}
                      {renduSources(p.sources)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(contenu.incoherences?.length ?? 0) > 0 && (
              <div className="dataroom-synthese-bloc">
                <p className="dataroom-synthese-bloc-titre">Incohérences</p>
                <ul className="dataroom-synthese-liste">
                  {contenu.incoherences!.map((inc, i) => (
                    <li key={i}>
                      <span
                        className={`dataroom-synthese-gravite is-${inc.gravite}`}
                      >
                        {GRAVITES_LABEL[inc.gravite] || inc.gravite}
                      </span>{" "}
                      <TexteJuridique texte={inc.description} />{" "}
                      {renduSources(inc.sources)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(contenu.recommandations?.length ?? 0) > 0 && (
              <div className="dataroom-synthese-bloc">
                <p className="dataroom-synthese-bloc-titre">
                  Recommandations
                </p>
                <ul className="dataroom-synthese-liste">
                  {contenu.recommandations!.map((r, i) => (
                    <li key={i}>
                      <TexteJuridique texte={r.texte} />{" "}
                      {renduSources(r.sources)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="dataroom-synthese-avertissement">
              Synthèse générée par IA — document consultatif, à valider par
              vos soins.
            </p>
          </div>
        ) : (
          synthese?.statut !== "echec" && (
            <p className="dataroom-vide">
              {analyseEnCours
                ? "Analyse en cours…"
                : versions.length === 0
                  ? "Aucune synthèse générée — lancez une analyse du dossier."
                  : "Synthèse indisponible pour cette version."}
            </p>
          )
        )}
      </div>

      <div className="panel dense clients-fiche-panel dataroom-section">
        <div className="clients-fiche-section-head">
          <div>
            <p className="picker-kicker">Coffre documentaire</p>
            <p className="picker-hint">
              {pieces.length} pièce{pieces.length !== 1 ? "s" : ""} du
              contribuable, groupées par type puis année d’ajout.
            </p>
          </div>
        </div>
        {!estLecteur && (
          <div className="dataroom-coffre-upload">
            <label className="dataroom-coffre-upload-label">
              <input
                type="file"
                multiple
                accept=".pdf,.png,.jpg,.jpeg,.webp"
                disabled={uploadEnCours}
                onChange={(e) => {
                  void uploaderPieces(e.target.files);
                  e.target.value = "";
                }}
              />
              <span className="dataroom-coffre-upload-hint">
                PDF, PNG, JPEG, WEBP — 25 Mo max. Type détecté
                automatiquement.
              </span>
            </label>
            {uploadEnCours && (
              <p className="dataroom-coffre-upload-statut">Envoi en cours…</p>
            )}
            {uploadMsg && !uploadEnCours && (
              <p className="dataroom-coffre-upload-succes">{uploadMsg}</p>
            )}
            {uploadErr && !uploadEnCours && (
              <p className="dataroom-coffre-upload-erreur" role="alert">
                {uploadErr}
              </p>
            )}
          </div>
        )}
        {pieces.length > 0 && (
          <div
            className="dataroom-filtres"
            role="group"
            aria-label="Filtrer les pièces"
          >
            <label className="dataroom-filtre">
              <span>Type</span>
              <select
                value={filtreTypePiece}
                onChange={(e) => setFiltreTypePiece(e.target.value)}
              >
                <option value="tous">Tous</option>
                {typesPresents.map((t) => (
                  <option key={t} value={t}>
                    {libelleTypePiece(t)}
                  </option>
                ))}
              </select>
            </label>
            <label className="dataroom-filtre">
              <span>Exercice</span>
              <select
                value={filtreExercice}
                onChange={(e) => setFiltreExercice(e.target.value)}
              >
                <option value="tous">Tous</option>
                {exercices.map((ex) => (
                  <option key={ex} value={ex}>
                    {ex}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        {groupesPieces.length > 0 ? (
          groupesPieces.map(({ type, exercices: parEx }) => (
            <div key={type} className="dataroom-groupe">
              <p className="dataroom-groupe-titre">{libelleTypePiece(type)}</p>
              {parEx.map(([ex, liste]) => (
                <div key={ex} className="dataroom-sous-groupe">
                  <p className="dataroom-sous-groupe-titre">{ex}</p>
                  <ul className="dataroom-pieces-liste">
                    {liste.map((p) => (
                      <li
                        key={p.id}
                        id={`dataroom-piece-${p.id}`}
                        className="dataroom-piece"
                      >
                        <span
                          className="dataroom-piece-nom"
                          title={p.nom_fichier}
                        >
                          {p.nom_fichier}
                        </span>
                        <span className="dataroom-piece-date">
                          {formaterDate(p.cree_le)}
                        </span>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          disabled={dlBusyId === p.id}
                          onClick={() => void telechargerPiece(p)}
                        >
                          {dlBusyId === p.id ? "…" : "Télécharger"}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ))
        ) : (
          <p className="dataroom-vide">
            {pieces.length > 0
              ? "Aucune pièce pour ces filtres."
              : "Aucune pièce déposée — ajoutez un premier document ci-dessus."}
          </p>
        )}
      </div>

      <div className="panel dense clients-fiche-panel dataroom-section">
        <div className="clients-fiche-section-head">
          <div>
            <p className="picker-kicker">Mémoire client</p>
            <p className="picker-hint">
              Faits, contexte, alertes et notes qui constituent la mémoire
              persistante du client.
            </p>
          </div>
          <div
            className="dataroom-memoire-filtres"
            role="group"
            aria-label="Filtrer la mémoire par type"
          >
            {[{ id: "tous", label: "Tous" }, ...TYPES_ENTREE].map((t) => (
              <button
                key={t.id}
                type="button"
                className={`dataroom-memoire-filtre${filtreTypeEntree === t.id ? " is-active" : ""}`}
                aria-pressed={filtreTypeEntree === t.id}
                onClick={() => setFiltreTypeEntree(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {!estLecteur && (
          <div className="dataroom-note-form">
            <label className="dataroom-filtre">
              <span>Type</span>
              <select
                value={noteType}
                onChange={(e) =>
                  setNoteType(e.target.value as TypeEntreeMemoire)
                }
                disabled={busy}
              >
                {TYPES_ENTREE.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
            <textarea
              className="dataroom-note-textarea"
              rows={2}
              maxLength={4000}
              placeholder="Ajouter une note à la mémoire du client…"
              value={noteContenu}
              onChange={(e) => setNoteContenu(e.target.value)}
              disabled={busy}
            />
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={busy || !noteContenu.trim()}
              onClick={() => void ajouterNote()}
            >
              Ajouter
            </button>
          </div>
        )}

        {entreesFiltrees.length > 0 ? (
          <ul className="dataroom-memoire-liste">
            {entreesFiltrees.map((e) => (
              <li
                key={e.id}
                id={`dataroom-memoire-${e.id}`}
                className={`dataroom-memoire-item type-${e.type_entree}`}
              >
                <div className="dataroom-memoire-meta">
                  <span
                    className={`dataroom-badge type-${e.type_entree}`}
                  >
                    {libelleTypeEntree(String(e.type_entree))}
                  </span>
                  <span className="dataroom-memoire-source">
                    {SOURCES_LABEL[e.source_type] || e.source_type}
                    {e.source_ref ? ` · ${e.source_ref}` : ""}
                  </span>
                  <span className="dataroom-memoire-date">
                    {formaterDateHeure(e.cree_le)}
                    {e.auteur ? ` · ${e.auteur}` : ""}
                  </span>
                  {!estLecteur &&
                    (confirmationId === e.id ? (
                      <span className="dataroom-memoire-confirm">
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm dataroom-btn-danger"
                          disabled={busy}
                          onClick={() => void retirerEntree(e.id)}
                        >
                          Confirmer le retrait
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          disabled={busy}
                          onClick={() => setConfirmationId(null)}
                        >
                          Annuler
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        disabled={busy}
                        onClick={() => setConfirmationId(e.id)}
                      >
                        Retirer
                      </button>
                    ))}
                </div>
                <p className="dataroom-memoire-contenu">
                  <TexteJuridique texte={e.contenu} />
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="dataroom-vide">
            {entrees.length > 0
              ? "Aucune entrée pour ce filtre."
              : "Mémoire vide — elle s’alimentera au fil des extractions, missions et risques."}
          </p>
        )}
      </div>

      <div className="panel dense clients-fiche-panel dataroom-section">
        <div className="clients-fiche-section-head">
          <div>
            <p className="picker-kicker">Timeline</p>
            <p className="picker-hint">
              Derniers événements du journal d’audit liés à ce contribuable.
            </p>
          </div>
        </div>
        {evenements.length > 0 ? (
          <ol className="dataroom-timeline">
            {evenements.map((ev) => (
              <li key={ev.id} className="dataroom-timeline-item">
                <span className="dataroom-timeline-date">
                  {formaterDateHeure(ev.horodatage)}
                </span>
                <span className="dataroom-timeline-corps">
                  <strong>
                    <TexteJuridique texte={libelleAction(ev.action)} />
                  </strong>
                  {ev.mission_id != null ? ` — mission #${ev.mission_id}` : ""}
                  <span className="dataroom-timeline-acteur">
                    {" "}
                    · {ev.acteur}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="dataroom-vide">Aucun événement enregistré.</p>
        )}
      </div>
    </div>
  );
}
