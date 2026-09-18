---
title: Architecture
---

# Architecture

Logos separates administration, the public inference gateway, and local-model
orchestration:

- **Logos webservice** manages users, teams, providers, models, permissions,
  billing, and persistent state. It also owns the **public inference gateway**
  (`/v1`, `/openai`, `/jobs`): Logos API-key auth, approximate budget checks,
  direct cloud-provider forwarding for pure-cloud named-model traffic, and
  reverse-proxy of local/mixed traffic to the orchestrator. Deploy more than
  one instance; Traefik load-balances them. Schema migrations use Liquibase's
  database lock so concurrent startups are safe.
- **Logos orchestrator** classifies and schedules **local** (logosnode) and
  mixed requests, then forwards them to a worker node (or still to cloud when
  the gateway proxies a non-cloud-eligible request). Worker WebSocket registry
  and capacity planning stay here — one instance.
- **Logos worker nodes** host local model lanes and report capacity over a
  secure WebSocket.
- **Logos UI** provides administration and usage views.

See the [request lifecycle reference](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-orchestrator/src/logos/pipeline/README.md)
for the detailed local-path pipeline boundaries.
