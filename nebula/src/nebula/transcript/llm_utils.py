import os

import yaml
from openai import AzureOpenAI, OpenAI


def load_llm_config(filename="llm_config.nebula.yml", llm_id="azure-gpt-4-omni"):
    """
    Load LLM configuration from a YAML file and return the config for the given ID.
    """
    config_path = os.getenv("LLM_CONFIG_PATH")
    if not config_path:
        this_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.abspath(os.path.join(this_dir, "..", "..", "..", filename))

    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"LLM config file not found at: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config_list = yaml.safe_load(f)

    for entry in config_list:
        if entry.get("id") == llm_id:
            return entry

    raise ValueError(f"LLM config with ID '{llm_id}' not found.")


def get_openai_client(llm_id="azure-gpt-4-omni"):
    """
    Create and return an OpenAI or AzureOpenAI client, plus the model/deployment name.
    """
    config = load_llm_config(llm_id=llm_id)
    llm_type = config.get("type")

    if llm_type == "azure_chat":
        client = AzureOpenAI(
            azure_endpoint=config["endpoint"],
            api_key=config["api_key"],
            api_version=config["api_version"],
        )
        return client, config["azure_deployment"]

    elif llm_type == "openai":
        client = OpenAI(api_key=config["api_key"])
        return client, config["model"]

    else:
        raise ValueError(f"Unsupported LLM config type: {llm_type}")


def get_whisper_config(llm_id="azure-whisper"):
    """
    Return configuration for Whisper transcription (Azure or OpenAI).
    """
    return load_llm_config(llm_id=llm_id)
