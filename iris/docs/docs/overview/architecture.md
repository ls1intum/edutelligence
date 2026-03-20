---
title: Architecture
---

# Architecture

This page explains how Iris works at a conceptual level. For implementation details, see the [Developer Guide](/docs/developer/local-setup).

## High-Level Overview

Iris sits between Artemis and one or more Large Language Models (LLMs). The overall flow is:

1. **Artemis** sends a request to Iris via REST API (e.g., "the student asked a question in the exercise chat").
2. An **Iris pipeline** processes the request — selecting the right strategy, gathering context, and orchestrating LLM calls.
3. The **LLM** generates a response, potentially calling tools to gather additional information.
4. **Status callbacks** return results to Artemis incrementally, so students see a streaming response.

:::info Screenshot Needed
Architecture diagram — Artemis → Iris → LLM with tool calls and RAG
:::

## Pipeline System

Iris uses a **pipeline architecture** where each type of interaction has its own pipeline. Examples include:

- **Course Chat Pipeline** — general course-related questions
- **Exercise Chat Pipeline** — programming and text exercise support
- **Lecture Chat Pipeline** — questions about lecture content
- **Competency Generation Pipeline** — generating learning objectives
- **Ingestion Pipeline** — processing lecture slides and transcripts for RAG

Each pipeline defines which **LLM roles** it needs (e.g., a primary chat model, a tool-calling model, a reranking model) and can declare **dependencies** on other pipelines. This makes the system modular: you can swap models per role, and pipelines can reuse shared logic without tight coupling.

:::info Screenshot Needed
Pipeline execution flow diagram
:::

## Agent Execution Flow

For chat pipelines, Iris uses an **agent-based execution model**. Rather than making a single LLM call, the agent works iteratively:

1. **Receive** the conversation history and student context.
2. **Decide** whether additional information is needed (e.g., current code state, build errors, relevant lecture content).
3. **Call tools** to retrieve that information — code execution analysis, RAG retrieval, Artemis API queries, etc.
4. **Repeat** steps 2–3 until the agent has enough context.
5. **Generate** the final response with citations and appropriate scaffolding level.

This tool-calling loop allows Iris to adapt its behavior dynamically. A simple greeting might require zero tool calls, while a complex debugging question might involve fetching code, running retrieval, and checking test results before responding.

## Retrieval-Augmented Generation (RAG)

Iris uses RAG to ground responses in actual course content rather than relying solely on the LLM's training data. The RAG system has two phases:

### Ingestion (Offline)

1. **Collect** course materials — lecture slides, transcripts, FAQs.
2. **Chunk** the content into semantically meaningful segments.
3. **Embed** each chunk into a vector representation.
4. **Store** the vectors in Weaviate (the vector database).

### Retrieval (At Query Time)

1. **Rewrite** the student's query to improve retrieval quality.
2. **Retrieve** the most relevant chunks from Weaviate using vector similarity search.
3. **Rerank** the retrieved chunks to surface the best matches.
4. **Generate** a response that incorporates the retrieved content with transparent citations.

This ensures that when a student asks about a concept covered in lectures, Iris can point to the specific slide or transcript segment rather than producing a generic explanation.

## What's Next?

- [EduTelligence Ecosystem](./ecosystem) — how Iris connects to other services
- [Developer Guide](/docs/developer/local-setup) — deep dive into implementation details
