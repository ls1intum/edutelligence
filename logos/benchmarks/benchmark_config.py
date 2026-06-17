"""
Benchmark configuration — edit this file to change models and settings.

Used by both prepare_benchmark.py (to assign models to requests) and
benchmark_logos.py (to translate Logos model names to Ollama tags).
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

# ── Ollama model name mapping ─────────────────────────────────────────────
# Maps Logos model identifiers → Ollama pull tags.
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

GSM8K_MAX_TOKENS: int = 512
