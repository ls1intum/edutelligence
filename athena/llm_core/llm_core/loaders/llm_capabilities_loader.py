import os
import yaml
from pathlib import Path
from typing import Dict


CONFIG_PATH = Path(__file__).resolve().parents[2] / "llm_capabilities.yml"
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        _yaml_config = yaml.safe_load(f)
else:
    _yaml_config = {}

DEFAULTS = _yaml_config.get("defaults", {})
MODEL_OVERRIDES = _yaml_config.get("models", {})


def get_model_capabilities(model_key: str) -> Dict:
    """
    Return the merged dictionary of defaults and overrides 
    for the given model key.
    """
    caps = dict(DEFAULTS)  # start with a copy of the defaults
    if model_key in MODEL_OVERRIDES:
        # override with model-specific entries
        for k, v in MODEL_OVERRIDES[model_key].items():
            caps[k] = v
    return caps