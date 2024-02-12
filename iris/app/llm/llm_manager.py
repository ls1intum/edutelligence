import os

import yaml

from common import Singleton
from llm.wrapper import AbstractLlmWrapper


# TODO: Replace with pydantic in a future PR
def create_llm_wrapper(config: dict) -> AbstractLlmWrapper:
    if config["type"] == "openai":
        from llm.wrapper import OpenAICompletionWrapper

        return OpenAICompletionWrapper(model=config["model"], api_key=config["api_key"])
    elif config["type"] == "azure":
        from llm.wrapper import AzureCompletionWrapper

        return AzureCompletionWrapper(
            id=config["id"],
            name=config["name"],
            description=config["description"],
            model=config["model"],
            endpoint=config["endpoint"],
            azure_deployment=config["azure_deployment"],
            api_version=config["api_version"],
            api_key=config["api_key"],
        )
    elif config["type"] == "openai_chat":
        from llm.wrapper import OpenAIChatCompletionWrapper

        return OpenAIChatCompletionWrapper(
            id=config["id"],
            name=config["name"],
            description=config["description"],
            model=config["model"],
            api_key=config["api_key"],
        )
    elif config["type"] == "azure_chat":
        from llm.wrapper import AzureChatCompletionWrapper

        return AzureChatCompletionWrapper(
            id=config["id"],
            name=config["name"],
            description=config["description"],
            model=config["model"],
            endpoint=config["endpoint"],
            azure_deployment=config["azure_deployment"],
            api_version=config["api_version"],
            api_key=config["api_key"],
        )
    elif config["type"] == "openai_embedding":
        from llm.wrapper import OpenAIEmbeddingWrapper

        return OpenAIEmbeddingWrapper(model=config["model"], api_key=config["api_key"])
    elif config["type"] == "azure_embedding":
        from llm.wrapper import AzureEmbeddingWrapper

        return AzureEmbeddingWrapper(
            id=config["id"],
            name=config["name"],
            description=config["description"],
            model=config["model"],
            endpoint=config["endpoint"],
            azure_deployment=config["azure_deployment"],
            api_version=config["api_version"],
            api_key=config["api_key"],
        )
    elif config["type"] == "ollama":
        from llm.wrapper import OllamaWrapper

        return OllamaWrapper(
            id=config["id"],
            name=config["name"],
            description=config["description"],
            model=config["model"],
            host=config["host"],
        )
    else:
        raise Exception(f"Unknown LLM type: {config['type']}")


class LlmManager(metaclass=Singleton):
    entries: list[AbstractLlmWrapper]

    def __init__(self):
        self.entries = []
        self.load_llms()

    def get_llm_by_id(self, llm_id):
        for llm in self.entries:
            if llm.id == llm_id:
                return llm

    def load_llms(self):
        path = os.environ.get("LLM_CONFIG_PATH")
        if not path:
            raise Exception("LLM_CONFIG_PATH not set")

        with open(path, "r") as file:
            loaded_llms = yaml.safe_load(file)

        self.entries = [create_llm_wrapper(llm) for llm in loaded_llms]
