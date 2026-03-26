---
title: Variants
---

# Variants

Iris supports different model variants, allowing you to choose between quality, speed, and cost tradeoffs for your course.

## What Are Variants?

Each Iris feature is powered by a pipeline that uses one or more language models. A **variant** defines which specific models are used for each role in the pipeline. Different variants offer different balances of response quality, speed, and computational cost.

In practice, instructors see two options:

| Variant      | Models                      | Best For                                             |
| ------------ | --------------------------- | ---------------------------------------------------- |
| **Default**  | Smaller, faster models      | Day-to-day use, large courses, quick responses       |
| **Advanced** | More capable, larger models | Complex questions, nuanced guidance, smaller courses |

## How Variants Affect the Student Experience

### Default Variant

- **Faster responses** — students spend less time waiting
- **Good for most interactions** — handles typical questions about exercises, concepts, and course material well
- **Lower resource usage** — suitable for courses with many students

### Advanced Variant

- **Higher response quality** — better at nuanced reasoning, complex debugging, and multi-step explanations
- **Slower responses** — larger models take more time to generate answers
- **Higher resource usage** — may be more appropriate for smaller courses or specific high-value interactions

## Configuring Variants

Variants are configured in the Iris settings on your **course overview page**. You can set the variant for each Iris feature independently. For example, you might use the Advanced variant for Exercise Chat (where response quality matters most) and the Default variant for Course Chat (where speed is more important).

:::tip
If you are unsure which variant to use, start with **Default**. It works well for the majority of use cases. Switch to Advanced if students report that Iris's responses are not detailed or accurate enough for your course content.
:::

## When to Use Advanced

Consider the Advanced variant when:

- Your course covers **complex topics** that require detailed reasoning (e.g., distributed systems, compiler design)
- Students frequently ask **multi-step questions** that require connecting several concepts
- You have a **smaller course** where the higher computational cost is manageable
- Response **quality is more important than speed** for your use case

## Availability

The specific variants available to you depend on your institution's Iris deployment. Your administrator configures which models are available and how they map to the Default and Advanced variants. If you need a different configuration, contact your system administrator.

For technical details on how variants work internally, see the [Developer Guide on the Variant System](/docs/developer/variant-system).

## Next Steps

- [Rate Limits](./rate-limits) — manage student usage
- [Custom Instructions](./custom-instructions) — tailor Iris's responses to your course
