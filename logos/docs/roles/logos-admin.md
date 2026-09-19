---
title: Logos Admin
---

# Logos Admin

The Logos Admin role (`logos_admin`) has full access to the platform: every
page in the UI, including the operator-facing ones. On the identity provider,
an account becomes a Logos Admin when it carries the OIDC role configured in
`KEYCLOAK_ROLES_LOGOS_ADMIN` (see the
[installation guide](../admin/installation.md)).

The UI shows the role badge "Logos Admin" in the header menu.

## Statistics

Platform-wide usage: request volume, token counts, and latency over time,
with live updates over the WebSocket statistics feed.

![Statistics page](/img/roles/logos-admin-statistics.png)

## Models

The deployment's model catalogue with tags, aliases, capabilities, and
scheduling weights. Clicking a model opens its **Model Details** view:
per-model request history, error reports, and scheduling statistics.

![Models page](/img/roles/logos-admin-models.png)

## Providers

Every provider the deployment knows — cloud providers (Azure, OpenAI, …) and
connected worker nodes — with their status, connected models, and the worker
control actions (calibrate, sleep, wake, lane management).

![Providers page](/img/roles/logos-admin-providers.png)

## Policies

The rules that decide which models a team or API key may use. Policies are
assigned per team and evaluated by the orchestrator for every request.

![Policies page](/img/roles/logos-admin-policies.png)

## Billing

Costs per team, model, and provider, computed from the usage logs and the
configured catalogue prices.

![Billing page](/img/roles/logos-admin-billing.png)

## Users

All users of the deployment: their role, teams, and status. Logos Admins can
create and re-assign users and roles (an App Admin can only manage App
Developers).

![Users page](/img/roles/logos-admin-user-management.png)

## Teams

Teams, their owners, and members. Opening a team shows its members, its API
keys, and its per-team settings (queue priority, budget).

![Teams page](/img/roles/logos-admin-team-management.png)

![Team detail](/img/roles/logos-admin-team-management-detail.png)

## Agent Sessions

The [agent runner's](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-agent/README.md)
coding-agent sessions: what each is working on, its state, and its pull
request. The page is reachable to every Logos Admin; the **Agents** entry in
the sidebar only appears when the deployment runs the optional agent stack.

![Agent Sessions page](/img/roles/logos-admin-agents.png)

## My Workspace

The developer-facing view of the signed-in user: their teams, their API keys
(create, rotate, revoke), and per-key model permissions. Available to every
role that has at least one team and key.

![My Workspace page](/img/roles/logos-admin-my-workspace.png)

## AI Tools

Same guided setup as for every other role — pick a coding assistant, team
key, and model, then install and connect. The page does not change with the
role; see the step-by-step walkthrough under
[App Developer → AI Tools](app-developer.md#ai-tools).

## Batches

The OpenAI Batch API in the browser: upload a `.jsonl` file, watch the job's
progress, download the result file. See [batch processing](../batch-processing.md)
for what happens server-side.

![Batches page](/img/roles/logos-admin-batches.png)
