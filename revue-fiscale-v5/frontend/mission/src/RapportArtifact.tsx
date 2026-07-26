import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  parseRapportDocument,
  type Align,
  type MdBlock,
  type MdInline,
  type MdListItem,
} from "./markdownLight";

type Props = {
  markdown: string;
};

function InlineNodes({ nodes }: { nodes: MdInline[] }): ReactNode {
  return nodes.map((n, i) => {
    switch (n.kind) {
      case "text":
        return <span key={i}>{n.value}</span>;
      case "strong":
        return (
          <strong key={i}>
            <InlineNodes nodes={n.children} />
          </strong>
        );
      case "em":
        return (
          <em key={i}>
            <InlineNodes nodes={n.children} />
          </em>
        );
      case "code":
        return (
          <code key={i} className="rapport-artifact-code">
            {n.value}
          </code>
        );
      case "link":
        return (
          <a
            key={i}
            href={n.href}
            className="rapport-artifact-link"
            target="_blank"
            rel="noopener noreferrer"
          >
            <InlineNodes nodes={n.children} />
          </a>
        );
      default:
        return null;
    }
  });
}

function buildListTree(
  items: MdListItem[],
  start: number,
  depth: number,
): { nodes: ReactNode[]; next: number } {
  const nodes: ReactNode[] = [];
  let i = start;
  while (i < items.length) {
    const item = items[i]!;
    if (item.depth < depth) break;
    if (item.depth > depth) {
      const nested = buildListTree(items, i, depth + 1);
      nodes.push(
        <li key={`nest-${i}`} className="rapport-artifact-li-nest">
          <ul>{nested.nodes}</ul>
        </li>,
      );
      i = nested.next;
      continue;
    }
    const content = <InlineNodes nodes={item.inlines} />;
    i += 1;
    if (i < items.length && items[i]!.depth > depth) {
      const nested = buildListTree(items, i, depth + 1);
      nodes.push(
        <li key={`li-${i}`}>
          {content}
          <ul>{nested.nodes}</ul>
        </li>,
      );
      i = nested.next;
    } else {
      nodes.push(<li key={`li-${i}`}>{content}</li>);
    }
  }
  return { nodes, next: i };
}

function ListBlock({ items }: { items: MdListItem[] }) {
  if (!items.length) return null;
  const min = Math.min(...items.map((it) => it.depth));
  const { nodes } = buildListTree(items, 0, min);
  return <ul className="rapport-artifact-ul">{nodes}</ul>;
}

function Chevron({ open }: { open: boolean }) {
  return (
    <span
      className={`rapport-artifact-chevron${open ? " is-open" : ""}`}
      aria-hidden
    >
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <path
          d="M3.5 5.25 7 8.75l3.5-3.5"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

function BlockView({ block }: { block: MdBlock }) {
  switch (block.type) {
    case "h1":
      return (
        <h2 className="rapport-artifact-h1">
          <InlineNodes nodes={block.inlines} />
        </h2>
      );
    case "h2":
      return (
        <h3 className="rapport-artifact-h2">
          <InlineNodes nodes={block.inlines} />
        </h3>
      );
    case "h3":
      return (
        <h4 className="rapport-artifact-h3">
          <InlineNodes nodes={block.inlines} />
        </h4>
      );
    case "p":
      return (
        <p className="rapport-artifact-p">
          <InlineNodes nodes={block.inlines} />
        </p>
      );
    case "blockquote":
      return (
        <blockquote className="rapport-artifact-quote">
          <InlineNodes nodes={block.inlines} />
        </blockquote>
      );
    case "ul":
      return <ListBlock items={block.items} />;
    case "table":
      return (
        <div className="rapport-artifact-table-wrap">
          <table className="rapport-artifact-table">
            <thead>
              <tr>
                {block.headers.map((h, i) => (
                  <th
                    key={i}
                    style={{ textAlign: (block.aligns[i] as Align) || "left" }}
                  >
                    <InlineNodes nodes={h} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, ri) => (
                <tr key={ri}>
                  {row.map((cell, ci) => (
                    <td
                      key={ci}
                      style={{
                        textAlign: (block.aligns[ci] as Align) || "left",
                      }}
                    >
                      <InlineNodes nodes={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "hr":
      return <hr className="rapport-artifact-hr" />;
    default:
      return null;
  }
}

function Blocks({ blocks }: { blocks: MdBlock[] }) {
  return (
    <div className="rapport-artifact-body">
      {blocks.map((b, i) => (
        <BlockView key={i} block={b} />
      ))}
    </div>
  );
}

function sectionKey(title: string, i: number): string {
  return `${title}-${i}`;
}

export function RapportArtifact({ markdown }: Props) {
  const doc = useMemo(() => parseRapportDocument(markdown), [markdown]);
  const [ouvert, setOuvert] = useState<Record<string, boolean>>({});
  const [sourceOuverte, setSourceOuverte] = useState(false);

  useEffect(() => {
    setOuvert({});
    setSourceOuverte(false);
  }, [markdown]);

  if (!markdown.trim()) {
    return <p className="empty-state">Rapport indisponible.</p>;
  }

  const hasStructure = doc.sections.length > 0;

  function estOuvert(key: string, index: number): boolean {
    return ouvert[key] ?? index < 3;
  }

  function toutDeployer(open: boolean) {
    const next: Record<string, boolean> = {};
    doc.sections.forEach((sec, i) => {
      next[sectionKey(sec.title, i)] = open;
    });
    setOuvert(next);
  }

  return (
    <article className="rapport-artifact" aria-label="Rapport de mission">
      <header className="rapport-artifact-hero">
        <p className="rapport-artifact-eyebrow">Artefact livrable</p>
        <h2 className="rapport-artifact-title">
          {doc.title ? (
            <InlineNodes nodes={doc.titleInlines} />
          ) : (
            "Rapport de mission"
          )}
        </h2>
        <p className="rapport-artifact-lede">
          Document produit par le moteur — lecture structurée, sans recalcul.
        </p>
      </header>

      {doc.preamble.length > 0 && (
        <div className="rapport-artifact-preamble">
          <Blocks blocks={doc.preamble} />
        </div>
      )}

      {hasStructure ? (
        <>
          <div className="rapport-artifact-controls" role="toolbar" aria-label="Sections du rapport">
            <span className="rapport-artifact-controls-meta">
              {doc.sections.length} section
              {doc.sections.length > 1 ? "s" : ""}
            </span>
            <button
              type="button"
              className="rapport-artifact-ctrl"
              onClick={() => toutDeployer(true)}
            >
              Tout déployer
            </button>
            <button
              type="button"
              className="rapport-artifact-ctrl"
              onClick={() => toutDeployer(false)}
            >
              Tout replier
            </button>
          </div>
          <div className="rapport-artifact-sections">
            {doc.sections.map((sec, i) => {
              const key = sectionKey(sec.title, i);
              const open = estOuvert(key, i);
              return (
                <details
                  key={key}
                  className={`rapport-artifact-section${open ? " is-open" : ""}`}
                  open={open}
                  onToggle={(e) => {
                    const el = e.currentTarget;
                    setOuvert((m) => ({ ...m, [key]: el.open }));
                  }}
                >
                  <summary className="rapport-artifact-summary">
                    <span className="rapport-artifact-summary-idx" aria-hidden>
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="rapport-artifact-summary-label">
                      <InlineNodes nodes={sec.titleInlines} />
                    </span>
                    <Chevron open={open} />
                  </summary>
                  <Blocks blocks={sec.blocks} />
                </details>
              );
            })}
          </div>
        </>
      ) : null}

      <details
        className="rapport-artifact-source"
        open={sourceOuverte}
        onToggle={(e) => setSourceOuverte(e.currentTarget.open)}
      >
        <summary className="rapport-artifact-source-sum">
          <Chevron open={sourceOuverte} />
          <span>Source markdown</span>
          <span className="rapport-artifact-source-hint">brut moteur</span>
        </summary>
        <pre className="rapport-artifact-source-pre">{markdown}</pre>
      </details>
    </article>
  );
}
