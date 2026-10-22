---
title: FAQ Ingestion
---

# FAQ Ingestion

FAQ ingestion lets you feed your course's frequently asked questions into Iris's knowledge base, so it can reference them when helping students.

## What FAQ Ingestion Does

Iris indexes the questions and answers you have curated in your course. This means:

- Students get **answers consistent with your official responses** rather than generic AI-generated explanations
- Common questions are handled accurately without requiring tutor intervention
- Iris can **cite your FAQs** when they are relevant to a student's question

## Setting Up FAQs

FAQs are managed through Artemis's built-in FAQ system for your course, and there is no separate step to make them available to Iris:

1. **Create or update your course FAQs** in Artemis — navigate to the FAQ management section in your course and add questions with their answers
2. **Accept them**: Artemis sends every accepted FAQ to Iris shortly after you save it, as long as Iris is enabled for your course; FAQs that are only proposed are not sent
3. **Verify the result**: ask Iris a question that one of your FAQs covers to confirm it references the correct answer

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
- **Delete outdated FAQs**: Iris stops using a deleted FAQ as well

Every change reaches Iris on its own. Artemis also compares the FAQs Iris holds with the accepted FAQs of your course every few minutes and sends whatever is missing or changed, so an FAQ saved while Iris was unavailable catches up without you doing anything.

:::info
FAQs are only sent to Iris while Iris is enabled for your course. After you enable Iris, the existing accepted FAQs follow within a few minutes.
:::

## How Iris Uses FAQs

When a student asks a question, Iris searches its knowledge base — which includes ingested FAQs — for relevant information. If a FAQ matches the student's question, Iris incorporates that answer into its response, potentially combining it with other sources like lecture content.

FAQs are particularly useful for:

- **Course logistics** — submission deadlines, tool setup, grading policies
- **Common misconceptions** — recurring conceptual errors that benefit from a consistent explanation
- **Exercise-specific clarifications** — common questions about specific assignments

## Next Steps

- [Lecture Ingestion](./lecture-ingestion): how your lecture materials reach Iris
- [Custom Instructions](./custom-instructions) — further shape how Iris responds in your course
