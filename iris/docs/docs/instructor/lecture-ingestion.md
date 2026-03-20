---
title: Lecture Ingestion
---

# Lecture Ingestion

Lecture ingestion sends your lecture materials to Iris's knowledge base, enabling it to answer student questions based on your actual course content rather than general knowledge alone.

## What Gets Ingested

When you ingest lectures, Iris processes:

- **Slide content** — text and structure from attachment units (PDFs, slide decks)
- **Video transcriptions** — if available, transcriptions from video units processed through Nebula

This content is indexed and made available to Iris so it can reference specific slides, concepts, and explanations from your lectures when responding to students.

## How to Ingest Lectures

There are two ways to send lecture content to Iris:

### Bulk Ingestion

On the **lecture management page**, use the **"Send All Lectures to Iris"** button to ingest all lecture units at once. This is the fastest way to set up Iris for a course with existing materials.

### Individual Ingestion

On an individual lecture unit that has attachments, use the **"Send Unit to Iris"** button to ingest just that specific unit. This is useful when you add or update a single lecture.

:::info Screenshot Needed
Lecture management page with Iris ingestion buttons
:::

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

## How Iris Uses Lecture Content

Once ingested, Iris draws on your lecture materials when answering student questions in the **Course Chat** and **Lecture Chat**. When Iris references a specific slide or lecture, it includes citation markers so students can trace the information back to the source material.

This is particularly valuable because it means Iris does not rely solely on its general training data. It can answer questions specific to your course — including topics covered in a unique way, institutional conventions, or domain-specific terminology you use in your lectures.

## Next Steps

- [FAQ Ingestion](./faq-ingestion) — add your course FAQs to Iris's knowledge base
- [Enabling Iris](./enabling-iris) — configure which Iris features are active
