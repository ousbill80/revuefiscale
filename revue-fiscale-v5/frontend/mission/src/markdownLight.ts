/** Parser markdown léger DIY — headings, listes, tables, citation, inline.
 * Destiné au rendu Artefact (document livrable), pas au calcul fiscal.
 */

export type MdInline =
  | { kind: "text"; value: string }
  | { kind: "strong"; children: MdInline[] }
  | { kind: "em"; children: MdInline[] }
  | { kind: "code"; value: string }
  | { kind: "link"; href: string; children: MdInline[] };

export type MdListItem = {
  depth: number;
  inlines: MdInline[];
};

export type MdBlock =
  | { type: "h1" | "h2" | "h3"; text: string; inlines: MdInline[] }
  | { type: "p"; inlines: MdInline[] }
  | { type: "blockquote"; inlines: MdInline[] }
  | { type: "ul"; items: MdListItem[] }
  | { type: "table"; headers: MdInline[][]; rows: MdInline[][][]; aligns: Align[] }
  | { type: "hr" };

export type Align = "left" | "center" | "right";

export type MdSection = {
  title: string;
  titleInlines: MdInline[];
  blocks: MdBlock[];
};

export type MdDocument = {
  title: string | null;
  titleInlines: MdInline[];
  preamble: MdBlock[];
  sections: MdSection[];
};

/** Normalise le nombre de colonnes d’une ligne de table sur le header. */
function padCells(cells: string[], width: number): string[] {
  if (cells.length >= width) return cells.slice(0, width);
  return [...cells, ...Array(width - cells.length).fill("")];
}

const INLINE_RE =
  /(\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;

export function parseInline(text: string): MdInline[] {
  if (!text) return [];
  const out: MdInline[] = [];
  let last = 0;
  const re = new RegExp(INLINE_RE.source, "g");
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) {
      out.push({ kind: "text", value: text.slice(last, m.index) });
    }
    const tok = m[0];
    if (tok.startsWith("**") && tok.endsWith("**")) {
      out.push({
        kind: "strong",
        children: parseInline(tok.slice(2, -2)),
      });
    } else if (
      (tok.startsWith("*") && tok.endsWith("*")) ||
      (tok.startsWith("_") && tok.endsWith("_"))
    ) {
      out.push({
        kind: "em",
        children: parseInline(tok.slice(1, -1)),
      });
    } else if (tok.startsWith("`") && tok.endsWith("`")) {
      out.push({ kind: "code", value: tok.slice(1, -1) });
    } else if (tok.startsWith("[")) {
      const mid = tok.indexOf("](");
      const label = tok.slice(1, mid);
      const href = tok.slice(mid + 2, -1);
      out.push({ kind: "link", href, children: parseInline(label) });
    } else {
      out.push({ kind: "text", value: tok });
    }
    last = m.index + tok.length;
  }
  if (last < text.length) {
    out.push({ kind: "text", value: text.slice(last) });
  }
  return out.length ? out : [{ kind: "text", value: text }];
}

function isTableSep(line: string): boolean {
  return /^\|?[\s:|-]+\|[\s:|-]*\|?$/.test(line.trim()) && line.includes("-");
}

function splitPipeRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

function parseAligns(sep: string): Align[] {
  return splitPipeRow(sep).map((cell) => {
    const left = cell.startsWith(":");
    const right = cell.endsWith(":");
    if (left && right) return "center";
    if (right) return "right";
    return "left";
  });
}

function listDepth(line: string): number | null {
  const m = /^( *)([-*]|\d+\.)\s+/.exec(line);
  if (!m) return null;
  return Math.floor(m[1].length / 2);
}

function listContent(line: string): string {
  return line.replace(/^( *)([-*]|\d+\.)\s+/, "");
}

function headingLevel(line: string): 1 | 2 | 3 | null {
  if (/^###\s+/.test(line)) return 3;
  if (/^##\s+/.test(line)) return 2;
  if (/^#\s+/.test(line)) return 1;
  return null;
}

function parseBlocks(lines: string[]): MdBlock[] {
  const blocks: MdBlock[] = [];
  let i = 0;
  while (i < lines.length) {
    const raw = lines[i] ?? "";
    const line = raw.trimEnd();
    if (!line.trim()) {
      i += 1;
      continue;
    }

    if (/^---+$/.test(line.trim())) {
      blocks.push({ type: "hr" });
      i += 1;
      continue;
    }

    const hl = headingLevel(line.trim());
    if (hl) {
      const text = line.trim().replace(/^#{1,3}\s+/, "");
      blocks.push({
        type: (`h${hl}` as "h1" | "h2" | "h3"),
        text,
        inlines: parseInline(text),
      });
      i += 1;
      continue;
    }

    if (line.trim().startsWith(">")) {
      const parts: string[] = [];
      while (i < lines.length && (lines[i] ?? "").trim().startsWith(">")) {
        parts.push((lines[i] ?? "").trim().replace(/^>\s?/, ""));
        i += 1;
      }
      blocks.push({ type: "blockquote", inlines: parseInline(parts.join(" ")) });
      continue;
    }

    if (
      line.includes("|") &&
      i + 1 < lines.length &&
      isTableSep(lines[i + 1] ?? "")
    ) {
      const headerCells = splitPipeRow(line);
      const width = Math.max(1, headerCells.length);
      const headers = padCells(headerCells, width).map(parseInline);
      const alignRaw = parseAligns(lines[i + 1] ?? "");
      const aligns: Align[] = Array.from(
        { length: width },
        (_, idx) => alignRaw[idx] ?? "left",
      );
      i += 2;
      const rows: MdInline[][][] = [];
      while (i < lines.length && (lines[i] ?? "").includes("|")) {
        const rowLine = (lines[i] ?? "").trim();
        if (!rowLine || isTableSep(rowLine)) break;
        rows.push(padCells(splitPipeRow(rowLine), width).map(parseInline));
        i += 1;
      }
      blocks.push({ type: "table", headers, rows, aligns });
      continue;
    }

    if (listDepth(line) !== null) {
      const items: MdListItem[] = [];
      while (i < lines.length) {
        const cur = lines[i] ?? "";
        if (!cur.trim()) {
          // blank inside list ends it unless next is indented continuation — keep simple
          if (
            i + 1 < lines.length &&
            listDepth(lines[i + 1] ?? "") !== null
          ) {
            i += 1;
            continue;
          }
          break;
        }
        const d = listDepth(cur);
        if (d === null) break;
        items.push({ depth: d, inlines: parseInline(listContent(cur)) });
        i += 1;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    const para: string[] = [line.trim()];
    i += 1;
    while (i < lines.length) {
      const next = lines[i] ?? "";
      if (!next.trim()) break;
      if (headingLevel(next.trim()) !== null) break;
      if (next.trim().startsWith(">")) break;
      if (listDepth(next) !== null) break;
      if (
        next.includes("|") &&
        i + 1 < lines.length &&
        isTableSep(lines[i + 1] ?? "")
      ) {
        break;
      }
      para.push(next.trim());
      i += 1;
    }
    blocks.push({ type: "p", inlines: parseInline(para.join(" ")) });
  }
  return blocks;
}

/** Découpe un rapport markdown en titre + sections ## collapsibles. */
export function parseRapportDocument(md: string): MdDocument {
  const text = (md || "").replace(/\r\n/g, "\n").trim();
  if (!text) {
    return { title: null, titleInlines: [], preamble: [], sections: [] };
  }

  const lines = text.split("\n");
  let title: string | null = null;
  let titleInlines: MdInline[] = [];
  let start = 0;

  if (lines[0] && /^#\s+/.test(lines[0].trim()) && !/^##/.test(lines[0].trim())) {
    title = lines[0].trim().replace(/^#\s+/, "");
    titleInlines = parseInline(title);
    start = 1;
    while (start < lines.length && !(lines[start] ?? "").trim()) start += 1;
  }

  const rest = lines.slice(start).join("\n");
  const parts = rest.split(/^##\s+/m);

  if (parts.length <= 1) {
    return {
      title,
      titleInlines,
      preamble: parseBlocks(rest.split("\n")),
      sections: [],
    };
  }

  const preamble = (parts[0] ?? "").trim()
    ? parseBlocks((parts[0] ?? "").split("\n"))
    : [];

  const sections: MdSection[] = [];
  for (const block of parts.slice(1)) {
    const nl = block.indexOf("\n");
    const titleRaw = (nl === -1 ? block : block.slice(0, nl)).trim() || "Section";
    const body = (nl === -1 ? "" : block.slice(nl + 1)).trim();
    sections.push({
      title: titleRaw,
      titleInlines: parseInline(titleRaw),
      blocks: parseBlocks(body.split("\n")),
    });
  }

  return { title, titleInlines, preamble, sections };
}
