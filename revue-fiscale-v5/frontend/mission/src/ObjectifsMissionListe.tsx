import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { api } from "./api";
import { InfoTip, Tooltip } from "./Tooltip";
import { PROCESS_TIPS } from "./processTips";
import {
  fusionnerSuggestionsObjectifs,
  type ObjectifSuggestion,
} from "./objectifsMissionSeed";

type Props = {
  jeton?: string | null;
  objectifsLibelles: string[];
  setObjectifsLibelles: Dispatch<SetStateAction<string[]>>;
  disabled?: boolean;
  /** Classe racine optionnelle (ex. dans affiner cadrage). */
  className?: string;
};

type SuggestionApi = { libelle: string; usage: number };

function ObjectifInput({
  idx,
  value,
  jeton,
  dejaUtilises,
  disabled,
  onChange,
}: {
  idx: number;
  value: string;
  jeton?: string | null;
  dejaUtilises: string[];
  disabled?: boolean;
  onChange: (v: string) => void;
}) {
  const [ouvert, setOuvert] = useState(false);
  const [cabinet, setCabinet] = useState<SuggestionApi[]>([]);
  const [busy, setBusy] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const debRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const suggestions = useMemo(
    () =>
      fusionnerSuggestionsObjectifs({
        q: value,
        cabinet,
        dejaUtilises,
        limit: 8,
      }),
    [value, cabinet, dejaUtilises],
  );

  const charger = useCallback(
    async (q: string) => {
      if (!jeton) {
        setCabinet([]);
        return;
      }
      setBusy(true);
      try {
        const qs = new URLSearchParams();
        if (q.trim()) qs.set("q", q.trim());
        qs.set("limit", "12");
        const path = `/api/v1/objectifs-mission/suggestions?${qs}`;
        const rows = await api<SuggestionApi[]>(path, { jeton });
        setCabinet(Array.isArray(rows) ? rows : []);
      } catch {
        setCabinet([]);
      } finally {
        setBusy(false);
      }
    },
    [jeton],
  );

  useEffect(() => {
    if (!ouvert) return;
    if (debRef.current) clearTimeout(debRef.current);
    debRef.current = setTimeout(() => {
      void charger(value);
    }, 220);
    return () => {
      if (debRef.current) clearTimeout(debRef.current);
    };
  }, [ouvert, value, charger]);

  useEffect(() => {
    if (!ouvert) return;
    const fermer = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOuvert(false);
      }
    };
    document.addEventListener("mousedown", fermer);
    return () => document.removeEventListener("mousedown", fermer);
  }, [ouvert]);

  const choisir = (s: ObjectifSuggestion) => {
    onChange(s.libelle);
    setOuvert(false);
  };

  const afficherListe =
    ouvert && !disabled && (suggestions.length > 0 || busy || !jeton);

  return (
    <div className="objectif-autocomplete" ref={wrapRef}>
      <input
        className="field-input"
        type="text"
        value={value}
        maxLength={500}
        placeholder={`Objectif ${idx + 1}`}
        aria-label={`Objectif ${idx + 1}`}
        aria-expanded={afficherListe}
        aria-controls={`objectif-sugg-${idx}`}
        aria-autocomplete="list"
        disabled={disabled}
        onFocus={() => setOuvert(true)}
        onChange={(e) => {
          onChange(e.target.value);
          setOuvert(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOuvert(false);
        }}
      />
      {afficherListe && (
        <ul
          className="objectif-autocomplete-liste"
          id={`objectif-sugg-${idx}`}
          role="listbox"
          aria-label={`Suggestions objectif ${idx + 1}`}
        >
          {busy && suggestions.length === 0 && (
            <li className="objectif-autocomplete-vide" role="presentation">
              Chargement…
            </li>
          )}
          {!busy &&
            suggestions.length === 0 && (
              <li className="objectif-autocomplete-vide" role="presentation">
                Aucune suggestion — saisissez librement
              </li>
            )}
          {suggestions.map((s) => (
            <li key={`${s.source}-${s.libelle}`} role="option">
              <button
                type="button"
                className="objectif-autocomplete-item"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choisir(s)}
              >
                <span className="objectif-autocomplete-lib">{s.libelle}</span>
                <span className="objectif-autocomplete-meta">
                  {s.source === "cabinet"
                    ? `Cabinet${s.usage && s.usage > 1 ? ` · ×${s.usage}` : ""}`
                    : "Modèle"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Liste éditable d'objectifs avec suggestions (modèles + historique cabinet). */
export function ObjectifsMissionListe({
  jeton,
  objectifsLibelles,
  setObjectifsLibelles,
  disabled,
  className,
}: Props) {
  return (
    <div className={className ?? "field cadrage2-affiner-pleine"}>
      <p className="label-with-tip impot-perimetre-lbl">
        Objectifs de la mission
        <InfoTip
          label={
            PROCESS_TIPS.objectifsMission +
            " Saisie assistée : modèles et objectifs déjà utilisés sur vos missions."
          }
          ariaLabel="Aide : objectifs mission"
        />
      </p>
      <ul className="objectifs-edit-list">
        {objectifsLibelles.map((lib, idx) => (
          <li key={`obj-${idx}`}>
            <ObjectifInput
              idx={idx}
              value={lib}
              jeton={jeton}
              disabled={disabled}
              dejaUtilises={objectifsLibelles
                .map((x, i) => (i === idx ? "" : x.trim()))
                .filter(Boolean)}
              onChange={(v) => {
                setObjectifsLibelles((prev) =>
                  prev.map((x, i) => (i === idx ? v : x)),
                );
              }}
            />
            <Tooltip label={`Retirer l'objectif ${idx + 1}`}>
              <button
                type="button"
                className="cadrage2-obj-retirer"
                disabled={disabled || objectifsLibelles.length <= 1}
                aria-label={`Retirer l'objectif ${idx + 1}`}
                onClick={() => {
                  setObjectifsLibelles((prev) =>
                    prev.length <= 1 ? prev : prev.filter((_, i) => i !== idx),
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
        disabled={disabled || objectifsLibelles.length >= 50}
        onClick={() => setObjectifsLibelles((prev) => [...prev, ""])}
      >
        Ajouter un objectif
      </button>
    </div>
  );
}
