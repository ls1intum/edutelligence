---
title: FAQ Ingestion
---

# FAQ Ingestion

FAQ ingestion lets you feed your course's frequently asked questions into Iris's knowledge base, so it can reference them when helping students.

## What FAQ Ingestion Does

When you ingest course FAQs, Iris indexes the questions and answers you have curated. This means:

- Students get **answers consistent with your official responses** rather than generic AI-generated explanations
- Common questions are handled accurately without requiring tutor intervention
- Iris can **cite your FAQs** when they are relevant to a student's question

## Setting Up FAQs

FAQs are managed through Artemis's built-in FAQ system for your course. To make them available to Iris:

1. **Create or update your course FAQs** in Artemis — navigate to the FAQ management section in your course and add questions with their answers
2. **Ingest the FAQs into Iris** — use the ingestion button on the FAQ management page to send your FAQ content to Iris's knowledge base (similar to [lecture ingestion](./lecture-ingestion))
3. **Verify ingestion** — after ingestion, test by asking Iris a question that one of your FAQs covers to confirm it references the correct answer

## What Makes a Good FAQ

Effective FAQs for Iris should:

- **Cover genuinely common questions** — focus on questions students actually ask, not hypothetical ones
- **Provide clear, complete answers** — Iris will reference these directly, so they should be self-contained
- **Use consistent terminology** — match the language you use in lectures and exercises
- **Address both conceptual and practical questions** — "What is polymorphism?" as well as "How do I submit my exercise?"

:::tip
Review your course discussion forum for recurring questions. These are ideal candidates for FAQs that Iris can then handle automatically.
:::

## Keeping FAQs Up to Date

As your course evolves, your FAQs should too:

- **Add new FAQs** as new common questions emerge during the semester
- **Update existing answers** when course policies or content change
- **Re-ingest after changes** so Iris uses the latest version of your FAQs

:::warning
If you update FAQs in Artemis but do not re-ingest them, Iris will continue using the old versions. Always re-ingest after making changes.
:::

## How Iris Uses FAQs

When a student asks a question in the Course Chat or other Iris features, Iris searches its knowledge base — which includes ingested FAQs — for relevant information. If a FAQ matches the student's question, Iris incorporates that answer into its response, potentially combining it with other sources like lecture content.

FAQs are particularly useful for:

- **Course logistics** — submission deadlines, tool setup, grading policies
- **Common misconceptions** — recurring conceptual errors that benefit from a consistent explanation
- **Exercise-specific clarifications** — common questions about specific assignments

## Next Steps

- [Lecture Ingestion](./lecture-ingestion) — add lecture materials to Iris's knowledge base
- [Custom Instructions](./custom-instructions) — further shape how Iris responds in your course
