"""The single home for vLLM-bound magic values (issue #873).

Everything in this module is bound to a specific vLLM version, configuration,
or instance and has to be re-checked whenever the worker's vLLM upgrade
changes what it registers, prints, or exposes:

- the model-name to ``--tool-call-parser`` / ``--reasoning-parser`` /
  ``--default-chat-template-kwargs`` mapping tables (vLLM's parser registry
  changes between releases),
- the persistent custom chat-template directory and its resolution rules,
- the vLLM log signatures we match or parse: fatal load-error needles, the
  KV-too-small / Mamba max_num_seqs / "Maximum concurrency" lines,
- the ``/metrics`` name spellings we scrape (they drift between vLLM
  versions - e.g. the ``prefix_cache_hit_rate`` gauge predates 0.20),
- vLLM process/install plumbing: scrubbed distributed-launch env vars, the
  default binary name, and the build-time-baked quantization-method registry
  file.

If you are about to hard-code another vLLM-specific value elsewhere, add it
here instead.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

# -----------------------------------------------------------------------------
# Model-name to vLLM CLI flag mapping tables
# -----------------------------------------------------------------------------


# Model-name → vLLM --tool-call-parser mapping.  Checked in order;
# first match wins.  Patterns are lowercased substrings of the HF model id.
# Full list of parsers: https://docs.vllm.ai/en/latest/features/tool_calling.html
_TOOL_PARSER_RULES: tuple[tuple[str, str], ...] = (
    # --- Patterns that share substrings with other families -----------------
    # Google FunctionGemma (before gemma — "functiongemma" contains "gemma")
    ("functiongemma", "functiongemma"),  # google/functiongemma-270m-it
    # Google Gemma 4
    ("gemma-4", "gemma4"),
    ("gemma4", "gemma4"),
    # Salesforce xLAM (before llama/qwen — xLAM models may contain those)
    ("xlam", "xlam"),
    # NousResearch Hermes (before llama — Hermes-Llama models exist)
    ("hermes", "hermes"),
    # Meta Llama (4 before 3)
    ("llama-4", "llama4_pythonic"),
    ("llama4", "llama4_pythonic"),
    ("llama-3", "llama3_json"),
    ("llama3", "llama3_json"),
    # Mistral / Mixtral
    ("mistral", "mistral"),
    ("mixtral", "mistral"),
    # DeepSeek (specific versions before general; R1 also uses deepseek_v3)
    ("deepseek-v3.2", "deepseek_v32"),
    ("deepseek-v3.1", "deepseek_v31"),
    ("deepseek", "deepseek_v3"),
    # IBM Granite (specific before general)
    ("granite-20b-functioncalling", "granite-20b-fc"),
    ("granite-20b-fc", "granite-20b-fc"),
    ("granite-4", "granite4"),
    ("granite4", "granite4"),
    ("granite", "granite"),
    # Zhipu GLM (4.7 before 4 — "glm-4" is a prefix of "glm-4.7")
    ("glm-4.7", "glm47"),
    ("glm47", "glm47"),
    ("glm-4", "glm45"),  # also covers GLM-4.5 and GLM-4.6
    ("glm4", "glm45"),
    # Shanghai AI Lab InternLM
    ("internlm", "internlm"),
    # AI21 Labs Jamba
    ("jamba", "jamba"),
    # Alibaba Qwen.  vLLM registers "qwen3_coder" and "qwen3_xml" as two names
    # for the same Qwen3EngineToolParser; "qwen3_coder" is the one vLLM's own
    # deployment recipes name, so it is the one used here.
    ("qwen3-coder", "qwen3_coder"),
    ("qwen3_coder", "qwen3_coder"),
    # Qwen3 point releases (3.5, 3.6, 3.8, …) emit the same XML dialect as
    # Qwen3-Coder, not the JSON-in-<tool_call> that hermes expects: their
    # bundled chat templates render '<tool_call>\n<function=NAME>\n<parameter=…>'
    # verbatim.  This rule has to sit above the "qwen3-"/"qwen3_" entries,
    # which never matched a dotted name and so let every point release fall
    # through to the generic ("qwen", "hermes") catch-all — hermes then failed
    # to parse the XML and vLLM returned the raw markup as assistant text.
    ("qwen3.", "qwen3_coder"),
    # Qwen3 (dot-free, e.g. Qwen3-32B) still emits hermes-style JSON.
    ("qwen3-", "hermes"),
    ("qwen3_", "hermes"),
    ("qwen", "hermes"),
    # MiniMax (m2 before general)
    ("minimax-m2", "minimax_m2"),
    ("minimax_m2", "minimax_m2"),
    ("minimax", "minimax"),
    # Microsoft Phi
    ("phi-4-mini", "phi4_mini_json"),
    ("phi4mini", "phi4_mini_json"),
    # Allen AI OLMo
    ("olmo-3", "olmo3"),
    ("olmo3", "olmo3"),
    # Tencent Hunyuan
    ("hunyuan-a13b", "hunyuan_a13b"),
    ("hunyuan_a13b", "hunyuan_a13b"),
    ("hunyuan", "hunyuan_a13b"),
    # Baidu ERNIE
    ("ernie-4.5", "ernie45"),
    ("ernie45", "ernie45"),
    ("ernie", "ernie45"),
    # Moonshot Kimi
    ("kimi-k2", "kimi_k2"),
    ("kimi_k2", "kimi_k2"),
    ("kimi", "kimi_k2"),
    # ByteDance Seed
    ("seed-oss", "seed_oss"),
    ("seed_oss", "seed_oss"),
    # StepFun (3.5 before 3 — "step-3" is a prefix of "step-3.5")
    ("step-3.5", "step3p5"),
    ("step3p5", "step3p5"),
    ("step-3", "step3"),
    ("step3", "step3"),
    # Sber GigaChat
    ("gigachat", "gigachat3"),
    # Meituan LongCat
    ("longcat", "longcat"),
    # Xiaomi MIMO
    ("mimo", "mimo"),
    # OpenAI OSS (gpt-oss-20b, gpt-oss-120b)
    ("gpt-oss", "openai"),
)

# Model-name → vLLM --reasoning-parser mapping.  Checked in order; first match
# wins.  Patterns are lowercased substrings of the HF model id.
# Registered parser names sourced directly from vllm/reasoning/__init__.py
# (_REASONING_PARSERS_TO_REGISTER dict) — these are the only valid values.
_REASONING_PARSER_RULES: tuple[tuple[str, str], ...] = (
    ("gemma-4", "gemma4"),
    ("gpt-oss", "openai_gptoss"),
    # Qwen3 point releases think by default.  Without a reasoning parser the
    # <think> block is returned inline in the assistant message instead of in
    # reasoning_content, so clients render it as the answer.  Only the dotted
    # releases are mapped: dot-free Qwen3 predates the parser.
    ("qwen3.", "qwen3"),
)

# Model-name → default --default-chat-template-kwargs mapping.  Applied as a
# base layer; explicit vllm_config.chat_template_kwargs keys win on a per-key
# basis (merge, not replace).
_DEFAULT_CHAT_TEMPLATE_KWARGS_RULES: tuple[tuple[str, dict[str, Any]], ...] = (
    # Google Gemma 4 — thinking is opt-in via chat template
    ("gemma-4", {"enable_thinking": True}),
)


def _infer_reasoning_parser(model: str) -> str | None:
    """Infer the vLLM --reasoning-parser value from the model name.

    Returns the parser name when the model is a known reasoning model, or
    ``None`` when no rule matches (no flag should be emitted).
    """
    model_lower = model.lower()
    for pattern, parser in _REASONING_PARSER_RULES:
        if pattern in model_lower:
            return parser
    return None


def _infer_default_chat_template_kwargs(model: str) -> dict[str, Any]:
    """Infer the default chat-template-kwargs dict from the model name.

    Returns the first matching dict, or ``{}`` when nothing matches.
    The caller should merge (overlay) any explicit user-supplied kwargs on top.
    """
    model_lower = model.lower()
    for pattern, kwargs in _DEFAULT_CHAT_TEMPLATE_KWARGS_RULES:
        if pattern in model_lower:
            return dict(kwargs)  # shallow copy so callers can mutate safely
    return {}


def _infer_tool_call_parser(model: str) -> str:
    """Infer the vLLM tool-call-parser from the model name.

    vLLM requires an explicit ``--tool-call-parser`` value when
    ``--enable-auto-tool-choice`` is set (no built-in auto-detect yet).
    Falls back to ``hermes`` which is broadly compatible.

    TODO: vLLM draft PR adds ``--tool-call-parser=auto`` which would make
    this function obsolete. Check if merged and remove this workaround:
    https://github.com/vllm-project/vllm/pull/34809
    """
    model_lower = model.lower()
    for pattern, parser in _TOOL_PARSER_RULES:
        if pattern in model_lower:
            return parser
    return "hermes"


# -----------------------------------------------------------------------------
# Custom chat templates
# -----------------------------------------------------------------------------


# Persistent, operator-managed directory holding custom Jinja chat templates.
# It matches the host-side compose directory (/opt/logos-workernode) so the
# same path is valid on the host and inside the container, and it is bind-
# mounted read-only by docker-compose.yml. Overridable for local dev and tests.
_DEFAULT_CHAT_TEMPLATE_DIR = "/opt/logos-workernode/chat-templates"


def _chat_template_dir() -> str:
    """Directory custom chat templates are resolved against."""
    return (os.environ.get("LOGOS_CHAT_TEMPLATE_DIR") or "").strip() or _DEFAULT_CHAT_TEMPLATE_DIR


def _resolve_chat_template(value: str) -> str:
    """Resolve a configured chat template to an absolute file path.

    ``value`` is a file name (optionally with subdirectories) relative to the
    persistent chat-template directory; an absolute path is accepted only when
    it points inside that directory. Symlinks are followed and the resolved
    target must still be contained, so a template can never be served from a
    location that a container restart would wipe.

    Raises ``RuntimeError`` when the value escapes the directory or the file
    does not exist — a lane must fail loudly rather than silently fall back to
    the model's bundled template, which would change generation behaviour
    without any visible error.
    """
    base = os.path.realpath(_chat_template_dir())
    candidate = os.path.join(base, value) if not os.path.isabs(value) else value
    resolved = os.path.realpath(candidate)
    if resolved != base and not resolved.startswith(base + os.sep):
        raise RuntimeError(
            f"chat_template {value!r} resolves to {resolved!r}, which is outside the "
            f"persistent chat-template directory {base!r}. Place the template there "
            "and reference it by file name."
        )
    if not os.path.isfile(resolved):
        raise RuntimeError(
            f"chat_template {value!r} not found at {resolved!r}. Templates are read from "
            f"{base!r} (bind-mounted from the host); add the file there and restart the lane."
        )
    return resolved


# -----------------------------------------------------------------------------
# Fatal load-error signatures (vLLM/HF error text)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class FatalLoadErrorPattern:
    """A vLLM log signature that proves the model can never load on this worker.

    Matched as a substring against the vLLM log tail captured after a probe
    failure. Case-sensitive — vLLM's own error strings are stable, so
    fuzzy-matching is unnecessary and just invites false positives.
    """

    needle: str
    reason_code: str  # short, kebab-case; surfaced in logs and the persisted file
    description: str  # human-readable, shown to ops in the file and in error responses


_FATAL_LOAD_ERROR_PATTERNS: tuple[FatalLoadErrorPattern, ...] = (
    FatalLoadErrorPattern(
        needle="Invalid repository ID or local directory specified",
        reason_code="invalid-repo-id",
        description=(
            "vLLM cannot resolve the model name to either a Hugging Face "
            "repository or a local directory containing config.json. The "
            "identifier is misspelled, the repository is private/withdrawn, "
            "or the local directory is missing config.json / params.json."
        ),
    ),
    FatalLoadErrorPattern(
        needle="Cannot access gated repo",
        reason_code="gated-repo-no-token",
        description=(
            "Hugging Face flags this repository as gated. The worker has no "
            "HF token (or the token lacks access). Fix by adding a "
            "HUGGING_FACE_HUB_TOKEN with read access to the repo before "
            "removing this entry."
        ),
    ),
    FatalLoadErrorPattern(
        needle="does not recognize this architecture",
        reason_code="unsupported-architecture",
        description=(
            "The installed vLLM build does not implement this model's "
            "architecture. Upgrade vLLM (and remove this entry) if support "
            "has been added since this worker was deployed."
        ),
    ),
)


# -----------------------------------------------------------------------------
# vLLM log-format regexes and their extractors
# -----------------------------------------------------------------------------


# vLLM raises a specific ValueError when the configured KV cache budget is too
# small to serve a single request at the model's default max_seq_len, e.g.::
#
#     ValueError: To serve at least one request with the model's max seq len
#     (131072), (8.0 GiB KV cache is needed, which is larger than the available
#     KV cache memory (6.0 GiB). Based on the available memory, the estimated
#     maximum model length is 98304.
#
# This is recoverable WITHOUT enlarging the KV budget: pass --max-model-len at
# the suggested value (or below). The calibration probe loop uses this helper
# to extract the number and auto-retry the same kv_mb with the suggestion
# injected, instead of blacklisting the command and failing the model.
_VLLM_MAX_MODEL_LEN_SUGGESTION_RE = re.compile(r"estimated maximum model length is (\d+)")
_VLLM_MAX_SEQ_LEN_RE = re.compile(r"max seq len \((\d+)\)")
_VLLM_MAX_MODEL_LEN_CONFIG_RE = re.compile(r"max_model_len\s*[=:]\s*(\d+)")
# "... the model's max seq len (131072), 8.94 GiB KV cache is needed ..." — the
# KV required to serve the model's FULL context. With the max seq len this gives
# the KV→context rate, letting the sweep COMPUTE the curve instead of crawling.
_VLLM_KV_GIB_NEEDED_RE = re.compile(r"([\d.]+)\s*GiB KV cache is needed")


def _extract_vllm_kv_gib_needed_for_full(log_tail: str) -> float | None:
    """GiB of KV cache vLLM says it needs to serve the model's full max seq len."""
    m = _VLLM_KV_GIB_NEEDED_RE.search(log_tail)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _extract_vllm_max_model_len_suggestion(log_tail: str) -> int | None:
    """Return vLLM's suggested ``--max-model-len`` when the KV budget is too
    small for the model's default max_seq_len, otherwise None.
    """
    if not log_tail:
        return None
    m = _VLLM_MAX_MODEL_LEN_SUGGESTION_RE.search(log_tail)
    if not m:
        return None
    try:
        value = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _extract_vllm_max_seq_len(log_tail: str, *, allow_config_fallback: bool = True) -> int | None:
    """Return the model's default max seq len mentioned by vLLM, if present.

    This appears in KV-too-small startup failures and lets calibration record
    the plateau ``max_model_len`` once the default fits again.

    ``allow_config_fallback=False`` restricts the search to the authoritative
    "max seq len (N)" phrasing of vLLM's KV-too-small ValueError and skips the
    ``max_model_len=N`` config-dump fallback. Callers MUST pass False whenever
    calibration itself injected ``--max-model-len`` for the probe being parsed:
    the config dump then echoes OUR OWN injected value, so treating it as the
    model default silently pins the whole sweep to the floor probe's shrunken
    context (deipapa/deimama 2026-08-18: Qwen3.8-27B recorded a flat 27440
    curve although probes at 10-20G served the model's full 262144).
    """
    if not log_tail:
        return None
    m = _VLLM_MAX_SEQ_LEN_RE.search(log_tail)
    if not m and allow_config_fallback:
        m = _VLLM_MAX_MODEL_LEN_CONFIG_RE.search(log_tail)
    if not m:
        return None
    try:
        value = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


# Hybrid Mamba/SSM models (Qwen3-Coder-Next, …) allocate a fixed pool of
# state-cache blocks sized from the leftover VRAM after weights + KV. Each
# in-flight decode sequence needs one block, so when max_num_seqs (vLLM's
# default 1024) exceeds the pool, CUDA-graph capture aborts at startup with:
#
#     RuntimeError: ... 'max_num_seqs (1024) exceeds available Mamba cache
#     blocks (160). Each decode sequence requires one Mamba cache block, so
#     CUDA graph capture cannot proceed. Please lower max_num_seqs to at most
#     160 or increase gpu_memory_utilization.'
#
# Recoverable by passing --max-num-seqs at (or below) the suggested ceiling.
# The probe loop extracts the number and auto-retries the same kv_mb with the
# flag injected, instead of blacklisting the command and failing the model.
_VLLM_MAX_NUM_SEQS_SUGGESTION_RE = re.compile(r"lower max_num_seqs to at most (\d+)")


def _extract_vllm_max_num_seqs_suggestion(log_tail: str) -> int | None:
    """Return vLLM's suggested ``--max-num-seqs`` ceiling when a hybrid
    Mamba/SSM model's state-cache pool is smaller than max_num_seqs, else None.
    """
    if not log_tail:
        return None
    m = _VLLM_MAX_NUM_SEQS_SUGGESTION_RE.search(log_tail)
    if not m:
        return None
    try:
        value = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


# vLLM prints the achievable concurrency at every engine init, e.g.
#   "Maximum concurrency for 33,888 tokens per request: 2.00x"
# This is total_kv_cache_tokens / max_model_len — i.e. how many simultaneous
# full-context requests the KV pool can serve. We read it back (rather than
# pinning --max-num-seqs) to record the "parallelity factor" of each KV point.
_VLLM_MAX_CONCURRENCY_RE = re.compile(r"Maximum concurrency for ([\d,]+) tokens per request:\s*([\d.]+)x")


def _extract_vllm_max_concurrency(log_tail: str) -> float | None:
    """Return vLLM's reported achievable concurrency (the ``X.XXx`` factor), else None.

    Uses the LAST occurrence in the log so a re-probe at a different KV size
    reflects the final successful load rather than an earlier attempt.
    """
    if not log_tail:
        return None
    matches = _VLLM_MAX_CONCURRENCY_RE.findall(log_tail)
    if not matches:
        return None
    try:
        value = float(matches[-1][1])
    except (TypeError, ValueError, IndexError):
        return None
    return value if value > 0 else None


def _extract_vllm_served_context(log_tail: str) -> int | None:
    """Return the context length vLLM actually loaded, from the same line.

    "Maximum concurrency for 262,144 tokens per request: 2.21x" names the
    engine's resolved ``max_model_len``, printed on every successful init. It
    is the ONLY authoritative answer to "what did this probe really serve" —
    a probe that starts without an injected ``--max-model-len`` carries no
    suggestion and no fresh config echo, so without this the sweep has to fall
    back to a cached model-default and can attribute the floor probe's
    shrunken context to every larger KV size (see ``_extract_vllm_max_seq_len``).

    Uses the LAST occurrence so retries within one probe report the final load.
    """
    if not log_tail:
        return None
    matches = _VLLM_MAX_CONCURRENCY_RE.findall(log_tail)
    if not matches:
        return None
    try:
        value = int(matches[-1][0].replace(",", ""))
    except (TypeError, ValueError, IndexError):
        return None
    return value if value > 0 else None


# -----------------------------------------------------------------------------
# vLLM /metrics name spellings
# -----------------------------------------------------------------------------


# The names vLLM exposes on its native /metrics endpoint drift between
# versions: the ``prefix_cache_hit_rate`` gauge predates 0.20 (where it was
# replaced by ``gpu_prefix_cache_{queries,hits}`` counters), and both
# ``*_perc`` and ``*_percent`` spellings of the cache-usage gauge exist
# across releases. ``get_backend_metrics`` matches every known spelling; add
# new ones here when a vLLM upgrade renames a metric. Single strings and
# tuples alike match via ``str.endswith``.

_VLLM_METRIC_QUEUE_WAITING = "num_requests_waiting"
_VLLM_METRIC_REQUESTS_RUNNING = "num_requests_running"
_VLLM_METRIC_GPU_CACHE_USAGE = (
    "gpu_cache_usage_perc",
    "gpu_cache_usage_percent",
    "kv_cache_usage_perc",
    "kv_cache_usage_percent",
)
# Legacy gauge (vLLM < 0.20); kept for backward compatibility.
_VLLM_METRIC_PREFIX_CACHE_HIT_RATE_LEGACY = "prefix_cache_hit_rate"
_VLLM_METRIC_PREFIX_CACHE_QUERIES = (
    "gpu_prefix_cache_queries",
    "gpu_prefix_cache_queries_total",
    ":prefix_cache_queries_total",
    ":prefix_cache_queries",
)
_VLLM_METRIC_PREFIX_CACHE_HITS = (
    "gpu_prefix_cache_hits",
    "gpu_prefix_cache_hits_total",
    ":prefix_cache_hits_total",
    ":prefix_cache_hits",
)
# vLLM speculative decoding (e.g. MTP draft heads): cumulative tokens
# proposed / accepted by the draft model.
_VLLM_METRIC_SPEC_DRAFT_TOKENS = (
    "spec_decode_num_draft_tokens",
    "spec_decode_num_draft_tokens_total",
)
_VLLM_METRIC_SPEC_ACCEPTED_TOKENS = (
    "spec_decode_num_accepted_tokens",
    "spec_decode_num_accepted_tokens_total",
)
_VLLM_METRIC_PROMPT_TOKENS_TOTAL = "prompt_tokens_total"
_VLLM_METRIC_GENERATION_TOKENS_TOTAL = "generation_tokens_total"
# Histogram buckets are matched as substrings (the bucket sample line also
# carries the ``le="..."`` label, so a bare-name endswith would miss it).
_VLLM_METRIC_TTFT_BUCKET = "time_to_first_token_seconds_bucket"
_VLLM_METRIC_TTFT_SUM = "time_to_first_token_seconds_sum"
_VLLM_METRIC_TTFT_COUNT = "time_to_first_token_seconds_count"
_VLLM_METRIC_TPOT_BUCKET = "time_per_output_token_seconds_bucket"
_VLLM_METRIC_TPOT_SUM = "time_per_output_token_seconds_sum"
_VLLM_METRIC_TPOT_COUNT = "time_per_output_token_seconds_count"
_VLLM_METRIC_E2E_LATENCY_BUCKET = "e2e_request_latency_seconds_bucket"


# -----------------------------------------------------------------------------
# vLLM process / installation plumbing
# -----------------------------------------------------------------------------


# Distributed-launch env vars that must not leak into the vLLM subprocess -
# a leftover RANK/WORLD_SIZE pair makes vLLM think it is one rank of a
# multi-node job.
_SCRUBBED_ENV_VARS = (
    "LOCAL_RANK",
    "RANK",
    "WORLD_SIZE",
    "LOCAL_WORLD_SIZE",
    "NODE_RANK",
    "MASTER_ADDR",
    "MASTER_PORT",
)

# Default vLLM binary name (resolved through PATH when no absolute path is
# configured).
_DEFAULT_VLLM = "vllm"

# File the Dockerfile bakes next to the venv's bin/ listing the quantization
# method names the installed vLLM recognizes (see
# ``query_vllm_quantization_methods`` in calibration.py).
_BAKED_QUANT_METHODS_FILENAME = "vllm_quantization_methods.json"

# vLLM dev-mode banner lines (VLLM_SERVER_DEV_MODE is required for the
# sleep/wake endpoints we use); suppress them from the lane log stream.
_VLLM_DEV_MODE_LOG_FRAGMENTS: tuple[str, ...] = ("SECURITY WARNING: Development endpoints are enabled",)
