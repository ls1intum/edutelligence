from openai import AzureOpenAI

from nebula.llm.llm_config import load_llm_config


def get_openai_client(llm_id="azure-gpt-4-omni"):
    config = load_llm_config(llm_id)
    client = AzureOpenAI(
        azure_endpoint=config["endpoint"],
        azure_deployment=config["azure_deployment"],
        api_version=config["api_version"],
        api_key=config["api_key"],
    )
    return client, config["azure_deployment"]


def get_azure_whisper_config(llm_id="azure-whisper"):
    return load_llm_config(llm_id)
