/** Agent fiscal flottant — accessible depuis n'importe quel écran du
 * cabinet (portefeuille, fiche client, mission…), à la manière d'un
 * copilote de navigateur : bouton persistant qui ouvre un panneau latéral
 * ancré à droite, sans dépendre d'une mission ouverte. */
import { useCallback, useEffect, useRef, useState } from "react";
import { AgentChatVue } from "./AgentChatVue";

type Props = {
  jeton: string;
};

const MIN_LARGEUR = 320;
const MAX_LARGEUR = 720;
const LARGEUR_DEFAUT = 400;
const STORAGE_KEY = "rf-assistant-width";
const PAS_CLAVIER = 24;

function largeurMax(): number {
  return Math.min(MAX_LARGEUR, Math.floor(window.innerWidth * 0.5));
}

function bornerLargeur(w: number): number {
  return Math.max(MIN_LARGEUR, Math.min(largeurMax(), w));
}

function lireLargeur(): number {
  try {
    const brut = sessionStorage.getItem(STORAGE_KEY);
    if (brut) {
      const n = parseInt(brut, 10);
      if (!Number.isNaN(n)) return bornerLargeur(n);
    }
  } catch {
    /* sessionStorage indisponible */
  }
  return LARGEUR_DEFAUT;
}

function persisterLargeur(w: number): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, String(w));
  } catch {
    /* ignore */
  }
}

export function AssistantFlottant({ jeton }: Props) {
  const [ouvert, setOuvert] = useState(false);
  const [largeur, setLargeur] = useState(lireLargeur);
  const [agrandi, setAgrandi] = useState(false);
  const [redimensionne, setRedimensionne] = useState(false);
  const largeurManuelle = useRef(lireLargeur());
  const poigneeRef = useRef<HTMLDivElement>(null);

  const appliquerLargeur = useCallback((w: number, persist = true) => {
    const bornee = bornerLargeur(w);
    setLargeur(bornee);
    if (persist) {
      largeurManuelle.current = bornee;
      persisterLargeur(bornee);
    }
  }, []);

  useEffect(() => {
    const frame = document.querySelector(".app-frame") as HTMLElement | null;
    if (!frame) return;

    if (ouvert) {
      frame.classList.add("assistant-ouvert");
      frame.style.setProperty("--assistant-w", `${largeur}px`);
    } else {
      frame.classList.remove("assistant-ouvert");
      frame.style.removeProperty("--assistant-w");
    }

    return () => {
      frame.classList.remove("assistant-ouvert");
      frame.style.removeProperty("--assistant-w");
    };
  }, [ouvert, largeur]);

  useEffect(() => {
    const onResize = () => {
      setLargeur((prev) => bornerLargeur(prev));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    if (!redimensionne) return;

    const onMove = (e: MouseEvent | TouchEvent) => {
      const clientX =
        "touches" in e ? e.touches[0]?.clientX : e.clientX;
      if (clientX == null) return;
      const w = window.innerWidth - clientX;
      appliquerLargeur(w, false);
    };

    const onEnd = () => {
      setRedimensionne(false);
      setAgrandi(false);
      setLargeur((prev) => {
        const bornee = bornerLargeur(prev);
        largeurManuelle.current = bornee;
        persisterLargeur(bornee);
        return bornee;
      });
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onEnd);
    document.addEventListener("touchmove", onMove, { passive: true });
    document.addEventListener("touchend", onEnd);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onEnd);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onEnd);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [redimensionne, appliquerLargeur]);

  const demarrerRedimensionnement = () => setRedimensionne(true);

  const basculerAgrandir = () => {
    if (agrandi) {
      appliquerLargeur(largeurManuelle.current);
      setAgrandi(false);
    } else {
      largeurManuelle.current = largeur;
      appliquerLargeur(largeurMax(), false);
      setAgrandi(true);
    }
  };

  const ajusterClavier = (delta: number) => {
    setAgrandi(false);
    appliquerLargeur(largeur + delta);
  };

  const fermer = () => setOuvert(false);

  return (
    <>
      {!ouvert && (
        <button
          type="button"
          className="assistant-flottant-bouton"
          onClick={() => setOuvert(true)}
          aria-expanded={false}
          aria-controls="assistant-flottant-panneau"
          title="Agent fiscal"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path
              d="M4 4h16v12H7l-3 3V4z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinejoin="round"
            />
          </svg>
          <span className="assistant-flottant-label">Agent fiscal</span>
        </button>
      )}

      {ouvert && (
        <div
          id="assistant-flottant-panneau"
          className={`assistant-flottant-panneau${redimensionne ? " assistant-flottant-panneau--drag" : ""}`}
          role="dialog"
          aria-label="Agent fiscal"
          style={{ width: largeur }}
        >
          <div
            ref={poigneeRef}
            className="assistant-flottant-poignee"
            role="separator"
            aria-orientation="vertical"
            aria-label="Redimensionner le panneau agent fiscal"
            aria-valuemin={MIN_LARGEUR}
            aria-valuemax={largeurMax()}
            aria-valuenow={largeur}
            tabIndex={0}
            onMouseDown={(e) => {
              e.preventDefault();
              demarrerRedimensionnement();
            }}
            onTouchStart={(e) => {
              e.preventDefault();
              demarrerRedimensionnement();
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowLeft") {
                e.preventDefault();
                ajusterClavier(PAS_CLAVIER);
              } else if (e.key === "ArrowRight") {
                e.preventDefault();
                ajusterClavier(-PAS_CLAVIER);
              }
            }}
          />

          <div className="assistant-flottant-tete">
            <div className="assistant-flottant-tete-titre">
              <p className="picker-kicker">AGENT FISCAL</p>
              <span>Agent fiscal</span>
            </div>
            <div className="assistant-flottant-tete-actions">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={basculerAgrandir}
                aria-label={agrandi ? "Réduire le panneau" : "Agrandir le panneau"}
                title={agrandi ? "Réduire" : "Agrandir"}
              >
                {agrandi ? "Réduire" : "Agrandir"}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={fermer}
                aria-label="Fermer l'agent fiscal"
              >
                ✕
              </button>
            </div>
          </div>
          <div className="assistant-flottant-corps">
            <AgentChatVue jeton={jeton} sansEntete />
          </div>
        </div>
      )}
    </>
  );
}
