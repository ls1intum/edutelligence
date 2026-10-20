---
title: Getting Started
---

# Getting started with Logos

Logos provides an OpenAI-compatible API and a web interface. Teams use them
to share hosted and self-hosted language models. Your administrator gives you
a Logos API key and the URL of the Logos instance.

## Open the web interface

1. Open the Logos URL in a browser.
2. Sign in with the configured identity provider.

The **Models** page shows the models that are available to your team. The
permissions of your team decide which of the **Providers**, **Statistics**,
and **Batches** pages you can use.

## Make your first request

Send your API key as a bearer token:

```bash
curl https://logos.aet.cit.tum.de/v1/chat/completions \
  -H "Authorization: ******" \
  -H "Content-Type: application/json" \
  -d '{"model":"your-model","messages":[{"role":"user","content":"Hello!"}]}'
```

The interactive API documentation is at `https://logos.aet.cit.tum.de/docs`.
Ask an administrator which model names and which endpoint URL are enabled for
your team.
