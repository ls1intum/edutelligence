# Decision models

A decision model answers typed questions about a text with calibrated
probabilities instead of generated text. Typical uses are ticket triage, model
routing, and content or safety moderation. Logos serves decision models through
`POST /v1/systemone`. The endpoint uses the request and response schema of
TypeSafe's Jev API, which Ollama also implements.

- [Asking questions](#asking-questions)
- [Question types](#question-types)
- [Supported models](#supported-models)
- [How Logos answers](#how-logos-answers)
- [Serving a decision model on a worker node](#serving-a-decision-model-on-a-worker-node)
- [Limits](#limits)

## Asking questions

Send the text as `state` and name each question. A single request can ask
several questions about the same state.

```bash
curl https://logos-test.aet.cit.tum.de/v1/systemone \
  -H "Authorization: Bearer $LOGOS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "autotrust/JEV-27B-VL",
    "state": {"ticket": "I was charged twice and want a refund. Demo at noon!"},
    "questions": {
      "team": {
        "type": "choice",
        "instructions": "Which team should handle this ticket?",
        "criteria": {
          "billing": "A payment or refund issue",
          "technical": "A malfunction or setup issue",
          "other": null
        }
      },
      "urgent": {"type": "noul", "instructions": "Does this need a reply within the hour?"},
      "severity": {
        "type": "score",
        "instructions": "How severe is the problem?",
        "criteria": ["Cosmetic", "Annoying", "Blocking"]
      }
    }
  }'
```

The response has this form. The values are examples.

```json
{
  "model": "autotrust/JEV-27B-VL",
  "answers": {
    "team": {
      "type": "choice",
      "choice": "billing",
      "probabilities": {"billing": 0.985, "technical": 0.012, "other": 0.003},
      "confidence": 0.922
    },
    "urgent": {"type": "noul", "noul": 0.81},
    "severity": {
      "type": "score",
      "score": 1.21,
      "legend": {"0": "Cosmetic", "1": "Annoying", "2": "Blocking"},
      "probabilities": {"0": 0.12, "1": 0.55, "2": 0.33},
      "confidence": 0.14
    }
  },
  "usage": {"input_tokens": 312, "output_tokens": 3}
}
```

`state`, `instructions`, and the criteria descriptions accept a string or any
JSON value. Logos renders JSON as text.

## Question types

| Type | `criteria` | Answer |
|------|------------|--------|
| `noul` | Optional `{"true": …, "false": …}`: what counts as yes and as no. | `noul`: the probability of yes. |
| `choice` | Required: the option names mapped to a description, or to `null` when the name says enough. | `choice`: the most likely option, `probabilities` for every option, and `confidence`. |
| `score` | Required: the level descriptions, lowest first. A description's position is its level. | `score`: the probability-weighted level, `legend`, `probabilities` per level, and `confidence`. |

`confidence` is one minus the normalised entropy of the probabilities. It is 1
when one answer takes all probability and 0 when all answers are equally likely.
Use low values to send an answer to a human for review.

## Supported models

| Model | Notes |
|-------|-------|
| `autotrust/JEV-27B-VL` | Qwen3.8-27B with a decision head. The same lane also serves ordinary chat requests under the model name. |

The API key needs access to the model, as for any other request. Logos rejects
other models on this endpoint with HTTP 400.

## How Logos answers

The model's decision head is a LoRA module next to the base model on the same
vLLM lane. Each question becomes one completion on that module. The completion
reads the probabilities of the answer labels at the first output position:
`false`/`true`, the score levels, or one letter per choice. No text is
generated. Logos adds the head's bias, applies the calibrated temperature of the
question type, and normalises.

Each question runs through the normal request pipeline. Logos therefore
authorises, schedules, logs, and bills every question like a completion. The
questions of one request run in parallel and share the state prefix, which
vLLM's prefix cache computes only once. `usage` adds up the questions.

## Serving a decision model on a worker node

The worker node serves the model with plain vLLM. It needs no plugin and no
extra container. Add the model to `engines.vllm.model_overrides` in the worker's
`config.yml`:

```yaml
engines:
  vllm:
    model_overrides:
      autotrust/JEV-27B-VL:
        max_model_len: 32768
        max_num_seqs: 8
        extra_args:
          - --enable-lora
          - --max-lora-rank=32
          - --lora-modules=jev-decision={model_path}/adapter_vllm
          - --logprobs-mode=processed_logprobs
          - --mamba-cache-mode=align
```

- `{model_path}` stands for the model's local Hugging Face snapshot. The worker
  replaces it before it starts vLLM. The LoRA module must be named
  `jev-decision`.
- `--logprobs-mode=processed_logprobs` makes vLLM report the probabilities
  after it restricts the next token to the answer labels.
- `max_num_seqs: 8` is required. Larger batches return wrong probabilities on
  this model's multimodal LoRA path.
- The model needs one GPU with at least 80 GB of memory.

## Limits

- `choice`: 2 to 16 options. The decision head is calibrated for the labels A to P.
- `score`: 2 to 6 levels.
- Text and JSON state only. Images are not supported on this endpoint.
- No streaming and no async job variant.
