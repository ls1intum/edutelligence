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

## Course Settings

Iris chat is enabled or disabled for your course as a whole. These are the settings you control:

| Setting                 | What It Does                                                                                            |
| ----------------------- | ------------------------------------------------------------------------------------------------------- |
| **Enabled**             | Whether Iris appears in your course at all                                                              |
| **Custom Instructions** | Your own additions to how Iris behaves in this course. See [Custom Instructions](./custom-instructions) |
| **Variant**             | Which model configuration Iris uses. See [Variants](./variants)                                         |
| **Support Level**       | How much help Iris is allowed to give                                                                   |
| **Rate Limit**          | How many messages a student may send per time period. See [Rate Limits](./rate-limits)                  |

## What Students See

When Iris is enabled for a course:

- **Iris** appears in the course sidebar.
- A **floating chat icon** appears on exercise pages and lecture views. Opening it there pre-selects that exercise or lecture as the context, which students can change or remove.
- Students who have not yet chosen an AI experience (Cloud, On-Premise, or No AI) are prompted to make a selection on their first encounter.

When Iris is disabled, these elements are hidden entirely. Students will not see any Iris-related UI in your course.

:::info
Students can point the chat at any lecture or exercise in your course, and Iris moves the chat itself when a student asks about a different one.
:::

:::tip
Enable Iris early in the semester so students can get familiar with it from the start. You can always adjust these settings as the course progresses.
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
