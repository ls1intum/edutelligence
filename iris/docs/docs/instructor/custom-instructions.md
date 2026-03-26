---
title: Custom Instructions
---

# Custom Instructions

Custom instructions let you shape how Iris interacts with students in your course. They are injected into Iris's system prompts, giving you direct influence over its tone, focus areas, and pedagogical emphasis.

## What Custom Instructions Do

When you provide custom instructions, Iris incorporates them into every response it generates for your course. This means you can:

- Set expectations about your students' background
- Direct Iris to emphasize certain topics or approaches
- Adjust language and communication style
- Align Iris with your course's specific learning objectives

## Where to Configure

Custom instructions are set in the Iris settings on your **course overview page**, alongside the feature toggles and other Iris configuration options.

## Writing Effective Instructions

### Be Specific About Your Students

Tell Iris who it is talking to. The more context you provide, the better Iris can calibrate its responses.

| Vague            | Specific                                                                             |
| ---------------- | ------------------------------------------------------------------------------------ |
| "Be helpful"     | "Students are first-year CS students with no prior programming experience"           |
| "Keep it simple" | "Students have completed introductory Java but have not yet covered data structures" |

### Focus on What Matters

Direct Iris toward the skills and concepts that matter most in your course.

**Examples:**

- _"Emphasize testing and code quality. When reviewing student code, always ask whether they have considered edge cases."_
- _"Focus on functional programming concepts. Encourage students to use higher-order functions and avoid mutable state."_
- _"This is a software engineering course. When students ask for help with code, also address design principles like separation of concerns."_

### Set Language Preferences

If your course is taught in a language other than English, let Iris know.

**Examples:**

- _"Respond in German when students write in German."_
- _"Use English for technical terms but respond in French for explanations."_

### Align with Course Philosophy

If you have specific pedagogical goals, express them.

**Examples:**

- _"Never provide complete solutions. Always guide students to find the answer themselves."_
- _"When students ask about algorithm complexity, always encourage them to derive the Big-O analysis step by step."_
- _"Encourage pair programming and collaborative problem-solving."_

## Best Practices

:::tip

- **Keep instructions concise.** A few well-chosen sentences are more effective than a wall of text. Aim for clarity over completeness.
- **Test your instructions.** After setting them, try a few conversations as if you were a student to verify that Iris responds the way you expect.
- **Update throughout the semester.** As your course progresses, refine instructions to match the current topic or assignment focus.
  :::

## Things to Avoid

- **Contradicting Iris's core design.** Asking Iris to "always provide the full solution" conflicts with its scaffolding approach and will produce inconsistent results.
- **Overly long instructions.** Very long custom instructions may dilute the effect of individual points. Prioritize the most important guidance.
- **Instructions about things Iris cannot control.** Iris cannot change grading, deadlines, or Artemis platform behavior.

## Example: Complete Custom Instruction

Here is an example of a well-crafted custom instruction for an introductory Java course:

> _Students are first-year computer science students taking their first programming course. They have no prior experience with Java or programming in general. Focus on fundamental concepts like variables, loops, and conditionals before addressing more advanced topics. When students make errors, explain the underlying concept rather than just pointing out the syntax mistake. Respond in German when students write in German. Encourage students to test their code with small examples before submitting._

## Next Steps

- [Variants](./variants) — choose the model configuration for your course
- [Pedagogical Approach](./pedagogical-approach) — understand the scaffolding philosophy behind Iris
