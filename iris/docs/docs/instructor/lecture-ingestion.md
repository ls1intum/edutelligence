---
title: Lecture Ingestion
---

# Lecture Ingestion

Lecture ingestion sends your lecture materials to Iris's knowledge base, enabling it to answer student questions based on your actual course content rather than general knowledge alone.

## What Gets Ingested

For each attachment video unit, Iris processes:

- **Slide content**: text and structure from the unit's PDF, including what a vision model reads from figures
- **Video transcripts**: Iris transcribes the unit's video and aligns the transcript with the slides

This content is indexed and made available to Iris so it can reference specific slides, concepts, and explanations from your lectures when responding to students.

## When Ingestion Happens

There is nothing to trigger. Artemis sends a lecture unit to Iris on its own whenever its content changes:

- when you create an attachment video unit with a PDF, or with a video from YouTube or TUM-Live;
- when you replace its file, which uploads a new version; and
- when you change its video link.

A file whose content is unchanged, such as a deck saved again from the slide editor, keeps its version and is not processed again. Artemis also checks the index regularly and sends a unit again when its content is missing, incomplete or outdated, for example after Iris was unavailable. You do not have to watch for that either.

A unit is processed only if Iris can read something from it: a PDF, or a video it can transcribe. A unit that only links a video on another site is marked as not indexed, and is processed automatically once it gets a PDF or a supported video.

Ingestion does not depend on whether Iris is enabled in your course. The processed content is also used by the Artemis global search, which every student who allowed AI can use. The chat only uses it while Iris is enabled; see [Enabling Iris](./enabling-iris).

## Following the Progress

On the **lecture management page**, every attachment video unit shows a status badge: **Awaiting Processing**, then the current step, such as **Transcribing** for a video or **Reading slides** and **Indexing**, and finally **Indexed**. Transcribing a video takes noticeably longer than processing slides.

<!-- TODO: Screenshot needed: status badges on the lecture management page, one unit Indexed and one in progress -->

If processing fails, the badge shows **Processing Failed** with the reason, for example a video that is private or too long, or a PDF without readable pages. Artemis retries transient errors on its own. After you have fixed the cause, **Retry processing** next to the unit starts it again.

### Changing a Unit While It Is Still Processing

You do not have to wait for a running ingestion to finish before changing the same unit again. Iris **supersedes** the run in progress: the older run stops at its next checkpoint and sends no final success or failure status. It may already have sent progress updates before it was superseded.

This is what makes correcting a mistake cheap. If you replace the slides again, or fix a video link while the first version is still being transcribed, the obsolete run does not finish and cannot overwrite the result of the one you actually want.

Iris stops a superseded run at a checkpoint and guards the write phases of the current run. Before reporting ingestion as finished, it verifies the stored content. During processing, old and new entries can briefly coexist, so wait for ingestion to finish before relying on answers about the updated material.

## How Iris Uses Lecture Content

Once ingested, Iris draws on your lecture materials when answering student questions. A chat set to a specific lecture retrieves from that lecture, and a chat at course level retrieves across all of them. When Iris uses a slide or a passage from a recording, it attaches a citation marker to the sentence it supports, and a student clicking that marker lands on the cited page or video moment.

This is particularly valuable because it means Iris does not rely solely on its general training data. It can answer questions specific to your course — including topics covered in a unique way, institutional conventions, or domain-specific terminology you use in your lectures.

### Slide Page Numbers in Answers

Iris reads the number **printed on each slide** during ingestion and refers to slides by that number, not by their position in the PDF. For a deck with a title or agenda slide in front, the two differ, and the printed number is the one your students see.

Where the printed numbering is regular, Iris infers the number of an unreadable slide from its neighbours, so a single unnumbered or misprinted slide in an otherwise consistent deck still gets named correctly.

Two cases fall outside that:

- **No number anywhere in the deck.** If Iris cannot read a single page number — unnumbered slides throughout, or a scan it cannot make out — it falls back to counting PDF pages and names slides by that count. For a deck with a title slide in front, those numbers are one ahead of what students would have read off the slides, had there been numbers.
- **A slide whose number stays unknown.** Where the rest of the deck is numbered but one slide's number cannot be resolved — typically front matter before printed page 1 — Iris describes it without a number ("the slide on quicksort") rather than guessing.

Adding page numbers to your slides is therefore the surest way to get Iris to refer to them the way your students do.

### What Replacing Slides Does to Older Citations

Replacing slides or a video does not retroactively change answers students have already received. A citation or a position from an older answer still opens the lecture unit, but it does not jump to the old page or moment, because that position may now refer to different content. Once the new material has finished processing, a fresh question produces citations into it.

## Next Steps

- [FAQ Ingestion](./faq-ingestion) — add your course FAQs to Iris's knowledge base
- [Enabling Iris](./enabling-iris) — configure which Iris features are active
