---
title: Chat Context
---

# Chat Context

Every Iris chat has an **active context**: the lecture or exercise it is currently about, or the course as a whole when neither is set. The context decides what material Iris has at hand, so setting it well does more for the quality of an answer than anything else you can do.

A chat is not locked to the context it started in. You can change it at any point, Iris keeps the history, and the chat records where the topic changed. That means you can start with a question about a lecture, move on to the exercise that builds on it, and stay in one conversation throughout.

## The Four Contexts

Whatever a chat is about, Iris can always reach the course as a whole: the exercise list, the lecture list, the competencies and the course FAQs. That is the starting point in every chat. Setting a lecture or an exercise adds its material on top.

| Context                                 | What it adds on top                                                     |
| --------------------------------------- | ----------------------------------------------------------------------- |
| **Course** — no lecture or exercise set | Nothing. Iris works from the course as a whole                          |
| **Lecture**                             | The slides and, when a recording exists, the transcript of that lecture |
| **Programming exercise**                | The problem statement, your current code, build logs and test results   |
| **Text exercise**                       | The problem statement and the text you have written so far              |

:::tip
Leave the context empty for questions that span topics: "which exercises cover recursion?", "how am I doing on the graph competency?", "what was covered last week?". Set a lecture or an exercise when your question is about that one lecture or exercise.
:::

## Setting the Context Yourself

Next to the message input field you will find a context selector and, when a context is active, a chip showing it.

<!-- TODO: Screenshot needed — context selector open, showing the course / lectures / exercises groups, with an active context chip next to it -->

- **Set or change it** — Open the selector and pick a lecture or an exercise. The list is grouped into Lectures and Exercises, and you can filter it by typing.
- **Remove it** — Click the small x on the chip. The chat returns to course level.
- **Do nothing** — Opening Iris from a lecture or exercise page fills the chip in for you.

Your choice takes effect with your next message, not the moment you pick it. The chip shows what Iris will use, so you can still change or remove it before you hit send.

## The Divider in the Chat

Whenever the context changes, Iris draws a labelled divider into the conversation: "Chat topic set", "Chat topic switched" or "Chat topic cleared", with the name of the new lecture or exercise. Click the name to navigate to that lecture or exercise in Artemis.

The divider is not decoration. It tells Iris where the topic changed, so earlier messages get read as being about the previous topic. That is why a long chat that has moved through several exercises does not confuse Iris about which one you are asking about now.

## When Iris Switches the Context Itself

You do not always have to set the context by hand. When you ask about an exercise or a lecture that is not the active context, Iris recognizes it, looks up which one you mean, and switches the chat to it before answering. You see the same divider you would see after switching yourself.

It works in both directions. Asking "can you explain the Quick Sort exercise?" while a lecture is active moves the chat to that exercise. Asking a general question about your progress while an exercise is active moves the chat back to course level.

Two things are worth knowing about the timing:

- **The switch applies from the answer onwards.** Iris answers your question in the new context, and every following message stays there.
- **Iris only switches within your course.** It looks for the exercise or lecture you mentioned in the course you are in, and if it cannot find one that matches, it tells you instead of guessing.

If Iris switched to something you did not mean, set the context you wanted with the selector and carry on. Nothing is lost — the history stays.

## Choosing a Context or Starting a New Chat

Both are reasonable, and they do different things:

| You want to                                 | Do this                            |
| ------------------------------------------- | ---------------------------------- |
| Move to a related topic, keeping the thread | Change the context                 |
| Drop everything and start clean             | Start a new chat with the pen icon |

Changing the context keeps what Iris knows about your work so far. Starting a new chat discards it, which is what you want when a conversation has gone off the rails.

## Next Steps

- [The Iris Chat](./chat) — opening Iris, citations, chat history
- [Tips for Effective Use](./tips) — how to phrase questions
- [Privacy & Data](./privacy) — what each context sends to the language model
