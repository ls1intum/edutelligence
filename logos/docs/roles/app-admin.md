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

### Repositories

GitHub repositories this team's applications live in. Owners link a repository
URL, branch, and optional path filters; for private repos they can paste a
read-only deploy key. LogosOSSAgent picks up a newly linked repository on its
own within a few minutes; queue an analysis from the same tab to run it sooner
(one at a time — a second request while one is queued or running is refused).
Every night it re-analyses each repository whose branch has new commits;
an unchanged repository is skipped.

![Team detail — Repositories](/img/roles/team-detail-repositories.png)

### Workflows

Latest AI-workflow analyses for the team's linked repositories: Mermaid
diagrams of detected flows and per-call **SLA** plus **objective priority**
recommendations (ordered latency / quality / price). Owners (and Logos Admins)
can **Accept** a recommendation, **Override** SLA or priority order, or
**Reject** it. The **Application key** picker above the recommendations applies
to every Accept and Override on the tab — it defaults to the team's
highest-priority key (usually production), and **No key** leaves key
priorities untouched. Accepting or overriding sets that key's queue priority
from the confirmed SLA so the orchestrator serves traffic accordingly.

A re-analysis **proposes**, it does not overwrite. When it recommends what you
already accepted, overrode to, or rejected for a call site, that decision is
kept ("Kept from the previous analysis"). When it recommends something else,
the call site is **pending** again and shows the earlier decision next to the
new proposal ("Was accepted: ux-critical · latency › quality › price"); key
priorities change only when you review it. A decision survives analyses you
have not reviewed yet: the earlier one is still what is shown and carried
over. If a newer analysis arrived while the tab was open, reviewing an
outdated proposal is refused — reload the tab.

The analysis often cannot tell which model a call site uses (it is usually
configuration, not code), so the **Model** column is a picker: choose the model
the call site actually uses, or leave it **Unknown**. Later analyses keep your
pick. When the model has Likert
profile ratings, a spider chart is shown beside it.

![Team detail — Workflows](/img/roles/team-detail-workflows.png)

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
