/** Assistant fiscal flottant — accessible depuis n'importe quel écran du
 * cabinet (portefeuille, fiche client, mission…), à la manière d'un
 * copilote de navigateur : bouton persistant qui ouvre un panneau de chat
 * indépendant, sans dépendre d'une mission ouverte. */
import { useState } from "react";
import { AgentChatVue } from "./AgentChatVue";

type Props = {
  jeton: string;
};

export function AssistantFlottant({ jeton }: Props) {
  const [ouvert, setOuvert] = useState(false);

  return (
    <>
      <button
        type="button"
        className="assistant-flottant-bouton"
        onClick={() => setOuvert((v) => !v)}
        aria-expanded={ouvert}
        aria-controls="assistant-flottant-panneau"
        title="Assistant IA — agent fiscal"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4 4h16v12H7l-3 3V4z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
        </svg>
        <span className="assistant-flottant-label">Assistant IA</span>
      </button>

      {ouvert && (
        <div
          id="assistant-flottant-panneau"
          className="assistant-flottant-panneau"
          role="dialog"
          aria-label="Assistant IA — agent fiscal"
        >
          <div className="assistant-flottant-tete">
            <span>Assistant IA du cabinet</span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setOuvert(false)}
              aria-label="Fermer l'assistant"
            >
              ✕
            </button>
          </div>
          <div className="assistant-flottant-corps">
            <AgentChatVue jeton={jeton} />
          </div>
        </div>
      )}
    </>
  );
}
