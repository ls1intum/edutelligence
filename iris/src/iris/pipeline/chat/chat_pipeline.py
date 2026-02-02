import os
from enum import StrEnum, auto
from typing import Any, Callable, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from iris.domain import ChatPipelineExecutionDTO
from iris.domain.variant.chat_variant import ChatVariant
from iris.pipeline.abstract_agent_pipeline import (
    DTO,
    VARIANT,
    AbstractAgentPipeline,
    AgentPipelineExecutionState,
)
from iris.pipeline.chat.code_feedback_pipeline import CodeFeedbackPipeline
from iris.pipeline.chat.interaction_suggestion_pipeline import (
    InteractionSuggestionPipeline,
)
from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)
from iris.pipeline.shared.citation_pipeline import CitationPipeline
from iris.retrieval.faq_retrieval import FaqRetrieval
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval


class ChatContext(StrEnum):
    COURSE = auto()
    LECTURE = auto()
    EXERCISE = auto()
    TEXT_EXERCISE = auto()


class ChatPipeline(AbstractAgentPipeline[ChatPipelineExecutionDTO, ChatVariant]):
    """
    Replaces CourseChatPipeline / ExerciseChatPipeline / TextExerciseChatPipeline / LectureChatPipeline
    """

    # Shared
    context: ChatContext
    session_title_pipeline: SessionTitleGenerationPipeline
    citation_pipeline: CitationPipeline
    jinja_env: Environment
    system_prompt_template: Any

    # Context-Specific
    lecture_retriever: Optional[LectureRetrieval]
    faq_retriever: Optional[FaqRetrieval]
    suggestion_pipeline: Optional[InteractionSuggestionPipeline]
    event: Optional[str]
    code_feedback_pipeline: Optional[CodeFeedbackPipeline]
    guide_prompt_template: Any  # TODO: Remove ?

    def __init__(
        self,
        context: ChatContext,
        event: Optional[str] = None,
    ):
        super().__init__(implementation_id="chat_pipeline")

        self.context = context

        self.event = None

        # Initialize pipelines & retrievers
        self.session_title_pipeline = SessionTitleGenerationPipeline()
        self.citation_pipeline = CitationPipeline()
        self.suggestion_pipeline = None
        self.code_feedback_pipeline = None
        self.lecture_retriever = None
        self.faq_retriever = None

        # Setup Jinja2 template environment
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates"
        )
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir), autoescape=select_autoescape(["j2"])
        )
        self.system_prompt_template = self.jinja_env.get_template(
            "chat_system_prompt.j2"
        )
        self.guide_prompt_template = None

        # Setup context-specific components
        if self.context == ChatContext.COURSE:
            self.suggestion_pipeline = InteractionSuggestionPipeline(
                variant=self.context
            )
            self.event = event

        elif self.context == ChatContext.EXERCISE:
            self.suggestion_pipeline = InteractionSuggestionPipeline(
                variant=self.context
            )
            self.code_feedback_pipeline = CodeFeedbackPipeline()
            self.guide_prompt_template = self.jinja_env.get_template(
                "exercise_chat_guide_prompt.j2"
            )

    @classmethod
    def get_variants(cls) -> List[ChatVariant]:
        # TODO: Instance method statt class method ? Parameter ? Alle 8 zurückgeben ?
        pass

    def get_memiris_reference(self, dto: DTO):
        pass

    def get_memiris_tenant(self, dto: DTO) -> str:
        pass

    def build_system_message(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> str:
        pass

    def get_tools(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> list[Callable]:
        pass

    def is_memiris_memory_creation_enabled(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> bool:
        pass
