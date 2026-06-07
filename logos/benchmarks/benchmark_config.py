"""
Benchmark configuration — edit this file to change models and settings.

Used by both prepare_benchmark.py (to assign models to requests) and
benchmark_logos.py (to translate Logos model names to Ollama tags).
"""

# ── LLM configurations ────────────────────────────────────────────────────
# These are the model identifiers as registered inside Logos.

# Two-LLM configuration (small comparison)
MODELS_2: list[str] = [
    "Qwen3-30B-A3B",
    "Llama-3.3-70B",
]

# Five-LLM configuration (full comparison)
MODELS_5: list[str] = [
    "Qwen3-30B-A3B",
    "Llama-3.3-70B",
    "Gemma3-4B",
    "microsoft/Phi-4-reasoning",
    "Gemma4-26b",
]

# ── Ollama model name mapping ─────────────────────────────────────────────
# Maps Logos model identifiers → Ollama pull tags.
# Verify exact tag names on the target machine with: ollama list
OLLAMA_MODEL_MAP: dict[str, str] = {
    "Qwen3-30B-A3B": "qwen3:30b-a3b",
    "Llama-3.3-70B": "llama3.3:70b",
    "Gemma3-4B": "gemma3:4b",
    "microsoft/Phi-4-reasoning": "phi4-reasoning:latest",  # verify tag
    "Gemma4-26b": "gemma4:27b",  # verify tag
}

# ── GSM8K prompt settings ─────────────────────────────────────────────────

GSM8K_SYSTEM_PROMPT: str = (
    "You are a helpful math tutor. "
    "Solve the given math problem step by step. "
    "End your response with '#### <number>' where <number> is the final numeric answer."
)

GSM8K_MAX_TOKENS: int = 512
