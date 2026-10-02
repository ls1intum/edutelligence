---
title: Using the API
---

# Using the Logos API

Logos implements the OpenAI chat completions, embeddings, audio, files, and
batch APIs. Replace the host and model name in the examples with the values
provided by your administrator.

Keep API keys in environment variables or a secret manager. Do not commit
them to source control or put them in client-side applications.

## Streaming

Set `stream` to `true` to receive server-sent events:

```bash
curl https://logos.aet.cit.tum.de/v1/chat/completions \
  -H "Authorization: ******" \
  -H "Content-Type: application/json" \
  -d '{"model":"your-model","stream":true,"messages":[{"role":"user","content":"Explain recursion."}]}'
```

For the complete request and response schema, use the Swagger UI at `/docs`.
