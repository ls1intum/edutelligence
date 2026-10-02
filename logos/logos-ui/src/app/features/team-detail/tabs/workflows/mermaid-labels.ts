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
      // "…" is part of that label, not syntax.
      return line
        .split(/("[^"]*")/)
        .map((part, i) => (i % 2 === 1 ? part : quoteBareLabels(part)))
        .join('');
    })
    .join('\n');
}

function quoteBareLabels(text: string): string {
  return (
    text
      // A[text]  →  A["text"]   (not [( [[ [/ [\ shapes)
      .replace(
        /\b([A-Za-z0-9_]+)\[(?![(\[/\\])([^\]]*[^\]\s][^\]]*)\](?!\])/g,
        (_, id, label) => `${id}["${label.trim()}"]`,
      )
      // A{text}  →  A{"text"}   (not {{ hexagons)
      .replace(
        /\b([A-Za-z0-9_]+)\{(?!\{)([^}]+)\}(?!\})/g,
        (_, id, label) => `${id}{"${label.trim()}"}`,
      )
      // -->|text|  →  -->|"text"|
      .replace(/\|([^|]+)\|/g, (_, label) => `|"${label.trim()}"|`)
  );
}
