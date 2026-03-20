---
title: Rate Limits
---

# Rate Limits

Rate limits control how many messages students can send to Iris within a given time window. They help ensure fair access across all students and manage computational resources.

## Why Rate Limits Exist

Iris uses language models that require significant computational resources. Without limits, a small number of students could consume a disproportionate share of capacity, degrading the experience for others. Rate limits:

- **Ensure fair access** — every student gets a reasonable allocation
- **Manage costs** — prevent runaway usage that could strain infrastructure
- **Encourage thoughtful use** — students learn to ask focused, well-formulated questions

## Configuring Rate Limits

Rate limits are set per course in the Iris settings on your **course overview page**. You can configure:

- **Message count** — how many messages a student can send (e.g., 20 messages)
- **Time window** — the period over which the count applies (e.g., 24 hours)

When a student reaches the limit, they cannot send additional messages until the time window resets.

:::tip
A limit of **20 messages per 24 hours** is a reasonable starting point for most courses. Monitor usage patterns and adjust if students consistently hit the limit during assignment deadlines.
:::

## What Students See

Students see a **message counter** in the chat header that shows how many messages they have remaining. This transparency helps students manage their usage throughout the day.

When the limit is reached, Iris displays a message explaining that the limit has been exceeded and when it will reset.

## Balancing Access and Resources

### Too Restrictive

If limits are too low, students may:

- Feel frustrated when they run out of messages mid-problem
- Avoid using Iris altogether to "save" messages for later
- Resort to external tools like ChatGPT, losing the pedagogical benefits of Iris's scaffolding approach

### Too Generous

If limits are too high (or absent), you risk:

- Excessive resource consumption
- Students relying on Iris instead of thinking independently
- Uneven distribution of resources across the course

### Adjusting During the Semester

Consider temporarily increasing limits during:

- **Assignment deadlines** — students need more help as submissions approach
- **Exam preparation periods** — increased study activity leads to more questions
- **New topic introductions** — students ask more questions when encountering unfamiliar material

:::warning
Changing rate limits takes effect immediately for all students in the course. There is no per-student override — the limit applies uniformly.
:::

## Next Steps

- [Enabling Iris](./enabling-iris) — configure which features are active
- [Variants](./variants) — choose the right model configuration for your course
