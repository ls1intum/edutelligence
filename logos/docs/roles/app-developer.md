---
title: App Developer
---

# App Developer

The App Developer role (`app_developer`) is the default role: every
authenticated user who does not carry a configured admin role on the
identity provider becomes an App Developer (see the
[installation guide](../admin/installation.md)). App Developers use Logos
through their team's models and their own API keys.

The UI shows the role badge "App Developer" in the header menu. Until the
user belongs to a team that has an API key, the developer-only pages are not
reachable and the UI shows a **No Access** page instead.

## Models

The models the user's team may use, with their queue state and health. This
is the starting point for choosing a model name for API calls.

![Models page](/img/roles/app-developer-models.png)

## My Workspace

The developer's own view: the teams the user belongs to and the API keys in
them — including creating, rotating, and revoking keys and setting per-key
model permissions. This is where a developer gets the secret to call the
[Logos API](../user/api-usage.md).

![My Workspace page](/img/roles/app-developer-my-workspace.png)

## AI Tools

Ready-made tools built on the Logos API (transcription, translation, and the
coding-agent entry points), configured against the user's own keys — no
scripting needed to try a model.

![AI Tools page](/img/roles/app-developer-ai-tools.png)
