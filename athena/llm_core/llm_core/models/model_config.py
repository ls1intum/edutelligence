from abc import ABC, abstractmethod
from pydantic import BaseModel
from langchain_core.language_models import BaseLanguageModel


class ModelConfig(BaseModel, ABC):
    """
    Abstract base class representing a general model configuration.
    """

    @abstractmethod
    def get_model(self) -> BaseLanguageModel:
        pass

    @abstractmethod
    def supports_system_messages(self) -> bool:
        """
        Indicates whether this model supports system prompt messages
        (for example, the 'system' role, in gpt4o)
        """
        pass

    @abstractmethod
    def supports_function_calling(self) -> bool:
        """
        Indicates whether this model supports function-calling
        """
        pass

    @abstractmethod
    def supports_structured_output(self) -> bool:
        """
        Indicates whether this model supports producing structured output
        """
        pass

    def structured_output_method(self) -> str:
        """
        The `method` passed to `with_structured_output()` when
        `supports_structured_output()` is True. Providers that need
        schema-constrained decoding instead of generic JSON mode
        (e.g. Ollama) can override this.
        """
        return "json_mode"
