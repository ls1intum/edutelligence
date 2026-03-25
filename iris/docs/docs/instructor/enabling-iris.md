---
title: Enabling Iris
---

# Enabling Iris

Iris is configured on a per-course basis. As an instructor, you control which Iris features are available to your students and how they behave.

## Accessing Iris Settings

Iris settings are found on the **course overview page**, not in the general course settings. Look for the Iris configuration section in the course management area.

<!-- TODO: Screenshot needed — Iris course settings panel in Artemis showing feature toggles -->

:::warning
If you do not see Iris settings on your course overview page, your institution's administrator may not have enabled Iris at the system level. Contact your admin to request activation.
:::

## Enabling and Disabling Features

Iris offers several features that can be toggled independently:

| Feature                | What It Does                                                           |
| ---------------------- | ---------------------------------------------------------------------- |
| **Exercise Chat**      | Students get context-aware help while working on programming exercises |
| **Text Exercise Chat** | Guidance for written and text-based exercises                          |
| **Course Chat**        | General-purpose assistant for course-wide questions                    |
| **Lecture Chat**       | Questions about specific lecture materials                             |
| **Tutor Suggestions**  | AI-generated response suggestions for tutors in discussion threads     |

Each feature has its own toggle. You can enable the features that make sense for your course and disable the rest. For example, you might enable Exercise Chat and Course Chat but leave Lecture Chat disabled until you have ingested your lecture materials.

## What Students See

When Iris is enabled for a course:

- A **floating chat icon** appears in relevant contexts (exercise pages, lecture views).
- The **Course Chat** option appears in the course sidebar.
- Students who have not yet chosen an AI experience (Cloud, On-Premise, or No AI) are prompted to make a selection on their first encounter.

When Iris is disabled, these elements are hidden entirely. Students will not see any Iris-related UI in your course.

:::tip
Enable Iris early in the semester so students can get familiar with it from the start. You can always adjust which specific features are active as the course progresses.
:::

## Impact on the Student Experience

Iris is designed as a pedagogical tool, not a solution generator. When students interact with Iris, it:

- **Guides** them toward understanding rather than providing direct answers
- **Uses calibrated scaffolding** — starting with subtle hints and only increasing specificity when needed
- **Respects your course context** — any [custom instructions](./custom-instructions) you provide shape how Iris responds

For more on the pedagogical philosophy, see [Pedagogical Approach](./pedagogical-approach).

## Next Steps

- [Custom Instructions](./custom-instructions) — tailor Iris's behavior to your course
- [Variants](./variants) — choose between different model configurations
- [Rate Limits](./rate-limits) — manage how many messages students can send
- [Lecture Ingestion](./lecture-ingestion) — feed your lecture materials into Iris
