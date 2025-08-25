import yaml
from pathlib import Path
from functools import lru_cache

CONFIG_PATH = Path(__file__).resolve().parents[2] / "llm_capabilities.yml"

@lru_cache(maxsize=1)
def _load_caps() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

def get_model_capabilities(model_key: str) -> dict:
    config = _load_caps()
    defaults = config.get("defaults", {})
    overrides = config.get("models", {}).get(model_key, {})
    return {**defaults, **overrides}