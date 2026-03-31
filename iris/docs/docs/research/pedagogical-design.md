---
title: Pedagogical Design
---

# Pedagogical Design

Iris is designed around three architectural pillars described in [Bassner et al. (2026)](./publications.md#randomized-controlled-trial) that together create a tutoring system grounded in established learning theories. This page summarizes the pedagogical foundations and how they translate into system behavior.

## Three Architectural Pillars

### 1. Educational Scaffolding via Calibrated Hints

Rather than providing direct answers, Iris uses a four-tier hint system that progressively reveals information while preserving the learner's opportunity for self-discovery:

| Tier                               | Strategy                                                          | Example Behavior                                                                                                                                          |
| ---------------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Subtle hints**                   | Focus attention on salient code lines                             | "Take a closer look at what happens on line 42 when the loop variable is incremented."                                                                    |
| **Guiding questions**              | Provoke reflection and self-discovery                             | "What do you think the return value should be when the input list is empty?"                                                                              |
| **High-level conceptual feedback** | Strategic guidance without revealing implementations              | "This problem requires you to think about how threads share memory. Consider what happens when two threads write to the same variable simultaneously."    |
| **Generalized examples**           | Illustrate analogous patterns, keeping the target solution opaque | "Imagine you have a bank account where two people try to withdraw money at the same time. How would you prevent them from both reading the same balance?" |

A built-in **self-check mechanism** evaluates generated responses against pedagogical constraints before they are sent to the student. This mechanism is designed to prevent inadvertent solution disclosure --- if a response is deemed too revealing, it is regenerated at a less specific tier.

### 2. Context-Aware Dynamic Agent Architecture

Iris integrates deeply with the [Artemis](https://github.com/ls1intum/Artemis) learning platform to automatically retrieve relevant context for each student interaction:

- **Exercise specifications** (problem statement, template code, solution structure)
- **Student submission history** (current code, previous attempts, build feedback)
- **Course materials** (lecture slides, reference materials)

This context awareness means students do not need to manually copy-paste code or explain their exercise setup. The tutor already knows what the student is working on, what they have tried, and what the expected solution looks like --- enabling it to provide targeted guidance rather than generic advice.

### 3. Multimodal RAG Pipeline

A Retrieval-Augmented Generation (RAG) pipeline grounds Iris's responses in authoritative course artifacts rather than relying solely on the LLM's parametric knowledge. This helps ensure that guidance aligns with the specific terminology, notation, and conventions used in the course.

## Theoretical Foundations

### Cognitive Load Theory (CLT)

CLT distinguishes three types of cognitive load during learning:

- **Intrinsic load**: inherent difficulty of the material itself
- **Germane load**: cognitive effort devoted to constructing mental models (the "productive struggle")
- **Extraneous load**: unnecessary cognitive burden from poor instructional design

Iris aims to **reduce extraneous load** (e.g., by eliminating time spent searching for relevant documentation or deciphering cryptic error messages) **without eliminating germane load** (the effortful processing that produces durable learning). The hint-based approach is specifically designed to preserve productive cognitive engagement rather than short-circuit it with direct answers.

### Self-Determination Theory (SDT)

SDT identifies three basic psychological needs that support intrinsic motivation:

- **Autonomy**: feeling in control of one's own learning process
- **Competence**: experiencing a sense of mastery and progress
- **Relatedness**: feeling connected to others and supported

By offering graduated hints rather than complete solutions, Iris preserves learner **autonomy** --- students remain the primary agents in solving their exercises. Successful resolution after receiving hints can strengthen perceived **competence**. The non-judgmental interaction style (92% of surveyed students reported feeling comfortable asking questions) supports **relatedness** by reducing social evaluation anxiety.

### Zone of Proximal Development (ZPD)

Vygotsky's ZPD describes the gap between what a learner can accomplish independently and what they can accomplish with assistance. Effective scaffolding operates within this zone and should be:

- **Contingent**: adapted to the learner's current state rather than generic
- **Graduated**: starting with minimal assistance and increasing only as needed
- **Faded**: withdrawn as the learner gains competence

Iris's four-tier hint system maps onto these principles: initial interactions begin with subtle hints (minimal assistance), escalating to more explicit guidance only when the student continues to struggle. Context awareness enables contingent support --- the system can tailor its hints to the specific code the student has written rather than offering one-size-fits-all advice.

## Design Trade-offs

:::note Important
The pedagogical design deliberately trades short-term task efficiency for long-term learning outcomes. In the C&E:AI 2026 RCT, Iris users achieved lower exercise scores than ChatGPT users (_d_ = 0.38), but equivalent learning gains --- suggesting that the scaffolding approach maintains the cognitive engagement necessary for durable learning.
:::

The [study results](./study-results.md) provide empirical evidence for how these design choices affect student performance, learning, motivation, and frustration in practice.
