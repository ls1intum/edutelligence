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
| **Web service** | `logos-webservice/` | Spring Boot service for identity (users, teams, roles), billing, statistics, and admin endpoints (`/api/*`). It also owns the **public inference gateway** (`/v1`, `/openai`, `/jobs`): Logos API-key auth, approximate budget checks, direct cloud-provider forwarding for pure-cloud named-model traffic, and reverse-proxy of local/mixed traffic to the orchestrator. Deploy more than one replica; Traefik load-balances them. Schema migrations use Liquibase's database lock so concurrent startups are safe. |
| **Orchestrator** | `logos-orchestrator/` | FastAPI service (single instance) that classifies and schedules **local** (logosnode) and mixed requests, holds the registry of connected worker nodes, and forwards to the chosen provider. Pure-cloud named-model traffic no longer enters here in the default gateway path. |
| **UI** | `logos-ui/` | The Angular admin frontend, served by the same Traefik instance as the API. |
| **Database** | `db/` | PostgreSQL 17 plus `pg_cron`. The schema source of truth is the web service's Liquibase changelogs. |
| **Keycloak** | `keycloak/` | The OpenID Connect provider for login. The development stack ships its own Keycloak; a production deployment points at the organisation's existing identity provider. |
| **Traefik** | (compose file) | The reverse proxy in front of everything: TLS (Let's Encrypt in production), and path-based routing that puts UI and API on one domain. Inference paths (`/v1`, `/openai`, `/jobs`) and admin API paths land on the web service; worker control routes that need the live registry stay on the orchestrator. |
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

![Logos architecture — core node, gateway split, worker nodes, and cloud providers](/img/architecture.svg)

Editable source: [`architecture.drawio`](/img/architecture.drawio)
(open in [diagrams.net](https://app.diagrams.net/)).

Two properties fall out of this shape:

- **The worker is outbound-only.** It opens the WebSocket to the orchestrator
  and never needs an inbound port, so a worker behind a NAT or firewall works
  unchanged. All control (sleep, wake, calibrate, lane changes) travels over
  that connection.
- **The client sees one domain.** Traefik routes by path on the default HTTPS
  port: public inference (`/v1`, `/openai`, `/jobs`) and admin API (`/api`, …)
  go to the web service; a small set of logosnode control routes that need the
  live worker registry stay on the orchestrator; everything else serves the UI.
- **Cloud vs local split (Phase 1).** Pure-cloud named-model requests authenticate
  and forward from the web service directly to the configured cloud provider.
  Local and mixed traffic is authenticated on the web service, then proxied to
  the orchestrator. Scale the web service with `LOGOS_WEBSERVICE_REPLICAS` on
  the core node's `.env` (see [deployment](../deployment.md#inference-gateway-replicas));
  keep a single orchestrator instance.

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
| **Inference gateway** | The web service path that terminates `/v1`, `/openai`, and `/jobs`: auth, budget, direct cloud forward, or proxy to the orchestrator. |
| **Batch** | An OpenAI Batch API job (`/v1/batches`): many latency-tolerant requests in one `.jsonl` upload. See [batch processing](../batch-processing.md). |
| **Agent session** | One run of a coding agent inside an isolated container, produced by the agent runner from a task (usually a GitHub issue or pull request). |
| **Calibration** | The worker measuring how much GPU memory each model needs when loaded versus sleeping. Profiles feed the capacity planner. |
| **Capacity planner** | The orchestrator's background loop that sleeps idle lanes, wakes lanes on demand, and tunes GPU memory utilization. |

## Roles

Logos has three roles. A user's role decides which UI pages are visible and
which admin endpoints the web service accepts:

| Role | UI label | Scope |
|---|---|---|
| `logos_admin` | Logos Admin | Full platform access: all pages, including providers, policies, billing, and agent sessions. |
| `app_admin` | App Admin | Application administration: users, teams, and the shared developer pages. |
| `app_developer` | App Developer | Developer tools: models, own workspace, AI tools. |

The role a user gets is derived at login from the roles of their identity
provider account: an account carrying the configured `logos_admin` role
becomes a Logos Admin, one carrying the configured `app_admin` role becomes an
App Admin, and every other authenticated user is an App Developer. The
mapping is configured per deployment (see the
[installation guide](../admin/installation.md)).
