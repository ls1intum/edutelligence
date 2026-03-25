---
title: What is Iris?
---

# What is Iris?

Iris is an AI-powered virtual tutor integrated directly into [Artemis](https://artemis.cit.tum.de), the open-source learning platform. It provides context-aware support for programming exercises, text exercises, and lecture content, helping students learn independently through guided hints and explanations rather than giving away solutions. Iris is also available as a course-wide assistant for general course-related questions.

![Meet Iris modal in Artemis](/img/screenshots/meet-iris-modal.png)

## Key Capabilities

### Calibrated Scaffolding

Iris delivers four tiers of support — from subtle hints to generalized examples — designed to preserve productive struggle. Instead of handing you the answer, it nudges you toward discovering it yourself.

### Context-Awareness

Iris is deeply integrated into Artemis. It automatically reads your code, build logs, test results, and course materials so that every response is grounded in what you are actually working on — no copy-pasting required.

### RAG-Grounded Responses

Responses are grounded in lecture slides, transcripts, and FAQs through retrieval-augmented generation (RAG). When Iris draws on course content, it provides transparent citations so you can verify and explore the source material.

## What Makes Iris Different from ChatGPT?

Unlike general-purpose chatbots that readily provide complete solutions, Iris is designed to _teach_. A 275-student randomized controlled trial found that Iris increased intrinsic motivation (+0.55 Cohen's d vs. No AI) while ChatGPT created a "comfort trap" — perceived as easier but without the same motivational benefits.

In short: ChatGPT solves the problem for you; Iris helps you solve it yourself.

## Who Uses Iris?

| Audience           | How They Use Iris                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------------------- |
| **Students**       | Get guided hints, explanations, and feedback while working on exercises or reviewing lectures           |
| **Instructors**    | Configure exercise-specific guidance, monitor chat interactions, and customize Iris behavior per course |
| **Administrators** | Deploy and manage the Iris service, configure LLM providers, and monitor system health                  |
| **Researchers**    | Study AI-assisted learning, analyze interaction patterns, and evaluate pedagogical effectiveness        |
| **Developers**     | Contribute new pipelines, tools, and integrations to the open-source project                            |

## Next Steps

- [Architecture](./architecture) — how Iris works under the hood
- [EduTelligence Ecosystem](./ecosystem) — where Iris fits in the broader platform
- [Student Guide](/docs/student/getting-started) — start using Iris as a student
