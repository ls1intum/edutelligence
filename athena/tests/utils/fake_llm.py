from typing import Any, Dict, List, Optional, Type
from pydantic import Field, PositiveInt
from langchain_community.chat_models.fake import FakeListChatModel
from langchain_core.messages import BaseMessage
from langchain_core.pydantic_v1 import BaseModel
from llm_core.models.providers.base_chat_model_config import BaseChatModelConfig


class FakeChatModel(FakeListChatModel):
    """
    A fake chat model that supports structured output and captures requests.
    This is a test double that allows us to control LLM responses and inspect inputs.
    """

    requests: List[Dict] = Field(default_factory=list)
    responses: List[Any] = Field(default_factory=list)
    # This will hold the pydantic model for with_structured_output
    pydantic_object: Optional[Type[BaseModel]] = None

    def _call(self, messages: List[BaseMessage], *args, **kwargs) -> str:
        # In a real scenario, this would format the messages into a string.
        # For our fake model, we just need to pop a response.
        # The real magic happens in ainvoke.
        return super()._call(messages, *args, **kwargs)

    async def ainvoke(self, prompt_input: Dict, *args, **kwargs) -> Any:
        """
        Intercepts the call, saves the input, and returns a pre-programmed response.
        """
        self.requests.append(
            {"prompt_input": prompt_input, "args": args, "kwargs": kwargs}
        )
        if not self.responses:
            raise ValueError(
                "FakeChatModel received a request but has no queued responses."
            )

        # Simulate structured output parsing by returning the Pydantic object directly
        response = self.responses.pop(0)
        if self.pydantic_object and not isinstance(response, self.pydantic_object):
            raise TypeError(
                f"Response is not of expected type {self.pydantic_object.__name__}"
            )

        return response

    def with_structured_output(
        self, pydantic_object: Type[BaseModel], **kwargs
    ) -> "FakeChatModel":
        """

        Simulates the .with_structured_output() method of a real LangChain model.
        """
        self.pydantic_object = pydantic_object
        return self  # Return self to allow chaining

    def add_response(self, response: BaseModel):
        """A helper to queue up a Pydantic model as a response."""
        self.responses.append(response)

    def clear(self):
        """Clears requests and responses for the next test."""
        self.requests.clear()
        self.responses.clear()
        self.pydantic_object = None


class FakeModelConfig(BaseChatModelConfig):
    """
    A fake ModelConfig that uses the FakeChatModel.
    We can pass an instance of FakeChatModel to it during test setup.
    It now includes default values for the fields inherited from BaseChatModelConfig.
    """

    # Provide default values for all required fields from the parent class
    max_tokens: PositiveInt = 4000
    temperature: float = 0.0
    top_p: float = 1.0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0

    # Fields specific to our fake implementation
    model_name: str = "fake_model"
    _fake_chat_model: FakeChatModel = Field(default_factory=FakeChatModel)

    def get_model(self) -> FakeChatModel:
        return self._fake_chat_model

    class Config:
        arbitrary_types_allowed = True
