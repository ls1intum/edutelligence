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

The deployment's model catalogue, with what each model supports (function
calling, vision, reasoning) and where it is served. Models can be searched
and their details opened from the list.

![Models page](/img/roles/app-developer-models.png)

## My Workspace

The developer's own view: the teams the user belongs to and the API keys in
them — including creating, rotating, and revoking keys and setting per-key
model permissions. This is where a developer gets the secret to call the
[Logos API](../user/api-usage.md).

![My Workspace page](/img/roles/app-developer-my-workspace.png)

## AI Tools

**AI Coding Tools** is a guided setup wizard shared by every role (the page
itself does not change with the role badge). It walks you through connecting
a coding assistant — Claude Code or OpenCode — to Logos with your own API
key. The stepper renumbers itself: **Team** is skipped when you only have
one key, and **Model** is skipped when that key can only reach one usable
model.

### 1. Tool

Pick Claude Code or OpenCode. The comparison table is the decision surface —
same Logos models and key either way; they differ in where they run, how
they treat the context window, and what they do to an existing setup.

![AI Tools — choose tool](/img/roles/ai-tools-step-tool.png)

### 2. Team

Choose which team's key the assistant will use (billing and model
permissions follow that key). Shown only when you have more than one key.

![AI Tools — choose team](/img/roles/ai-tools-step-team.png)

### 3. Model

Pick the model the assistant should call. For Claude Code the wrapper maps
every alias (`opus` / `sonnet` / `haiku`) to this one model so `/model`
never leaves Logos.

![AI Tools — choose model](/img/roles/ai-tools-step-model.png)

### 4. Install

OS-specific install commands for the tool itself (skip if you already have
it). Tabs cover macOS, Linux, and Windows.

![AI Tools — install](/img/roles/ai-tools-step-install.png)

### 5. Connect

Generated commands that wire the tool to this Logos deployment — for Claude
Code that is the `claude-logos` wrapper (your plain `claude` Anthropic setup
is left alone).

![AI Tools — connect](/img/roles/ai-tools-step-connect.png)

### 6. Verify

Check the connection (`claude-logos --check`), update the wrapper, or
uninstall it again.

![AI Tools — verify](/img/roles/ai-tools-step-verify.png)
