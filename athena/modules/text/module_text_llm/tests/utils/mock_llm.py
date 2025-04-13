"""Mock language model implementations for testing the text LLM module."""

from pydantic import BaseModel, Field
from typing import Any, List, Optional, Callable, Type
from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.runnables import RunnableConfig
from langchain_core.prompt_values import PromptValue
from langchain_core.messages import BaseMessage
from module_text_llm.basic_approach.prompt_generate_suggestions import AssessmentModel as RealAssessmentModel

class MockFeedbackModel(BaseModel):
    """Mock feedback model for testing."""
    title: str = "Test Feedback"
    description: str = "Test description"
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    credits: float = 0.0
    grading_instruction_id: Optional[int] = None

class AssessmentModel(BaseModel):
    """Mock assessment model containing feedback items."""
    feedbacks: List[MockFeedbackModel] = Field(default_factory=lambda: [MockFeedbackModel()])

class StructuredMockLanguageModel(BaseLanguageModel):
    """Mock language model with structured output support."""
    return_value: Any = Field(default_factory=lambda: None)

    def __init__(self, return_value: Any = None):
        super().__init__()
        if return_value is not None:
            self.return_value = return_value

    async def ainvoke(self, input: Any, config: Optional[RunnableConfig] = None, **kwargs: Any) -> Any:
        return self.return_value

    async def agenerate_prompt(self, prompts: List[PromptValue], stop: Optional[List[str]] = None, **kwargs: Any) -> Any:
        return [self.return_value]

    async def apredict(self, text: str, stop: Optional[List[str]] = None, **kwargs: Any) -> str:
        return str(self.return_value)

    async def apredict_messages(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs: Any) -> str:
        return str(self.return_value)

    def generate_prompt(self, prompts: List[PromptValue], stop: Optional[List[str]] = None, **kwargs: Any) -> Any:
        return [self.return_value]

    def invoke(self, input: Any, config: Optional[RunnableConfig] = None, **kwargs: Any) -> Any:
        return self.return_value

    def predict(self, text: str, stop: Optional[List[str]] = None, **kwargs: Any) -> str:
        return str(self.return_value)

    def predict_messages(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs: Any) -> str:
        return str(self.return_value)

class MockLanguageModel(BaseLanguageModel):
    """Mock language model for testing feedback generation."""
    return_value: Any = Field(default_factory=lambda: None)

    def __init__(self, return_value: Any = None):
        super().__init__()
        if return_value is not None:
            self.return_value = return_value

    async def ainvoke(self, input: Any, config: Optional[RunnableConfig] = None, **kwargs: Any) -> Any:
        if isinstance(self.return_value, AssessmentModel):
            return RealAssessmentModel(feedbacks=self.return_value.feedbacks)
        return self.return_value

    def with_structured_output(self, cls: Type[BaseModel]) -> Any:
        """Return a mock that will return the structured output directly."""
        return self

    async def agenerate_prompt(self, prompts: List[PromptValue], stop: Optional[List[str]] = None, **kwargs: Any) -> Any:
        return [self.return_value]

    async def apredict(self, text: str, stop: Optional[List[str]] = None, **kwargs: Any) -> str:
        return str(self.return_value)

    async def apredict_messages(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs: Any) -> str:
        return str(self.return_value)

    def generate_prompt(self, prompts: List[PromptValue], stop: Optional[List[str]] = None, **kwargs: Any) -> Any:
        return [self.return_value]

    def invoke(self, input: Any, config: Optional[RunnableConfig] = None, **kwargs: Any) -> Any:
        if isinstance(self.return_value, AssessmentModel):
            return RealAssessmentModel(feedbacks=self.return_value.feedbacks)
        return self.return_value

    def predict(self, text: str, stop: Optional[List[str]] = None, **kwargs: Any) -> str:
        return str(self.return_value)

    def predict_messages(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs: Any) -> str:
        return str(self.return_value)
