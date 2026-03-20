---
title: Pedagogical Approach
---

# Pedagogical Approach

Iris is not a general-purpose chatbot. It is a pedagogical tool designed to help students learn more deeply by guiding them toward understanding rather than handing them solutions. This page explains the research-backed approach behind Iris and why it matters for your course.

## Philosophy: Scaffolding Over Solutions

The core principle is simple: **students learn more when they arrive at answers themselves**. Iris acts as a scaffold — providing temporary, calibrated support that helps students bridge the gap between what they know and what they need to learn, then stepping back as mastery develops.

This stands in contrast to tools like ChatGPT, which readily provide complete solutions. While that feels efficient in the moment, research shows it can undermine deeper learning.

## The 4-Tier Calibrated Scaffolding System

Iris uses a structured approach to assistance, escalating specificity only when needed:

### Tier 1: Subtle Hints

Iris draws the student's attention to a specific line of code, a relevant concept, or a particular section of the problem statement. The goal is to focus attention without revealing the answer.

> _"Take a closer look at what happens in your loop when the input list is empty."_

### Tier 2: Guiding Questions

If the hint is not enough, Iris asks questions that provoke reflection and self-discovery. These questions are designed to activate the student's existing knowledge and help them make connections.

> _"What value does your variable hold after the first iteration? Is that what you expect?"_

### Tier 3: High-Level Conceptual Feedback

When students need more direction, Iris provides strategic guidance about their approach — without revealing specific implementations. This helps students understand _what_ to change at a conceptual level.

> _"Your current approach processes elements one at a time. Consider whether a divide-and-conquer strategy might be more efficient here."_

### Tier 4: Generalized Examples

As a last resort, Iris illustrates the relevant pattern using an **analogous example** — a different problem that uses the same underlying concept. This keeps the target solution opaque while making the pattern visible.

> _"Imagine you are organizing books on a shelf by size. You could compare each book to every other book, or you could split the shelf in half and sort each half separately. Which approach does your algorithm resemble?"_

## Theoretical Foundations

Iris's design draws on established educational research:

### Cognitive Load Theory (CLT)

Students have limited working memory capacity. Iris manages cognitive load by providing the _minimum necessary_ assistance at each step, avoiding information overload that could hinder learning.

### Self-Determination Theory (SDT)

Motivation is strongest when students feel **autonomous** (making their own decisions), **competent** (capable of succeeding), and **connected** (supported by their learning environment). Iris's scaffolding preserves autonomy by guiding rather than dictating, builds competence through graduated challenges, and provides a supportive presence through relatedness.

### Zone of Proximal Development (ZPD)

The ZPD describes the space between what a student can do alone and what they can do with help. Iris operates precisely in this zone — providing support that is just beyond the student's current ability, making challenges achievable without making them trivial.

### Scaffolding Research

Effective scaffolding is **temporary** and **adaptive**. It provides structure when needed and withdraws as the student develops mastery. Iris's tiered approach embodies this: it starts with minimal intervention and escalates only when the student demonstrates they need more support.

## What the Research Shows

Iris's approach has been evaluated in a rigorous study with real students:

### Study Design

A **randomized controlled trial (RCT) with 275 students** compared Iris against ChatGPT and a no-AI control group during programming exercises. This is one of the largest controlled studies of AI tutoring in computer science education.

### Key Findings

- **Intrinsic motivation increased** — students using Iris showed significantly higher intrinsic motivation compared to the ChatGPT group (+0.55 Cohen's d, a medium effect size)
- **Frustration decreased** — Iris reduced frustration compared to the no-AI control group (-0.81 Cohen's d, a large effect size)
- **Performance variation preserved** — Iris maintained healthy variation in student performance, indicating that scaffolding balances support with challenge rather than homogenizing outcomes

### The "Comfort Trap"

An important finding: **ChatGPT creates a "comfort trap."** Students reported that ChatGPT was easier to use, but this ease did not translate into the same motivational benefits as Iris. The scaffolding approach requires more cognitive effort from students, which is precisely what drives deeper learning.

This is a key insight for instructors: the goal is not to minimize student effort, but to ensure that effort is productive and well-supported.

For full details on the research, methodology, and additional findings, see the [Research section](/docs/research/study-results).

## Why This Matters for Your Course

As an instructor, understanding Iris's pedagogical approach helps you:

- **Set expectations** with students — Iris will not give them direct answers, and that is by design
- **Write better [custom instructions](./custom-instructions)** — you can reinforce the scaffolding approach or adjust it for specific contexts
- **Communicate the value** — when students ask why Iris "won't just tell me the answer," you can explain the research-backed reasoning
- **Trust the process** — even when students initially find scaffolding more challenging than getting direct solutions, the evidence shows it leads to better learning outcomes

:::tip
Consider sharing the basics of this approach with your students at the start of the course. When students understand _why_ Iris guides rather than tells, they engage with it more productively. The [How Iris Helps You Learn](/docs/student/how-iris-helps) page is designed for exactly this purpose.
:::

## Next Steps

- [Custom Instructions](./custom-instructions) — shape Iris's behavior for your specific course
- [Enabling Iris](./enabling-iris) — configure which features are active
- [Research: Study Results](/docs/research/study-results) — detailed findings from the evaluation study
