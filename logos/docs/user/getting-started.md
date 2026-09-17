---
title: Getting Started
---

# Getting started with Logos

Logos provides an OpenAI-compatible API and a web interface for teams that
share hosted and self-hosted language models. Your administrator gives you a
Logos API key and the URL of the Logos instance.

## Open the web interface

Open the Logos URL in a browser and sign in with the configured identity
provider. The **Models** page shows the models available to your team. The
**Providers**, **Statistics**, and **Batches** pages are available according
to your team's permissions.

## Make your first request

Use your API key as a bearer token:

```bash
curl https://logos.example.com/v1/chat/completions \
  -H "Authorization: ******" \
  -H "Content-Type: application/json" \
  -d '{"model":"your-model","messages":[{"role":"user","content":"Hello!"}]}'
```

The API is documented interactively at `https://logos.example.com/docs`.
Ask an administrator which model names and endpoint URL are enabled for your
team.
