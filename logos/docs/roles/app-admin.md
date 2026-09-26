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

## Models {#models}

The deployment's model catalogue: name, description, and capabilities.
App Admins see the list but not the per-model operator controls (weights,
aliases, add/delete).

![Models page](/img/roles/app-admin-models.png)

## Users

The users of the deployment: their role, teams, and status. An App Admin can
create users and assign them to teams — but can only create App Developers,
never higher roles.

![Users page](/img/roles/app-admin-user-management.png)

## Teams {#teams}

Teams, their owners, and members. App Admins can create teams, add members,
and manage the team's API keys — for the teams they own.

![Teams page](/img/roles/app-admin-team-management.png)

Opening a team opens its detail view. Owners (and Logos Admins) get the full
tab set below; other members only see **Overview** and **Members**.

### Overview

Headcount, active keys, permitted models, member budget usage, and the
defaults applied when a key or member has no individual limit.

![Team detail — Overview](/img/roles/team-detail-overview.png)

### Members

Owners and members, with per-person budget and rate-limit overrides. Add or
remove people here (unless the team is Keycloak-managed).

![Team detail — Members](/img/roles/team-detail-members.png)

### Application Keys

Application (service) keys that belong to the team — create, rotate, revoke,
and set per-key limits / model permissions.

![Team detail — Application Keys](/img/roles/team-detail-application-keys.png)

### Models {#team-models}

Which catalogue models this team may use.

![Team detail — Models](/img/roles/team-detail-models.png)

### Activity

Live queue state for the team, recent request log, token totals, and export.

![Team detail — Activity](/img/roles/team-detail-activity.png)

### Cloud Usage

What cloud providers charged for this team's off-site traffic (local models
do not appear here — see Activity for that).

![Team detail — Cloud Usage](/img/roles/team-detail-cloud-usage.png)

### Settings

Team monthly budget, default key budget, and default cloud/local rate limits.
Also where an owner deletes the team.

![Team detail — Settings](/img/roles/team-detail-settings.png)

## My Workspace

The developer-facing view of the signed-in user: their teams, their API keys
(create, rotate, revoke), and per-key model permissions. Available to every
role that has at least one team and key.

![My Workspace page](/img/roles/app-admin-my-workspace.png)

## AI Tools

Same guided setup as for every other role — pick a coding assistant, team
key, and model, then install and connect. The page does not change with the
role; see the step-by-step walkthrough under
[App Developer → AI Tools](app-developer.md#ai-tools).

## Batches {#batches}

The OpenAI Batch API in the browser: upload a `.jsonl` file, watch the job's
progress, download the result file. See [batch processing](../batch-processing.md)
for what happens server-side. The page is the same for every role that can
open it (App Admin and Logos Admin).

![Batches page](/img/roles/batches.png)
