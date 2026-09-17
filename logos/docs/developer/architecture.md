---
title: Architecture
---

# Architecture

Logos separates the public API and administration service from model
orchestration:

- **Logos webservice** manages users, teams, providers, models, permissions,
  billing, and persistent state.
- **Logos orchestrator** classifies and schedules requests, then forwards them
  to a cloud provider or worker node.
- **Logos worker nodes** host local model lanes and report capacity over a
  secure WebSocket.
- **Logos UI** provides administration and usage views.

See the [request lifecycle reference](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-orchestrator/src/logos/pipeline/README.md)
for the detailed pipeline boundaries.
