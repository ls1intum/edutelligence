import os

import yaml


def load_llm_config(filename="llm_config.nebula.yml", llm_id="azure-gpt-4-omni"):
    """Load LLM configuration from a YAML file."""
    config_path = os.getenv("LLM_CONFIG_PATH")
    if not config_path:
        this_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.abspath(os.path.join(this_dir, "..", "..", "..", filename))

    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"LLM config file not found at: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    for entry in config:
        if entry.get("id") == llm_id:
            return entry

    raise ValueError(f"LLM config with ID '{llm_id}' not found.")
