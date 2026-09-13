---
title: Instructional Support Level
---

# Instructional Support Level

The instructional support level decides how much Iris gives away when it helps a student. It is a single per-course setting with three values, and it is the most consequential pedagogical choice you make about Iris: the same student question draws a very different answer at each level.

## Where to Configure

The support level is set in the Iris settings on your **course overview page**, alongside [custom instructions](./custom-instructions) and the other Iris configuration.

The setting applies to the whole course. **Moderate** is the default, and a course that has never been configured behaves as if Moderate were chosen explicitly.

## The Three Levels

The settings page shows an example conversation at each level, using the same student question throughout, so you can compare the levels directly rather than in the abstract.

### Low

Iris responds only with high-level counter-questions that redirect students back to their own reasoning.

> **Student:** My sorting algorithm is not working. Can you help?
>
> **Iris:** What sorting algorithm are you implementing? What output do you get when you trace through your code with a small input like `[3, 1, 2]`?

**Best suited for** advanced courses where independent problem-solving is a core learning objective.

### Moderate

Iris asks guiding questions and provides targeted hints to help students work through problems. This is the default.

> **Student:** My sorting algorithm is not working. Can you help?
>
> **Iris:** Let us work through this step by step. Can you describe what your algorithm should do with the input `[3, 1, 4, 1, 5]`? Walk me through the first pass.

**Best suited for** courses where students have some experience but benefit from concrete nudges and contextual pointers.

### High

Iris provides step-by-step explanations with analogies and small code examples to illustrate concepts.

> **Student:** My sorting algorithm is not working. Can you help?
>
> **Iris:** The issue is in your inner loop condition `j <= arr.length`. Arrays are zero-indexed, so the last element is at `arr.length - 1`. Try changing it to `j < arr.length` and see if that resolves the IndexOutOfBoundsException.

**Best suited for** introductory courses where students are new to programming and need clear and approachable explanations.

## Choosing a Level

Reading the three examples against each other is the quickest way to decide. The same question — a sorting algorithm that does not work — draws a counter-question at Low, a walk-through invitation at Moderate, and at High the actual off-by-one error named with the fix.

The choice is about what the exercise is meant to teach, not about how capable your students are:

- If working the problem out unaided **is** the learning objective, Low protects it. A hint at the wrong moment removes the exercise.
- If students are stuck on incidental obstacles rather than the concept you are teaching — build errors, language syntax, tooling — High removes the obstacle without giving away the concept.
- Moderate is the sensible starting point when you are unsure. Adjust once you have seen how your students actually use Iris.

:::warning
The support level applies to the entire course. It cannot be set per exercise. If one exercise is meant to be worked out unaided while the rest of the course benefits from more help, say so in that exercise's problem statement — the support level cannot carve it out.
:::

## What the Level Does Not Change

The support level shapes how much Iris explains. It does not remove the limits that apply at every level.

:::info
Iris is globally restricted from providing complete solutions or full code blocks, regardless of your settings. High is not a way to turn Iris into a solution generator, and this restriction is not one you can relax.
:::

The support level is also not a content setting. What Iris knows about your course comes from your lecture materials and FAQs; what tone and emphasis it uses comes from your custom instructions. A High support level cannot compensate for material Iris has never seen.

## Support Level and Custom Instructions

The two settings work together and are worth keeping distinct:

| Setting                 | What it controls                                             |
| ----------------------- | ------------------------------------------------------------ |
| **Support level**       | How much Iris gives away — questions, hints, or explanations |
| **Custom instructions** | What Iris should emphasize, and in what style and language   |

Use custom instructions for things a general tutor cannot know — which language version your course uses, which of two conventions you teach, where to send students for background. Do not use them to restate the support level; if you want less help given away, lower the level rather than instructing Iris to hold back.

## Next Steps

- [Custom Instructions](./custom-instructions) — tailor Iris's emphasis and style to your course
- [Enabling Iris](./enabling-iris) — control which Iris features are active
- [Pedagogical Approach](./pedagogical-approach) — the reasoning behind Iris's scaffolding model
