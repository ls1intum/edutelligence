---
title: App Admin
---

# App Admin

The App Admin role (`app_admin`) manages the application for its people:
users, teams, and keys — without touching the platform-level settings
(providers, policies, billing, agent sessions), which stay with the
[Logos Admin](logos-admin.md). On the identity provider, an account becomes
an App Admin when it carries the OIDC role configured in
`KEYCLOAK_ROLES_APP_ADMIN` (see the
[installation guide](../admin/installation.md)).

The UI shows the role badge "App Admin" in the header menu.

## Models

The deployment's model catalogue: name, description, and capabilities.
App Admins see the list but not the per-model operator controls (weights,
aliases, add/delete).

![Models page](/img/roles/app-admin-models.png)

## Users

The users of the deployment: their role, teams, and status. An App Admin can
create users and assign them to teams — but can only create App Developers,
never higher roles.

![Users page](/img/roles/app-admin-user-management.png)

## Teams

Teams, their owners, and members. App Admins can create teams, add members,
and manage the team's API keys — for the teams they own. Opening a team
shows its members, its API keys, and its per-team settings (queue priority,
budget).

![Teams page](/img/roles/app-admin-team-management.png)

![Team detail](/img/roles/app-admin-team-management-detail.png)

## My Workspace

The developer-facing view of the signed-in user: their teams, their API keys
(create, rotate, revoke), and per-key model permissions. Available to every
role that has at least one team and key.

![My Workspace page](/img/roles/app-admin-my-workspace.png)

## AI Tools

Ready-made tools built on the Logos API (transcription, translation, and the
coding-agent entry points), configured against the user's own keys.

![AI Tools page](/img/roles/app-admin-ai-tools.png)

## Batches

The OpenAI Batch API in the browser: upload a `.jsonl` file, watch the job's
progress, download the result file. See [batch processing](../batch-processing.md)
for what happens server-side.

![Batches page](/img/roles/app-admin-batches.png)
