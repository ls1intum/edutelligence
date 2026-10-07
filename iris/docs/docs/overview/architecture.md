---
title: Architecture
---

# Architecture

This page explains how Iris works at a conceptual level. For implementation details, see the [Developer Guide](/docs/developer/local-setup).

## High-Level Overview

Iris sits between Artemis and one or more Large Language Models (LLMs). The overall flow is:

1. **Artemis** sends a request to Iris via REST API (e.g., "the student asked a question, and the chat is currently about this programming exercise").
2. An **Iris pipeline** processes the request — selecting the right strategy, gathering context, and orchestrating LLM calls.
3. The **LLM** generates a response, potentially calling tools to gather additional information.
4. **Status callbacks** return results to Artemis incrementally, so students see a streaming response.

<!-- TODO: Diagram needed — Artemis → Iris → LLM with tool calls and RAG -->

## Pipeline System

Iris uses a **pipeline architecture** where each kind of work has its own pipeline:

- **Chat Pipeline** — every student chat, whatever it is currently about
- **Competency Generation Pipeline** — generating learning objectives
- **Ingestion Pipeline** — processing lecture slides and transcripts for RAG
- **Tutor Suggestion Pipeline** — response suggestions for tutors in discussion threads

Each pipeline defines which **LLM roles** it needs (e.g., a primary chat model, a tool-calling model, a reranking model) and can declare **dependencies** on other pipelines. This makes the system modular: you can swap models per role, and pipelines can reuse shared logic without tight coupling.

<!-- TODO: Diagram needed — Pipeline execution flow -->

### One Pipeline, Several Contexts

A single chat pipeline serves every student chat, whether the student is working through a lecture, a programming exercise, a text exercise, or the course as a whole. A chat carries an **active context** for the chat: the course, a lecture or an exercise. The context travels with each request and decides three things — which parts of the system prompt render, which tools the agent is offered, and how retrieval is scoped. Everything else is shared.

Splitting this along contexts instead would mean one pipeline per context, each duplicating the agent loop, the retrieval wiring and the citation handling, and none of them able to hand a conversation to another. Keeping the context as data means a chat can change what it is about without losing what came before it, which is what the next section describes.

## Context Switching

The active context of a chat is not fixed for its lifetime. It changes in two ways:

1. **The student changes it.** The student picks a lecture or an exercise in the chat UI, or opens Iris from a lecture or exercise page. Artemis validates the target and applies it.
2. **Iris changes it.** The agent notices that the question is about a different exercise or lecture, looks up which one, and requests the switch through a tool. The switch travels back to Artemis with the answer, and Artemis validates and applies it.

Both paths end at the same place. Artemis records the transition as a marker message in the chat history, so the history itself carries the information that the topic changed at this point. Pyris reads those markers on the next request: earlier messages are understood as being about the previous context, and the chat title reflects the current one rather than the one the chat started with.

Keeping the switch on the Artemis side matters for authorization. Pyris proposes, Artemis decides — it re-checks that the student may access the target exercise or lecture before it changes anything, so a mistaken or manipulated proposal cannot widen what a student can reach.

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
