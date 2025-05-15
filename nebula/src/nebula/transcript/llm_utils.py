import os
import yaml
from openai import AzureOpenAI


def load_llm_config(filename="llm_config.nebula.yml", llm_id="azure-gpt-4-omni"):
    """Load LLM configuration from a YAML file."""
    config_path = os.getenv("LLM_CONFIG_PATH")
    if not config_path:
        this_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.abspath(os.path.join(this_dir, "..", filename))

    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"LLM config file not found at: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    for entry in config:
        if entry.get("id") == llm_id:
            return entry

    raise ValueError(f"LLM config with ID '{llm_id}' not found.")


def get_openai_client(llm_id="azure-gpt-4-omni"):
    """Return an AzureOpenAI client and deployment name."""
    config = load_llm_config(llm_id=llm_id)

    client = AzureOpenAI(
        azure_endpoint=config["endpoint"],
        azure_deployment=config["azure_deployment"],
        api_version=config["api_version"],
        api_key=config["api_key"],
    )
    return client, config["azure_deployment"]


def get_azure_whisper_config(llm_id="azure-whisper"):
    config = load_llm_config(llm_id=llm_id)
    return config
