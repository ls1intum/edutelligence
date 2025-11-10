import os

import yaml
from openai import AzureOpenAI, OpenAI


def load_llm_config(model: str, filename: str = "llm_config.nebula.yml"):
    """Load LLM configuration from a YAML file."""
    config_path = os.getenv("LLM_CONFIG_PATH")
    if not config_path:
        this_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.abspath(
            os.path.join(this_dir, "..", "..", "..", filename)
        )

    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"LLM config file not found at: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    for entry in config:
        if entry.get("model") == model:
            return entry

    raise ValueError(f"LLM config with model '{model}' not found.")


def get_openai_client(model: str = "gpt-4.1"):
    """
    Create and return an OpenAI or AzureOpenAI client, plus the model/deployment name.
    """
    config = load_llm_config(model=model)
    llm_type = config.get("type")

    if llm_type == "azure_chat":
        return (
            AzureOpenAI(
                azure_endpoint=config["endpoint"],
                azure_deployment=config["azure_deployment"],
                api_key=config["api_key"],
                api_version=config["api_version"],
            ),
            config["azure_deployment"],
        )

    if llm_type == "openai_chat":
        return OpenAI(api_key=config["api_key"]), config["model"]

    raise ValueError(f"Unsupported OpenAI LLM config type: {llm_type}")
