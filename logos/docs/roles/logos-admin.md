---
title: Logos Admin
---

# Logos Admin

The Logos Admin role (`logos_admin`) has full access to the platform. This
includes every page in the UI, also the pages for operators. On the identity
provider, an account becomes a Logos Admin if the account has the OIDC role
that is configured in `KEYCLOAK_ROLES_LOGOS_ADMIN` (see the
[installation guide](../admin/installation.md)).

The UI shows the role badge "Logos Admin" in the header menu.

## Statistics

This page shows the usage of the complete platform: the request volume, the
token counts and the latency over time. The page gets live updates from the
WebSocket statistics feed. If you delete a model, its usage stays in these
views. The historical requests stay under the former name of the model. A
trash icon marks the entry as deleted.

On the **Local Providers** tab, each worker node has its own section. The
section shows memory, lane health and GPU metrics. Next to the name of the
worker, the page shows `version: <commit>` and an info icon. `<commit>` is the
commit from which the image was built. To see the full commit, hold the
pointer over the icon, or tap it on a touch screen. Use the button there to
copy the commit. With this information, you can find which workers have the
update. If a worker cannot report a commit, the page shows `version: unknown`.
The icon then shows the reason.

![Statistics page](/img/roles/logos-admin-statistics.png)

## Models

This page shows the model catalogue of the deployment. It shows tags, aliases,
capabilities and scheduling weights for each model. It also shows the Likert
**profile ratings** (latency / quality / price) as a spider chart. Click a
model to open its **Model Details** view. This view shows the request history,
the error reports and the scheduling statistics of the model.

![Models page](/img/roles/logos-admin-models.png)

## Providers

This page shows each provider that the deployment knows. These are cloud
providers (Azure, OpenAI and others) and connected worker nodes. For each
provider, the page shows the status and the connected models. It also shows the
worker control actions (calibrate, sleep, wake, lane management).

![Providers page](/img/roles/logos-admin-providers.png)

## Policies

Policies are the rules that decide which models a team or an API key can use.
You assign policies to each team. The orchestrator evaluates them for every
request.

![Policies page](/img/roles/logos-admin-policies.png)

## Billing

This page shows the costs for each team, model and provider. Logos calculates
the costs from the usage logs and from the configured catalogue prices.

![Billing page](/img/roles/logos-admin-billing.png)

## Users

This page shows all users of the deployment, with their role, teams and
status. Logos Admins can create users and roles, and can assign users to other
roles. An App Admin can manage only App Developers.

![Users page](/img/roles/logos-admin-user-management.png)

## Teams {#teams}

This page shows the teams, their owners and their members. The **Priority**
column of each team sets the queue level of that team's traffic (1–10, or
Default).

![Teams page](/img/roles/logos-admin-team-management.png)

Below the team list, Logos Admins also see **Queue order**. This is an ordered
ranking of application keys across teams. Rank 1 is served first when SLO or
priority buckets tie. For example, `testapp1-prod` can outrank
`testapp2-prod`, while `testapp1-staging` stays below `testapp2-test`. Move
keys up or down, remove them from the ranking, or add an unranked application
key from any team. Keys that are not in the list keep their usual team and
per-key priority only.

When you open a team, you see the same detail tabs as an owning App Admin sees.
For the tabs Overview to Settings, see [App Admin → Teams](app-admin.md#teams).
Logos Admins also get a **Providers** tab. This tab shows which cloud
providers and worker providers the team can use.

![Team detail — Providers](/img/roles/team-detail-providers.png)

## Agent Sessions

This page shows the coding-agent sessions of the
[agent runner](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-agent/README.md).
For each session, it shows the work, the state and the pull request. Every
Logos Admin can open the page. The **Agents** entry in the sidebar shows only
if the deployment runs the optional agent stack.

Repository analyses of the linked repositories of the teams also run here.
Each night, they run again for repositories that have new commits. **Analyze
all repositories** immediately queues an analysis for every linked repository,
also if there are no new commits. Use it, for example, after an improvement of
the analysis. It does not change repositories that already have an analysis
that is queued or that runs. The results go to the teams as proposals on their
**Workflows** tab ([Team detail](app-admin.md#workflows)).

![Agent Sessions page](/img/roles/logos-admin-agents.png)

## My Workspace

This page is the developer view of the signed-in user. It shows the teams of
the user and the API keys of the user. You can create, rotate and revoke keys.
You can also set model permissions for each key. Every role that has at least
one team and one key can use this page.

![My Workspace page](/img/roles/logos-admin-my-workspace.png)

## AI Tools

This is the same guided setup as for every other role. Select a coding
assistant, a team key and a model. Then install the assistant and connect it.
The page does not change with the role. For the step-by-step procedure, see
[App Developer → AI Tools](app-developer.md#ai-tools).

## Batches

This is the same Batch UI as for the App Admin. Upload a `.jsonl` file, look at
the progress and download the results. See [App Admin → Batches](app-admin.md#batches).
