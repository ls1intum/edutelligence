import { describe, expect, it } from 'vitest';
import { quoteFlowchartLabels } from './mermaid-labels';

describe('quoteFlowchartLabels', () => {
  it('quotes labels whose parentheses Mermaid would read as a shape', () => {
    const src = [
      'flowchart TD',
      '  I --> J[Session title LLM (deferred)]',
      '  B -.parallel.-> L[MCQ generation thread (LLM)]',
      '  C{Agent tool loop: 1 LLM call per step}',
      '  C -->|final answer| E[post_agent_hook]',
    ].join('\n');
    expect(quoteFlowchartLabels(src)).toBe(
      [
        'flowchart TD',
        '  I --> J["Session title LLM (deferred)"]',
        '  B -.parallel.-> L["MCQ generation thread (LLM)"]',
        '  C{"Agent tool loop: 1 LLM call per step"}',
        '  C -->|"final answer"| E["post_agent_hook"]',
      ].join('\n'),
    );
  });

  it('leaves quoted labels, special shapes and directives alone', () => {
    const src = [
      'flowchart LR',
      '  A["already (quoted)"] --> B[(Weaviate)]',
      '  B --> C[[subroutine]]',
      '  C --> D{{hexagon}}',
      '  classDef hot fill:#f00',
    ].join('\n');
    expect(quoteFlowchartLabels(src)).toBe(src);
  });

  it('treats a pipe inside a quoted label as text, not as an edge label', () => {
    const src = 'flowchart TD\n  B --> C["webhooks\\n/lectures/ingest | metadata | delete"]';
    expect(quoteFlowchartLabels(src)).toBe(src);
  });

  it('does not touch other diagram types', () => {
    const src = 'sequenceDiagram\n  A->>B: call (x)';
    expect(quoteFlowchartLabels(src)).toBe(src);
  });
});
