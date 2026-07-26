/** Rendu de texte avec tooltips juridiques sur les citations d'articles. */
import { useRef, useState, type ReactNode } from "react";
import {
  MENTION_PRUDENCE,
  chercherFiche,
  type FicheJuridique,
} from "./referentielJuridique";

const CODES = "LPF|CGI(?:\\s+CI)?|AUSCGIE|OHADA";
const ARTICLE =
  "art\\.\\s*L?\\d+[a-z]?(?:\\s+[A-Z](?![\\w’']))?(?:\\s*\\d+°)?" +
  "(?:\\s*(?:bis|ter))?(?:\\s*(?:et\\s+s\\.|s\\.))?";

const MOTIF_CITATION = new RegExp(
  `(?:${ARTICLE}\\s*(?:du\\s+)?(?:${CODES})` +
    `|(?:${CODES})(?:\\s+\\d{4})?\\s*,?\\s*${ARTICLE})`,
  "g",
);

function cleCitation(brut: string): string {
  const code = /LPF|AUSCGIE|OHADA|CGI/.exec(brut)?.[0] ?? "";
  const apresArt = brut.slice(brut.search(/art\./i));
  const article =
    /L?\d+[a-z]?(?:\s+[A-Z](?![\w’']))?(?:\s+(?:bis|ter))?/.exec(
      apresArt,
    )?.[0] ?? "";
  return `${article.replace(/\s+/g, " ").trim()} ${code}`.trim();
}

function TermeJuridique({ citation }: { citation: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [pos, setPos] = useState<{ gauche: number; haut: number } | null>(
    null,
  );
  const fiche: FicheJuridique | null = chercherFiche(cleCitation(citation));

  function montrer() {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    const largeur = 320;
    const gauche = Math.max(
      8,
      Math.min(
        rect.left + rect.width / 2 - largeur / 2,
        window.innerWidth - largeur - 8,
      ),
    );
    setPos({ gauche, haut: rect.bottom + 6 });
  }

  return (
    <span
      ref={ref}
      className="juridique-terme"
      tabIndex={0}
      onMouseEnter={montrer}
      onMouseLeave={() => setPos(null)}
      onFocus={montrer}
      onBlur={() => setPos(null)}
    >
      {citation}
      {pos && (
        <span
          className="juridique-tooltip"
          role="tooltip"
          style={{ left: pos.gauche, top: pos.haut }}
        >
          {fiche ? (
            <>
              <span className="juridique-tooltip-reference">
                {fiche.reference}
              </span>
              <span className="juridique-tooltip-intitule">
                {fiche.intitule}
              </span>
              <span className="juridique-tooltip-texte">{fiche.resume}</span>
              <span className="juridique-tooltip-texte is-interpretation">
                {fiche.interpretation}
              </span>
            </>
          ) : (
            <span className="juridique-tooltip-texte">
              Référence non documentée dans le référentiel interne. Vérifier
              le texte en vigueur.
            </span>
          )}
          <span className="juridique-tooltip-prudence">
            {MENTION_PRUDENCE}
          </span>
        </span>
      )}
    </span>
  );
}

export function TexteJuridique({ texte }: { texte: string }) {
  if (!texte) return null;
  MOTIF_CITATION.lastIndex = 0;
  if (!MOTIF_CITATION.test(texte)) return <>{texte}</>;
  MOTIF_CITATION.lastIndex = 0;
  const morceaux: ReactNode[] = [];
  let curseur = 0;
  let m: RegExpExecArray | null;
  while ((m = MOTIF_CITATION.exec(texte)) !== null) {
    if (m.index > curseur) morceaux.push(texte.slice(curseur, m.index));
    morceaux.push(<TermeJuridique key={`${m.index}`} citation={m[0]} />);
    curseur = m.index + m[0].length;
  }
  if (curseur < texte.length) morceaux.push(texte.slice(curseur));
  return <>{morceaux}</>;
}
