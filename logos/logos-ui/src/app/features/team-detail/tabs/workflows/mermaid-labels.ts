/**
 * Quote the node and edge labels of a Mermaid flowchart.
 *
 * Analyses write labels like `J[Session title LLM (deferred)]`; Mermaid reads
 * the parentheses as a shape and rejects the whole diagram. A quoted label is
 * plain text, so quoting every label the agent left bare makes those diagrams
 * render without changing what they say. Labels that are already quoted, and
 * the special shapes (`[(db)]`, `[[sub]]`, `[/io/]`), are left as written, as
 * is anything that is not a flowchart.
 */
export function quoteFlowchartLabels(source: string): string {
  const lines = source.split('\n');
  const header = lines.find((l) => l.trim() !== '')?.trim() ?? '';
  if (!/^(flowchart|graph)\b/.test(header)) return source;

  return lines
    .map((line) => {
      const trimmed = line.trim();
      if (
        trimmed === header ||
        trimmed.startsWith('%%') ||
        /^(classDef|class|style|linkStyle|click)\b/.test(trimmed)
      ) {
        return line;
      }
      // Only the text between quoted labels is rewritten: a `|` or `]` inside
      // "…" is part of that label, not syntax. Node labels go first, and the
      // line is split again before edge labels, so a `|` inside a node label
      // quoted by the first pass is left alone.
      const outsideQuotes = (text: string, rewrite: (part: string) => string) =>
        text
          .split(/("[^"]*")/)
          .map((part, i) => (i % 2 === 1 ? part : rewrite(part)))
          .join('');
      return outsideQuotes(outsideQuotes(line, quoteNodeLabels), quoteEdgeLabels);
    })
    .join('\n');
}

/**
 * A[text] → A["text"] and A{text} → A{"text"}. Scans to the matching close so
 * nested brackets stay inside the label (`A[arr[0] x]`). The special shapes
 * `[(…)]`, `[[…]]`, `[/…/]`, `[\…\]` and `{{…}}` are left as written.
 */
function quoteNodeLabels(text: string): string {
  const pairs: Record<string, string> = { '[': ']', '{': '}' };
  let out = '';
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    const close = pairs[ch];
    const prev = text[i - 1] ?? '';
    const next = text[i + 1] ?? '';
    const special = ch === '[' ? '([/\\'.includes(next) : next === '{';
    if (!close || !/[A-Za-z0-9_]/.test(prev) || special) {
      out += ch;
      i++;
      continue;
    }
    let depth = 0;
    let end = -1;
    for (let k = i; k < text.length; k++) {
      if (text[k] === ch) depth++;
      else if (text[k] === close && --depth === 0) {
        end = k;
        break;
      }
    }
    const label = end < 0 ? '' : text.slice(i + 1, end).trim();
    if (!label) {
      out += ch;
      i++;
      continue;
    }
    out += `${ch}"${label}"${close}`;
    i = end + 1;
  }
  return out;
}

function quoteEdgeLabels(text: string): string {
  // -->|text|  →  -->|"text"|
  return text.replace(/\|([^|]+)\|/g, (_, label) => `|"${label.trim()}"|`);
}
