import { useRef, type KeyboardEvent } from "react";

/** Onglets du poste de travail mission (étape 3 du wizard). */
export type OngletMission =
  | "cadrage"
  | "sources"
  | "travaux"
  | "revue"
  | "restitution"
  | "cloture"
  | "assistant";

const ONGLETS: Array<{ id: OngletMission; libelle: string }> = [
  { id: "cadrage", libelle: "Cadrage" },
  { id: "sources", libelle: "Sources" },
  { id: "travaux", libelle: "Travaux" },
  { id: "revue", libelle: "Revue" },
  { id: "restitution", libelle: "Restitution" },
  { id: "cloture", libelle: "Clôture" },
  { id: "assistant", libelle: "Assistant IA" },
];

/**
 * Navigation par onglets du poste de travail mission — composant
 * présentational : l'état (onglet actif) et l'écriture du hash
 * restent portés par App. Accessible : tablist ARIA, sélection
 * suivant le focus aux flèches clavier, Home/End.
 */
export function MissionTabsNav({
  ongletActif,
  onNaviguer,
}: {
  ongletActif: OngletMission;
  onNaviguer: (o: OngletMission) => void;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  function surClavier(e: KeyboardEvent<HTMLDivElement>) {
    const idx = ONGLETS.findIndex((o) => o.id === ongletActif);
    let cible = -1;
    if (e.key === "ArrowRight") cible = (idx + 1) % ONGLETS.length;
    else if (e.key === "ArrowLeft")
      cible = (idx - 1 + ONGLETS.length) % ONGLETS.length;
    else if (e.key === "Home") cible = 0;
    else if (e.key === "End") cible = ONGLETS.length - 1;
    if (cible < 0) return;
    e.preventDefault();
    onNaviguer(ONGLETS[cible].id);
    refs.current[cible]?.focus();
  }

  return (
    <div
      className="mission-tabs"
      role="tablist"
      aria-label="Étapes de la mission"
      onKeyDown={surClavier}
    >
      {ONGLETS.map((o, i) => {
        const actif = o.id === ongletActif;
        return (
          <button
            key={o.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={`mission-tab-${o.id}`}
            aria-selected={actif}
            tabIndex={actif ? 0 : -1}
            className={`mission-tab${actif ? " active" : ""}`}
            onClick={() => onNaviguer(o.id)}
          >
            {o.libelle}
          </button>
        );
      })}
    </div>
  );
}
