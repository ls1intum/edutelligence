"""
Benchmark configuration — edit this file to change models and settings.

Used by prepare_benchmark.py to assign models to requests.
"""

# ── LLM configurations ────────────────────────────────────────────────────
# These are the model identifiers as registered inside Logos.

# Two-LLM configuration (small comparison)
MODELS_2: list[str] = [
    "Qwen/Qwen3.6-35B-A3B",
    "google/gemma-3-4b-it",
]

# Five-LLM configuration (full comparison)
MODELS_5: list[str] = [
    "Qwen/Qwen3.6-35B-A3B",
    "meta-llama/Llama-3.1-8B-Instruct",
    "google/gemma-3-12b-it",
    "microsoft/Phi-4-reasoning",
    "google/gemma-3-4b-it",
]

# ── GSM8K prompt settings ─────────────────────────────────────────────────

GSM8K_SYSTEM_PROMPT: str = (
    "You are a helpful math tutor. "
    "Solve the given math problem step by step. "
    "End your response with '#### <number>' where <number> is the final numeric answer."
)

# No completion-token limit by default. A hard cap (the old 512) silently
# truncated answers — reasoning models in particular never reached the
# "#### <number>" line, and completion_tokens pinned to exactly the cap. None
# means "send no max_tokens at all"; the backend decides when to stop.
# Set a positive int here only if you deliberately want to bound generation.
GSM8K_MAX_TOKENS: int | None = None
