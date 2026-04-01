---
title: Privacy & Data
---

# Privacy & Data

Iris is designed with privacy in mind. This page explains what data Iris processes, how it is protected, and what choices you have.

## Cloud AI

When you use the **Cloud** AI experience:

- Requests are typically processed on **European Azure servers** located within the EU. The exact provider may vary depending on your institution's deployment.
- A **data processing agreement** governs how your data is handled.
- **Your data is not used to train AI models.** For example, Microsoft's Azure OpenAI Service does not use customer data for model training.
- Data is transmitted over encrypted connections and is not stored beyond what is needed to generate a response.

## On-Premise AI

When you use the **On-Premise** AI experience:

- All processing happens on **your institution's own infrastructure**.
- **No data leaves the university network** at any point.
- This option provides the highest level of data locality, suitable for users or institutions with strict data sovereignty requirements.

## What Data Is Sent to the AI

When you use Iris, the following data may be included in requests to the language model:

| Data                           | When It Is Sent                                 |
| ------------------------------ | ----------------------------------------------- |
| Your chat messages             | Every conversation                              |
| Conversation history           | To maintain context within a session            |
| Exercise problem statement     | In Exercise Chat                                |
| Your code / submission text    | In Exercise Chat and Text Exercise Chat         |
| Build logs and test results    | In Exercise Chat (programming exercises)        |
| Lecture slides and transcripts | In Course Chat and Lecture Chat (via retrieval) |
| Memory summaries               | When Memory is enabled                          |

### What Is NOT Sent

- Your **name, email, or student ID** are not included in requests to the language model.
- Your **grades or performance data** across other exercises are not sent.
- **Other students' data** is never included in your requests.

:::info
The AI receives the context needed to help you with your current question — nothing more. Iris is designed to minimize the data footprint of each request.
:::

## GDPR Considerations

Iris operates under the General Data Protection Regulation (GDPR). Key points:

- You have the **right to access** your stored data (available through your learner profile).
- You have the **right to deletion** — you can delete your Memory data and chat history at any time.
- You can **withdraw consent** by switching your AI experience to "No AI" at any time.
- Your institution's data protection officer can provide additional information about the specific data processing agreement in place.

## Your Choices

You are always in control of your AI experience:

| Action                                            | How                            |
| ------------------------------------------------- | ------------------------------ |
| Switch AI experience (Cloud / On-Premise / No AI) | Account settings in Artemis    |
| Enable or disable Memory                          | Learner profile settings       |
| Delete stored memories                            | Learner profile settings       |
| Start a fresh conversation (clear context)        | Click the pen icon in the chat |

:::tip
If you are unsure about data handling at your institution, ask your instructor or check with your university's data protection office.
:::

## Next Steps

- [Memory](./memory) — how Iris Memory works and how to manage it
- [Getting Started](./getting-started) — choose your AI experience
- [Tips for Effective Use](./tips) — practical advice for working with Iris
