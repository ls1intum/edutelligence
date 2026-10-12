---
title: Lecture Ingestion
---

# Lecture Ingestion

Lecture ingestion sends your lecture materials to Iris's knowledge base, enabling it to answer student questions based on your actual course content rather than general knowledge alone.

## What Gets Ingested

When you ingest lectures, Iris processes:

- **Slide content** — text and structure from attachment units (PDFs, slide decks)
- **Video transcriptions** — if available, transcriptions from video units

This content is indexed and made available to Iris so it can reference specific slides, concepts, and explanations from your lectures when responding to students.

## How to Ingest Lectures

There are two ways to send lecture content to Iris:

### Bulk Ingestion

On the **lecture management page**, use the **"Send All Lectures to Iris"** button to ingest all lecture units at once. This is the fastest way to set up Iris for a course with existing materials.

### Individual Ingestion

On an individual lecture unit that has attachments, use the **"Send Unit to Iris"** button to ingest just that specific unit. This is useful when you add or update a single lecture.

<!-- TODO: Screenshot needed — Lecture management page -->

## Prerequisites

Before ingesting, ensure that:

- **Lectures have attachment units** — Iris can only ingest content from lecture units that have attached files (slides, PDFs). Lectures without attachments have nothing to ingest.
- **Iris is enabled** for your course — see [Enabling Iris](./enabling-iris)

## When to Re-Ingest

You should re-ingest lectures when:

- **You update slide content** — Iris uses the version it last ingested, so updates require re-ingestion
- **You add new lectures** — newly added lectures are not automatically ingested
- **You add transcriptions** — if video transcriptions become available after the initial ingestion

:::tip
Make it a habit to re-ingest after updating lecture materials. A quick click on "Send Unit to Iris" ensures students always get answers based on the latest version of your content.
:::

### Re-Ingesting While a Unit Is Still Processing

You do not have to wait for a running ingestion to finish before sending the same unit again. Iris starts the new run immediately and **supersedes** the one in progress: the older run stops at its next checkpoint and reports nothing, so the status you see belongs to the newest request.

This is what makes correcting a mistake cheap. If you replace the slides again, or fix a video link while the first version is still being transcribed, the obsolete run does not finish and cannot overwrite the result of the one you actually want.

A superseded run stops only at a point where what is stored for the unit is consistent, so students never get answers from a half-written unit while the new run is still working.

## How Iris Uses Lecture Content

Once ingested, Iris draws on your lecture materials when answering student questions. A chat set to a specific lecture retrieves from that lecture, and a chat at course level retrieves across all of them. When Iris uses a slide or a passage from a recording, it attaches a source chip to the sentence it supports, and a student clicking that chip lands on the cited page or video moment.

This is particularly valuable because it means Iris does not rely solely on its general training data. It can answer questions specific to your course — including topics covered in a unique way, institutional conventions, or domain-specific terminology you use in your lectures.

### Slide Page Numbers in Answers

Iris reads the number **printed on each slide** during ingestion and refers to slides by that number, not by their position in the PDF. For a deck with a title or agenda slide in front, the two differ, and the printed number is the one your students see.

A slide that carries no legible number is described without one ("the slide on quicksort"). Where the printed numbering is regular, Iris infers the number of such a slide from its neighbours, so a single unnumbered or misprinted slide in an otherwise consistent deck still gets named correctly.

### What Replacing Slides Does to Older Citations

Replacing slides or a video does not retroactively change answers students have already received. A citation or a position from an older answer still opens the lecture unit, but it does not jump to the old page or moment, because that position may now refer to different content. Once the new material has finished processing, a fresh question produces citations into it.

## Next Steps

- [FAQ Ingestion](./faq-ingestion) — add your course FAQs to Iris's knowledge base
- [Enabling Iris](./enabling-iris) — configure which Iris features are active
