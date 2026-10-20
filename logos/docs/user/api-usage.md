---
title: Using the API
---

# Using the Logos API

Logos implements the OpenAI chat completions, embeddings, audio, files, and
batch APIs. Replace the host and the model name in the examples with the
values from your administrator.

Keep API keys in environment variables or in a secret manager. Do not commit
API keys to source control. Do not put API keys in client-side applications.

## Streaming

To receive server-sent events, set `stream` to `true`:

```bash
curl https://logos.aet.cit.tum.de/v1/chat/completions \
  -H "Authorization: ******" \
  -H "Content-Type: application/json" \
  -d '{"model":"your-model","stream":true,"messages":[{"role":"user","content":"Explain recursion."}]}'
```

For the complete request and response schema, see the Swagger UI at `/docs`.
