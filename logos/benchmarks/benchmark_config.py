"""
Benchmark configuration — edit this file to change models and settings.

Used by both prepare_benchmark.py (to assign models to requests) and
benchmark_anontool.py (to translate AnonTool model names to Ollama tags).
"""

# ── LLM configurations ────────────────────────────────────────────────────
# These are the model identifiers as registered inside AnonTool.

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

# ── Ollama model name mapping ─────────────────────────────────────────────
# Maps AnonTool model identifiers → Ollama pull tags.
# Verify exact tag names on the target machine with: ollama list
OLLAMA_MODEL_MAP: dict[str, str] = {
    "Qwen/Qwen3.6-35B-A3B": "qwen3.6:35b",
    "meta-llama/Llama-3.1-8B-Instruct": "llama3.1:8b",
    "google/gemma-3-12b-it": "gemma3:12b-it-qat",
    "microsoft/Phi-4-reasoning": "phi4-reasoning:latest",  # verify tag
    "google/gemma-3-4b-it": "gemma3:4b-it-qat",  # verify tag
}

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
