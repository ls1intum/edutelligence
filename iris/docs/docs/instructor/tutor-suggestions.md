---
title: Tutor Suggestions
---

# Tutor Suggestions

Tutor Suggestions provide AI-generated response guidance for tutors when they open discussion threads. Rather than replacing tutor responses, they help tutors craft pedagogically meaningful answers more efficiently.

## How Tutor Suggestions Work

When a tutor opens a discussion post, Iris analyzes the thread context — including the student's question, any prior replies, and related course content — and generates suggested response directions. These are not canned responses; they are tailored guidance that helps the tutor formulate a helpful reply.

<!-- TODO: Screenshot needed — Tutor suggestion in a discussion thread -->

## What Tutors See

### Suggestion Panel

When a tutor opens a discussion thread, Iris suggestions appear in a dedicated panel within the thread view. A **status bar** indicates when suggestions are being generated.

### Integrated Iris Chat

Below the suggestions, tutors can start a **direct conversation with Iris** to explore the topic further. This is useful for:

- Asking follow-up questions like _"What misconception might the student have?"_
- Getting deeper context on the relevant course material
- Exploring different angles for explaining a concept

Iris may **automatically regenerate suggestions** based on the conversation, refining its guidance as the tutor's understanding of the student's issue evolves.

### Suggestion History

A **"View history"** button allows tutors to review previous suggestions generated for the same thread. This is helpful when revisiting a discussion or when multiple tutors are involved.

## Pedagogical Value

Tutor Suggestions are designed to support — not replace — the tutor's judgment. They:

- **Guide toward scaffolding** — suggestions encourage tutors to ask guiding questions rather than provide direct answers
- **Surface relevant course content** — Iris draws on ingested lectures and FAQs to ground suggestions in your actual materials
- **Save preparation time** — tutors spend less time researching the topic and more time crafting a thoughtful response

## Enabling Tutor Suggestions

Tutor Suggestions must be enabled at two levels:

1. **System-level** — your administrator must enable the feature for your Artemis instance
2. **Course-level** — you must enable it in the Iris settings on your course overview page (see [Enabling Iris](./enabling-iris))

:::warning
Tutor Suggestions are disabled by default and require admin activation. If you do not see the option in your course Iris settings, contact your system administrator.
:::

## Who Can See Suggestions

Tutor Suggestions are only visible to users with the **tutor role** (or higher). Students never see the suggestions — they only see the tutor's actual reply. This ensures that the AI assistance remains a behind-the-scenes tool for your teaching team.

## Best Practices for Tutors

- **Use suggestions as a starting point**, not a final answer. The tutor's own judgment and knowledge of the student's situation should always shape the response.
- **Engage with the Iris chat** when the suggestion is not quite right. A short follow-up conversation often produces more targeted guidance.
- **Review the history** when picking up a thread that another tutor started, to see what guidance was previously generated.

## Next Steps

- [Enabling Iris](./enabling-iris) — configure Iris features for your course
- [Pedagogical Approach](./pedagogical-approach) — understand the scaffolding philosophy behind Iris
- [FAQ Ingestion](./faq-ingestion) — ensure Iris has access to your course's common questions
