---
title: Exercise Chat
---

# Exercise Chat

The Exercise Chat gives you context-aware help while you work on a programming exercise. Iris can see your code, build output, and test results — so you never have to copy-paste anything.

## How to Access It

While working on a programming exercise in Artemis, click the **floating Iris icon** in the bottom-right corner of the screen. The chat opens as an overlay where you can ask questions without leaving the exercise.

:::info Screenshot Needed
Exercise chat showing context-aware response
:::

## What Iris Automatically Sees

When you open the Exercise Chat, Iris has access to:

- **Problem statement** — the full exercise description and requirements
- **Your current code** — the latest version in the online editor or your most recent submission
- **Build logs** — compiler output, including errors and warnings
- **Test results** — which tests pass and which fail, along with failure messages

This context is sent automatically. You do not need to describe your code or paste error messages — just ask your question and Iris already knows what you are working with.

## How Iris Guides You

Iris is designed to help you **learn**, not to hand you the solution. When you ask for help, it uses a calibrated scaffolding approach:

1. It might first draw your attention to a specific line or concept you should look at.
2. If you are still stuck, it asks guiding questions to help you think through the problem.
3. It can provide higher-level feedback about your approach or strategy.
4. When needed, it illustrates patterns with analogous examples — without revealing the actual answer.

For a full explanation of this approach, see [How Iris Helps You Learn](./how-iris-helps).

## Example Interaction

> **You:** My code compiles but the second test case fails. I don't understand why.
>
> **Iris:** Looking at your implementation of `findShortestPath`, I notice the test that fails involves a graph with cycles. Consider: what happens in your algorithm when it visits a node it has already seen?
>
> **You:** Oh, I think I need to track visited nodes?
>
> **Iris:** Exactly! Think about where in your loop you should check whether a node has already been visited, and what data structure would be efficient for that lookup.

Notice how Iris does not write the fix for you. It points you toward the issue and asks questions that help you arrive at the solution yourself.

## Proactive Hints

If Iris detects that you might be stuck — for example, after repeated build failures — it may **proactively offer a hint** without you having to ask. These hints follow the same scaffolding approach, starting subtle and becoming more specific only if needed.

:::tip
If a proactive hint is not relevant to what you are working on, just ignore it and continue. You can also tell Iris what you are actually trying to do to get more targeted help.
:::

## Tips for Exercise Chat

- **Be specific** — "Why does my BFS implementation fail on graphs with cycles?" gets better help than "My code doesn't work."
- **Share your thinking** — telling Iris what you have already tried helps it avoid repeating suggestions.
- **Ask follow-up questions** — if Iris's hint is not clear enough, ask it to elaborate.
- If the conversation gets long or confused, **start a new chat** for a fresh perspective.

## Next Steps

- [Text Exercise Chat](./text-exercise-chat) — help with written exercises
- [How Iris Helps You Learn](./how-iris-helps) — the scaffolding approach in detail
- [Tips for Effective Use](./tips) — general advice for working with Iris
