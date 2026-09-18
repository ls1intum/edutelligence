---
title: Architecture
---

# Architecture and terminology

This page is the terminology ground truth for all Logos documentation. The
subsystem decomposition is defined here; every other document uses these
names, so read this first if the docs feel abstract.

Logos is an LLM engineering platform. Clients call it like an OpenAI
endpoint (`/v1/chat/completions`, `/v1/models`, …) and get models back from
two kinds of backends — cloud providers and self-hosted GPU workers — with
logging, billing, policies, and scheduling in between.

## The subsystem decomposition

Logos is two kinds of machine plus an optional add-on:

- A **core node** — one machine running the core stack below. It is the only
  part clients ever talk to.
- Any number of **worker nodes** — separate GPU machines that serve local
  models and connect *out* to the core node.
- An optional **agent stack** — services on the core node that run coding
  agents on spare serving capacity.

### Core stack (one machine)

| Subsystem | Directory | What it is |
|---|---|---|
| **Orchestrator** | `logos-orchestrator/` | The heart: a FastAPI service that terminates the public API (`/v1`, `/openai`, `/jobs`), classifies and schedules each request, holds the registry of connected worker nodes, and forwards to the chosen provider. |
| **Web service** | `logos-webservice/` | A Spring Boot service behind the admin UI: identity (users, teams, roles), billing, statistics, and the admin endpoints (`/api/*`). It owns the database schema via Liquibase. |
| **UI** | `logos-ui/` | The Angular admin frontend, served by the same Traefik instance as the API. |
| **Database** | `db/` | PostgreSQL 17 plus `pg_cron`. The schema source of truth is the web service's Liquibase changelogs. |
| **Keycloak** | `keycloak/` | The OpenID Connect provider for login. The development stack ships its own Keycloak; a production deployment points at the organisation's existing identity provider. |
| **Traefik** | (compose file) | The reverse proxy in front of everything: TLS (Let's Encrypt in production), and path-based routing that puts UI and API on one domain. |
| **Rate-limit gateway** | `rate-limit-gateway/` | An nginx front door in front of Traefik that enforces per-IP request budgets — the first layer of the two-layer rate limiting (per-IP here, per-service in Traefik; see [deployment](../deployment.md#security--rate-limiting)). |

### Worker node (separate machine)

| Subsystem | Directory | What it is |
|---|---|---|
| **Worker node** | `logos-workernode/` | The outbound worker for local inference. It runs one **lane** (a `vllm serve` process) per configured model, keeps a WebSocket session open to the orchestrator, reports runtime state so the orchestrator can schedule against warm/cold capacity, and auto-calibrates model memory profiles. |

### Agent stack (optional, core node)

| Subsystem | Directory | What it is |
|---|---|---|
| **Agent runner** | `logos-agent/` | Runs coding agents in isolated, capped containers on serving capacity Logos is not otherwise using, and gives that capacity back the moment a user needs it. |
| **Agent gateway** | `agent-gateway/` | An nginx bridge that exposes *only* the orchestrator's `/v1` model surface to the agent session containers — and is where the model credential lives. |

Internal engineering references, for the curious (not needed to use Logos):
the
[request pipeline reference](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-orchestrator/src/logos/pipeline/README.md),
the [agent runner README](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-agent/README.md),
and the [worker node guide](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-workernode/AGENTS.md).

## How the pieces talk

```
                    ┌───────────────────────── core node ─────────────────────────┐
 client (OpenAI SDK,│                                                              │
        browser)    │  ┌─────────┐  per-IP budget  ┌──────────────────────────┐   │
      ─────────────►│  │  nginx  │ ──────────────► │  Traefik (TLS, routing)  │   │
   /v1, /jobs, UI   │  │ gateway │                 └────────────┬─────────────┘   │
                    │  └─────────┘                              │                 │
                    │                   ┌───────────────────────┼────────────┐    │
                    │                   ▼                       ▼            ▼    │
                    │             ┌───────────┐           ┌────────────┐  ┌─────┐ │
                    │             │  Web      │           │ Orchestr-  │  │  UI │ │
                    │             │  service  │◄─────────►│ ator       │  └─────┘ │
                    │             │ (Spring)  │  internal │ (FastAPI)  │         │
                    │             └─────┬─────┘  secret   └───┬────┬───┘         │
                    │                   │                     │    │             │
                    │             ┌─────▼─────┐        ┌──────▼───▼──────────┐   │
                    │             │ Postgres  │        │ agent runner +      │   │
                    │             │ (Liqui-   │        │ agent gateway       │   │
                    │             │  base)    │        │ (optional)          │   │
                    │             └───────────┘        └─────────────────────┘   │
                    └────────────────────────────────────────┬───────────────────┘
                                                             │
            outbound WebSocket + HTTPS (the worker initiates;│
            the core node never dials the worker)            ▼
                    ┌─────────────────────── worker node ───────────────────────┐
                    │  worker node  ──►  one lane (vllm serve) per model        │
                    └───────────────────────────────────────────────────────────┘
```

Two properties fall out of this shape:

- **The worker is outbound-only.** It opens the WebSocket to the orchestrator
  and never needs an inbound port, so a worker behind a NAT or firewall works
  unchanged. All control (sleep, wake, calibrate, lane changes) travels over
  that connection.
- **The client sees one domain.** Traefik routes by path on the default HTTPS
  port: API paths (`/v1`, `/openai`, `/jobs`, `/api`, `/docs`, …) go to the
  orchestrator or web service, everything else serves the UI.

## Glossary

| Term | Meaning |
|---|---|
| **Core node** | The machine running the core stack. Clients, the UI, and all admin functions live here. |
| **Worker node** | A (usually GPU) machine running the worker node service. It serves local models and connects out to a core node. |
| **Lane** | One `vllm serve` process on a worker, serving one model. Lanes are the unit the orchestrator schedules and the capacity planner sleeps/wakes. |
| **Model** | A model id that Logos offers to clients, e.g. `logos-v1/...`. A model is served either by a cloud provider or by a worker lane. |
| **Provider** | Where a model is physically served: a cloud provider (Azure, OpenAI, …) configured on the core node, or a connected worker node. The UI's **Providers** page lists both kinds. |
| **Policy** | A rule that restricts which models a team or API key may use. Managed on the UI's **Policies** page. |
| **Team** | A group of users. API keys and budgets belong to teams, and per-team policies apply to their keys. |
| **API key** | A secret a client uses to call the Logos API. Keys belong to a team, carry the team's model permissions, and can pin a queue priority. |
| **Batch** | An OpenAI Batch API job (`/v1/batches`): many latency-tolerant requests in one `.jsonl` upload. See [batch processing](../batch-processing.md). |
| **Agent session** | One run of a coding agent inside an isolated container, produced by the agent runner from a task (usually a GitHub issue or pull request). |
| **Calibration** | The worker measuring how much GPU memory each model needs when loaded versus sleeping. Profiles feed the capacity planner. |
| **Capacity planner** | The orchestrator's background loop that sleeps idle lanes, wakes lanes on demand, and tunes GPU memory utilization. |

## Roles

Logos has three roles. A user's role decides which UI pages are visible and
which admin endpoints the web service accepts:

| Role | UI label | Scope | Guide |
|---|---|---|---|
| `logos_admin` | Logos Admin | Full platform access: all pages, including providers, policies, billing, and agent sessions. | [Logos Admin](../roles/logos-admin.md) |
| `app_admin` | App Admin | Application administration: users, teams, and the shared developer pages. | [App Admin](../roles/app-admin.md) |
| `app_developer` | App Developer | Developer tools: models, own workspace, AI tools. | [App Developer](../roles/app-developer.md) |

The role a user gets is derived at login from the roles of their identity
provider account: an account carrying the configured `logos_admin` role
becomes a Logos Admin, one carrying the configured `app_admin` role becomes an
App Admin, and every other authenticated user is an App Developer. The
mapping is configured per deployment (see the
[installation guide](../admin/installation.md)).
