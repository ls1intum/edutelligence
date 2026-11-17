---
title: Network Layout
---

# Network Layout

This page describes how Iris and the services around it are meant to be placed in a deployment. It is plain deployment guidance: follow it for any installation, and use it as the starting point for your own network plan.

## Recommended Layout

```
Internet
   |
[Reverse proxy of Artemis]          the only part that is reachable from outside
   |
[Artemis application servers]
   |                  |                  |
[Iris]            [Weaviate]        [other services, for example Athena or a message broker]
        private network: no route from the internet
```

- **Only the reverse proxy of Artemis is reachable from the internet**, on the ports that Artemis needs. It forwards requests to the Artemis application servers.
- **Iris, Weaviate and the other supporting services run in a private network.** The Artemis application servers can reach them, and they can reach each other where they need to. Nothing from the internet can. This keeps the number of services that accept requests from outside small.
- **Iris reaches out to a few addresses only**: the Artemis installations it works for (callbacks and the pull-based lecture ingestion) and your LLM providers. Allow outbound connections to those and nothing else where your network lets you.
- **Do not publish the ports of Iris or Weaviate on a public address.** If a reverse proxy in front of Iris is needed, for example for TLS between hosts, allow only the Artemis servers to connect to it.

## One Iris per Environment That Holds Real Data

- Run a separate Iris, with its own Weaviate, for every environment that holds real course or lecture data, in particular production.
- Environments that hold only test data, such as a test and a staging server, can share one Iris. Give each Artemis installation its own key and list its base URL in `allowed_base_urls`, so that a key is answered only for the installation it belongs to (see [Artemis Integration](./artemis-integration.md)).
- Never use one token in several environments.
- The interactive API documentation (`/docs`, `/redoc`) and the schema (`/openapi.json`) are off unless `api_docs_enabled: true` is set. Leave it off on a deployed instance.

## Example: The Deployment at TUM

At TUM, the production environment of Artemis has its own Iris and its own Weaviate instance, both in a private network. The test and staging environments of Artemis share one separate Iris, which holds test data only and is not reachable from the internet either.

Only the reverse proxy of Artemis is reachable from the outside, on specific ports. It forwards requests to the Artemis application servers (the core nodes). The core nodes can reach every service in the private network and pass requests on to them: Iris, Athena, Weaviate, the message broker and the other services. None of these services is reachable from the outside. This is intended, to keep the number of exposed services as small as possible.
