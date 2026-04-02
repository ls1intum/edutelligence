---
title: EduTelligence Ecosystem
---

# EduTelligence Ecosystem

## What is EduTelligence?

EduTelligence is the suite of AI-enabled services that extend [Artemis](https://artemis.cit.tum.de). Artemis Intelligence blends in-process modules (running inside the Artemis server) with external EduTelligence services (running as standalone applications). Together, they provide AI-powered features across the entire learning workflow — from exercise feedback to lecture comprehension to competency tracking.

## Service Overview

| Service     | Description                                                                       | Status                          |
| ----------- | --------------------------------------------------------------------------------- | ------------------------------- |
| **Iris**    | AI virtual tutor — chat orchestrator, retrieval-augmented prompts, session memory | Live                            |
| **Athena**  | AI feedback service — automated exercise feedback generation                      | Live                            |
| **Nebula**  | Transcription service — speech-to-text for lecture media                          | Live                            |
| **Atlas**   | Competency-based learning — learner profiles, recommendations                     | Live (server-side)              |
| **Memiris** | Memory service — cross-session personalization for Iris                           | Live                            |
| **Logos**   | AI gateway — unified routing, metering, privacy controls                          | Implemented, not yet integrated |

## How Iris Connects to Other Services

### Artemis

Iris communicates with Artemis via REST API. Artemis sends chat requests, exercise context, and course metadata to Iris. Iris returns responses through status callbacks, enabling the streaming chat experience students see in the UI.

### Memiris

[Memiris](https://github.com/ls1intum/edutelligence) provides cross-session memory for Iris. It stores summarized interaction history so that Iris can personalize responses based on what a student has previously asked about and struggled with — even across different sessions.

### Nebula

[Nebula](https://github.com/ls1intum/edutelligence) processes lecture recordings into text transcripts. These transcripts are then ingested by Iris's RAG pipeline, making lecture content searchable and citable in chat responses.

### Logos

Logos is an AI gateway that will eventually handle unified model routing, usage metering, and privacy controls for all EduTelligence services. It is implemented but not yet integrated into the production workflow.

## Related Documentation

- [Athena Documentation](https://ls1intum.github.io/edutelligence/athena/) — automated feedback service
- [Atlas Documentation](https://ls1intum.github.io/edutelligence/atlas/) — competency-based learning
- [EduTelligence GitHub](https://github.com/ls1intum/edutelligence) — monorepo for all services
- [Artemis GitHub](https://github.com/ls1intum/Artemis) — the core learning platform
