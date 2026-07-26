import { useMemo, useState } from "react";
import { Tooltip } from "./Tooltip";
import { estMissionActive, libelleStatut } from "./statuts";

// Ré-export pour les consommateurs existants (App.tsx, ClientsVue.tsx).
export { estMissionActive, libelleStatut } from "./statuts";

export type MissionRow = {
  id: number;
  exercice: number;
  statut: string;
  contribuable_denomination: string;
  contribuable_id: number;
  cree_le?: string | null;
  version_referentiel_id?: number | null;
  type_engagement?: string | null;
  type_engagement_libelle?: string | null;
  perimetre_impots?: string[] | null;
  revue_partielle?: boolean;
};

type Synthese = "toutes" | "actives" | "cloturees";

type Props = {
  missions: MissionRow[];
  filtreExercice: string;
  filtreStatut: string;
  estLecteur: boolean;
  busy?: boolean;
  onFiltrer: (opts: {
    filtreExercice: string;
    filtreStatut: string;
  }) => void;
  onOuvrirMission: (id: number) => void;
  onNouvelleMission: () => void;
};

function normaliserRecherche(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "");
}

export function MissionsVue({
  missions,
  filtreExercice,
  filtreStatut,
  estLecteur,
  busy = false,
  onFiltrer,
  onOuvrirMission,
  onNouvelleMission,
}: Props) {
  const [recherche, setRecherche] = useState("");
  const [synthese, setSynthese] = useState<Synthese>("toutes");

  const stats = useMemo(() => {
    const actives = missions.filter((m) => estMissionActive(m.statut)).length;
    return {
      toutes: missions.length,
      actives,
      cloturees: missions.length - actives,
    };
  }, [missions]);

  const exercicesDispo = useMemo(() => {
    const set = new Set<string>();
    for (const m of missions) set.add(String(m.exercice));
    if (filtreExercice && !set.has(filtreExercice)) set.add(filtreExercice);
    return [...set].sort((a, b) => {
      const na = Number(a);
      const nb = Number(b);
      if (!Number.isNaN(na) && !Number.isNaN(nb) && na !== nb) return nb - na;
      return b.localeCompare(a, "fr");
    });
  }, [missions, filtreExercice]);

  const statutsDispo = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of missions) {
      map.set(m.statut, (map.get(m.statut) ?? 0) + 1);
    }
    if (filtreStatut && !map.has(filtreStatut)) {
      map.set(filtreStatut, 0);
    }
    return [...map.entries()].sort((a, b) =>
      libelleStatut(a[0]).localeCompare(libelleStatut(b[0]), "fr"),
    );
  }, [missions, filtreStatut]);

  const liste = useMemo(() => {
    const q = normaliserRecherche(recherche);
    return missions.filter((m) => {
      if (synthese === "actives" && !estMissionActive(m.statut)) return false;
      if (synthese === "cloturees" && estMissionActive(m.statut)) return false;
      if (!q) return true;
      const nom = normaliserRecherche(m.contribuable_denomination);
      const id = String(m.id);
      return nom.includes(q) || id.includes(q) || `#${id}`.includes(q);
    });
  }, [missions, recherche, synthese]);

  const filtresActifs =
    Boolean(filtreExercice) ||
    Boolean(filtreStatut) ||
    Boolean(recherche.trim()) ||
    synthese !== "toutes";

  function appliquerFiltres(next: {
    filtreExercice?: string;
    filtreStatut?: string;
  }) {
    setSynthese("toutes");
    onFiltrer({
      filtreExercice:
        next.filtreExercice !== undefined ? next.filtreExercice : filtreExercice,
      filtreStatut:
        next.filtreStatut !== undefined ? next.filtreStatut : filtreStatut,
    });
  }

  function reinitialiser() {
    setRecherche("");
    setSynthese("toutes");
    onFiltrer({ filtreExercice: "", filtreStatut: "" });
  }

  function choisirSynthese(s: Synthese) {
    setSynthese(s);
    if (filtreStatut) {
      onFiltrer({
        filtreExercice,
        filtreStatut: "",
      });
    }
  }

  function choisirStatutChip(statut: string) {
    const next = filtreStatut === statut ? "" : statut;
    appliquerFiltres({ filtreStatut: next });
  }

  const emptyTitle = missions.length
    ? "Aucun résultat pour ces critères"
    : "Aucune mission pour l’instant";
  const emptyBody = missions.length
    ? "Élargissez la recherche, changez les filtres ou réinitialisez la vue."
    : estLecteur
      ? "Les missions du cabinet apparaîtront ici dès qu’elles seront créées."
      : "Créez une mission pour démarrer une revue fiscale sur un contribuable.";

  return (
    <div className="page missions-vue">
      <header className="page-head missions-head">
        <div>
          <p className="page-eyebrow">Travail</p>
          <h2 className="section-title">Missions</h2>
          <p className="section-sub">
            Centre de travail du réviseur — dossiers ouverts, filtres et accès
            direct à la restitution.
          </p>
        </div>
        {!estLecteur && (
          <div className="page-actions">
            <Tooltip label="Créer une nouvelle mission de revue fiscale.">
              <button
                type="button"
                className="btn btn-primary"
                onClick={onNouvelleMission}
              >
                Nouvelle mission
              </button>
            </Tooltip>
          </div>
        )}
      </header>

      <div
        className="missions-synth"
        role="group"
        aria-label="Synthèse des missions chargées"
      >
        {(
          [
            {
              id: "toutes" as const,
              label: "Toutes",
              value: stats.toutes,
              tip: "Afficher toutes les missions chargées.",
            },
            {
              id: "actives" as const,
              label: "En cours",
              value: stats.actives,
              tip: "Missions non clôturées (cadrage, ouverte, en cours…).",
            },
            {
              id: "cloturees" as const,
              label: "Clôturées",
              value: stats.cloturees,
              tip: "Missions clôturées ou terminées.",
            },
          ] as const
        ).map((item) => (
          <Tooltip key={item.id} label={item.tip}>
            <button
              type="button"
              className={`missions-synth-btn${synthese === item.id ? " is-active" : ""}`}
              aria-pressed={synthese === item.id}
              onClick={() => choisirSynthese(item.id)}
            >
              <span className="missions-synth-value">{item.value}</span>
              <span className="missions-synth-label">{item.label}</span>
            </button>
          </Tooltip>
        ))}
      </div>

      <div className="missions-toolbar" role="search" aria-label="Filtres des missions">
        <div className="missions-toolbar-search">
          <label htmlFor="missions-q">Recherche</label>
          <input
            id="missions-q"
            type="search"
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
            placeholder="Client ou #mission"
            autoComplete="off"
            spellCheck={false}
            title="Filtrer localement par nom de client ou numéro de mission"
          />
        </div>
        <div>
          <label htmlFor="missions-ex">Exercice</label>
          <select
            id="missions-ex"
            value={filtreExercice}
            disabled={busy}
            title="Filtrer par exercice fiscal (appliqué immédiatement)"
            onChange={(e) => appliquerFiltres({ filtreExercice: e.target.value })}
          >
            <option value="">Tous</option>
            {exercicesDispo.map((ex) => (
              <option key={ex} value={ex}>
                {ex}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="missions-st">Statut</label>
          <select
            id="missions-st"
            value={filtreStatut}
            disabled={busy}
            title="Filtrer par statut de mission (appliqué immédiatement)"
            onChange={(e) => appliquerFiltres({ filtreStatut: e.target.value })}
          >
            <option value="">Tous</option>
            {statutsDispo.map(([statut, n]) => (
              <option key={statut} value={statut}>
                {libelleStatut(statut)}
                {n > 0 ? ` (${n})` : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="missions-toolbar-actions">
          <Tooltip label="Effacer recherche, synthèse et filtres.">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={reinitialiser}
              disabled={busy || !filtresActifs}
            >
              Réinitialiser
            </button>
          </Tooltip>
        </div>
      </div>

      {statutsDispo.length > 0 && (
        <div className="missions-chips" aria-label="Filtres rapides par statut">
          <span className="missions-chips-label">Statuts</span>
          {statutsDispo.map(([statut, n]) => (
            <Tooltip
              key={statut}
              label={`Filtrer au statut « ${libelleStatut(statut)} ».`}
            >
              <button
                type="button"
                className={`missions-chip${filtreStatut === statut ? " is-active" : ""}`}
                aria-pressed={filtreStatut === statut}
                onClick={() => choisirStatutChip(statut)}
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

      <div className="panel dense missions-panel">
        <div className="missions-panel-head">
          <p className="missions-count">
            {liste.length} mission{liste.length !== 1 ? "s" : ""}
            {filtresActifs ? " · filtrées" : ""}
          </p>
          <p className="missions-panel-hint">
            Cliquez une ligne ou « Ouvrir » pour accéder à la restitution.
          </p>
        </div>

        {liste.length > 0 ? (
          <div className="missions-table-wrap">
            <table className="missions-table" aria-label="Liste des missions">
              <thead className="missions-thead">
                <tr>
                  <th scope="col">Mission</th>
                  <th scope="col">Client</th>
                  <th scope="col" className="missions-th-ex">
                    Exercice
                  </th>
                  <th scope="col">Statut</th>
                  <th scope="col" className="missions-col-action">
                    Action
                  </th>
                </tr>
              </thead>
              <tbody>
                {liste.map((m) => (
                  <tr
                    key={m.id}
                    className="missions-tr"
                    onClick={() => onOuvrirMission(m.id)}
                  >
                    <td className="missions-cell-id">
                      <span className="missions-id-mono">#{m.id}</span>
                    </td>
                    <td className="missions-cell-client">
                      <Tooltip
                        label={m.contribuable_denomination}
                        side="bottom"
                      >
                        <span className="missions-client-name">
                          {m.contribuable_denomination}
                        </span>
                      </Tooltip>
                    </td>
                    <td className="missions-cell-ex">{m.exercice}</td>
                    <td className="missions-cell-statut">
                      <span className={`badge statut-${m.statut}`}>
                        {libelleStatut(m.statut)}
                      </span>
                      {m.revue_partielle ? (
                        <span className="badge badge-partielle">
                          Revue partielle
                        </span>
                      ) : null}
                    </td>
                    <td className="missions-cell-action">
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm missions-open-btn"
                        aria-label={`Ouvrir la mission #${m.id}, ${m.contribuable_denomination}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          onOuvrirMission(m.id);
                        }}
                      >
                        Ouvrir
                        <span className="missions-open-arrow" aria-hidden="true">
                          →
                        </span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="missions-empty">
            <p className="missions-empty-title">{emptyTitle}</p>
            <p className="missions-empty-body">{emptyBody}</p>
            <div className="missions-empty-actions">
              {filtresActifs && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={reinitialiser}
                >
                  Réinitialiser les filtres
                </button>
              )}
              {!estLecteur && !missions.length && (
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={onNouvelleMission}
                >
                  Nouvelle mission
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
