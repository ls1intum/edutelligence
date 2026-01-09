import logging
import os
import traceback
from datetime import datetime
from typing import Any, Callable, List, Optional, cast

import pytz
from jinja2 import Environment, FileSystemLoader, select_autoescape
from iris.tracing import TracingContext, observe

from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)

from ...common.memiris_setup import get_tenant_for_user
from ...common.pyris_message import IrisMessageRole, PyrisMessage
from ...domain.chat.lecture_chat.lecture_chat_pipeline_execution_dto import (
    LectureChatPipelineExecutionDTO,
)
from ...domain.variant.lecture_chat_variant import LectureChatVariant
from ...retrieval.faq_retrieval import FaqRetrieval
from ...retrieval.faq_retrieval_utils import should_allow_faq_tool
from ...retrieval.lecture.lecture_retrieval import LectureRetrieval
from ...retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from ...tools import (
    create_tool_faq_content_retrieval,
    create_tool_get_course_details,
    create_tool_lecture_content_retrieval,
)
from ...web.status.status_update import LectureChatCallback
from ..abstract_agent_pipeline import AbstractAgentPipeline, AgentPipelineExecutionState
from ..shared.citation_pipeline import CitationPipeline, InformationType
from ..shared.utils import datetime_to_string, format_custom_instructions

logger = logging.getLogger(__name__)


class LectureChatPipeline(
    AbstractAgentPipeline[LectureChatPipelineExecutionDTO, LectureChatVariant]
):
    """
    Lecture chat pipeline that answers course related questions from students.
    """

    session_title_pipeline: SessionTitleGenerationPipeline
    citation_pipeline: CitationPipeline
    lecture_retriever: Optional[LectureRetrieval]
    faq_retriever: Optional[FaqRetrieval]
    jinja_env: Environment
    system_prompt_template: Any

    def __init__(self):
        super().__init__(implementation_id="lecture_chat_pipeline")
        self.session_title_pipeline = SessionTitleGenerationPipeline()
        self.citation_pipeline = CitationPipeline()
        self.lecture_retriever = None
        self.faq_retriever = None
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates"
        )
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml", "j2"]),
        )
        self.system_prompt_template = self.jinja_env.get_template(
            "lecture_chat_system_prompt.j2"
        )

    # event (see course) does not exist here
    # model (see old version) is in the abstract super class now
    def __repr__(self):
        return f"{self.__class__.__name__}()"

    def __str__(self):
        return f"{self.__class__.__name__}()"

    def is_memiris_memory_creation_enabled(
        self,
        state: AgentPipelineExecutionState[
            LectureChatPipelineExecutionDTO, LectureChatVariant
        ],
    ) -> bool:
        """
        Return True if background memory creation should be enabled for this run.

        Returns:
            bool: True if memory creation is enabled
        """
        return bool(state.dto.user and state.dto.user.memiris_enabled)

    def get_tools(
        self,
        state: AgentPipelineExecutionState[
            LectureChatPipelineExecutionDTO, LectureChatVariant
        ],
    ) -> list[Callable]:
        """
        Get the tools available for the agent pipeline.

        Returns:
            list[Callable]: A list of tools available for the agent pipeline
        """
        allow_lecture_tool = should_allow_lecture_tool(state.db, state.dto.course.id)
        allow_faq_tool = should_allow_faq_tool(state.db, state.dto.course.id)
        allow_memiris_tool = bool(
            state.dto.user
            and state.dto.user.memiris_enabled
            and state.memiris_wrapper
            and state.memiris_wrapper.has_memories()
        )

        if not hasattr(state, "lecture_content_storage"):
            setattr(state, "lecture_content_storage", {})
        if not hasattr(state, "faq_storage"):
            setattr(state, "faq_storage", {})
        if not hasattr(state, "accessed_memory_storage"):
            setattr(state, "accessed_memory_storage", [])

        callback = state.callback
        if not isinstance(callback, LectureChatCallback):
            callback = cast(LectureChatCallback, state.callback)

        tool_list: list[Callable] = [
            create_tool_get_course_details(state.dto.course, callback),
        ]

        query_text = self.get_text_of_latest_user_message(state)
        if allow_lecture_tool:
            self.lecture_retriever = LectureRetrieval(state.db.client)
            tool_list.append(
                create_tool_lecture_content_retrieval(
                    self.lecture_retriever,
                    state.dto.course.id,
                    state.dto.settings.artemis_base_url if state.dto.settings else "",
                    callback,
                    query_text,
                    state.message_history,
                    getattr(state, "lecture_content_storage", {}),
                    lecture_id=state.dto.lecture.id if state.dto.lecture else None,
                    lecture_unit_id=state.dto.lecture_unit_id,
                )
            )

        if allow_faq_tool:
            self.faq_retriever = FaqRetrieval(state.db.client)
            tool_list.append(
                create_tool_faq_content_retrieval(
                    self.faq_retriever,
                    state.dto.course.id,
                    state.dto.course.name,
                    state.dto.settings.artemis_base_url if state.dto.settings else "",
                    callback,
                    query_text,
                    state.message_history,
                    getattr(state, "faq_storage", {}),
                )
            )

        if allow_memiris_tool and state.memiris_wrapper:
            tool_list.append(
                state.memiris_wrapper.create_tool_memory_search(
                    getattr(state, "accessed_memory_storage", [])
                )
            )
            tool_list.append(
                state.memiris_wrapper.create_tool_find_similar_memories(
                    getattr(state, "accessed_memory_storage", [])
                )
            )

        return tool_list

    def build_system_message(
        self,
        state: AgentPipelineExecutionState[
            LectureChatPipelineExecutionDTO, LectureChatVariant
        ],
    ) -> str:
        """
        Return a system message for the chat prompt.

        Returns:
            str: The system message content
        """
        # Extract user language with fallback
        user_language = "en"
        if state.dto.user and state.dto.user.lang_key:
            user_language = state.dto.user.lang_key

        allow_lecture_tool = should_allow_lecture_tool(state.db, state.dto.course.id)
        allow_faq_tool = should_allow_faq_tool(state.db, state.dto.course.id)
        allow_memiris_tool = bool(
            state.dto.user
            and state.dto.user.memiris_enabled
            and state.memiris_wrapper
            and state.memiris_wrapper.has_memories()
        )
        custom_instructions = format_custom_instructions(
            state.dto.custom_instructions or ""
        )

        template_context = {
            "current_date": datetime_to_string(datetime.now(tz=pytz.UTC)),
            "user_language": user_language,
            "lecture_name": state.dto.lecture.title if state.dto.lecture else None,
            "course_name": state.dto.course.name if state.dto.course else None,
            "allow_lecture_tool": allow_lecture_tool,
            "allow_faq_tool": allow_faq_tool,
            "allow_memiris_tool": allow_memiris_tool,
            "has_chat_history": bool(state.message_history),
            "custom_instructions": custom_instructions,
        }

        return self.system_prompt_template.render(template_context)

    def get_memiris_tenant(self, dto: LectureChatPipelineExecutionDTO) -> str:
        """
        Return the Memiris tenant identifier for the current user.

        Returns:
            str: The tenant identifier
        """
        if not dto.user:
            raise ValueError("User is required for memiris tenant")
        return get_tenant_for_user(dto.user.id)

    def get_memiris_reference(self, dto: LectureChatPipelineExecutionDTO):
        """
        Return the reference to use for the Memiris learnings created in a lecture chat.
        It is simply the id of last user message in the chat history with a prefix.

        Returns:
            str: The reference identifier
        """
        last_message: Optional[PyrisMessage] = next(
            (
                m
                for m in reversed(dto.chat_history or [])
                if m.sender == IrisMessageRole.USER
            ),
            None,
        )
        return (
            f"session-messages/{last_message.id}"
            if last_message and last_message.id
            else "session-messages/unknown"
        )

    def on_agent_step(
        self,
        state: AgentPipelineExecutionState[
            LectureChatPipelineExecutionDTO, LectureChatVariant
        ],
        step: dict[str, Any],
    ) -> None:
        """
        Handle each agent execution step.

        Args:
            state: The current pipeline execution state.
            step: The current step information.
        """
        if step.get("intermediate_steps"):
            state.callback.in_progress("Thinking ...")

    def post_agent_hook(
        self,
        state: AgentPipelineExecutionState[
            LectureChatPipelineExecutionDTO, LectureChatVariant
        ],
    ) -> str:
        """
        Post-processing after agent execution including citations.

        Returns:
            str: The final result
        """
        if hasattr(state, "lecture_content_storage") and hasattr(state, "faq_storage"):
            state.result = self._process_citations(
                state,
                state.result,
                state.lecture_content_storage,
                state.faq_storage,
                state.dto,
                state.variant,
            )

        session_title = self._generate_session_title(state, state.result, state.dto)

        state.callback.done(
            "Response created",
            final_result=state.result,
            tokens=state.tokens,
            session_title=session_title,
            accessed_memories=getattr(state, "accessed_memory_storage", []),
        )

        return state.result

    def _process_citations(
        self,
        state: AgentPipelineExecutionState[
            LectureChatPipelineExecutionDTO, LectureChatVariant
        ],
        output: str,
        lecture_content_storage: dict[str, Any],
        faq_storage: dict[str, Any],
        dto: LectureChatPipelineExecutionDTO,
        variant: LectureChatVariant,
    ) -> str:
        """
        Process citations for lecture content and FAQs.

        Args:
            state: The current pipeline execution state
            output: The agent's output
            lecture_content_storage: Storage for lecture content
            faq_storage: Storage for FAQ content
            dto: The pipeline execution DTO
            variant: The variant configuration

        Returns:
            str: The output with citations added
        """
        # Extract user language
        user_language = "en"
        if state.dto.user and state.dto.user.lang_key:
            user_language = state.dto.user.lang_key

        if lecture_content_storage.get("content"):
            base_url = dto.settings.artemis_base_url if dto.settings else ""
            output = self.citation_pipeline(
                lecture_content_storage["content"],
                output,
                InformationType.PARAGRAPHS,
                variant=variant.id,
                user_language=user_language,
                base_url=base_url,
            )
        if hasattr(self.citation_pipeline, "tokens") and self.citation_pipeline.tokens:
            for token in self.citation_pipeline.tokens:
                self._track_tokens(state, token)

        if faq_storage.get("faqs"):
            base_url = dto.settings.artemis_base_url if dto.settings else ""
            output = self.citation_pipeline(
                faq_storage["faqs"],
                output,
                InformationType.FAQS,
                variant=variant.id,
                user_language=user_language,
                base_url=base_url,
            )

        return output

    def _generate_session_title(
        self,
        state: AgentPipelineExecutionState[
            LectureChatPipelineExecutionDTO, LectureChatVariant
        ],
        output: str,
        dto: LectureChatPipelineExecutionDTO,
    ) -> Optional[str]:
        """
        Generate a session title for the first learner interaction.
        """

        chat_history = dto.chat_history or []
        if len(chat_history) == 1 and chat_history[0].contents:
            first_user_msg = chat_history[0].contents[0].text_content
            return super()._create_session_title(state, output, first_user_msg)
        return None

    @observe(name="Lecture Chat Pipeline")
    def __call__(
        self,
        dto: LectureChatPipelineExecutionDTO,
        variant: LectureChatVariant,
        # course: CourseChatStatusCallback -> maybe adapt arcitecture later
        callback: LectureChatCallback,
    ):
        """
        Run the lecture chat pipeline.

        Args:
            dto: The pipeline execution data transfer object
            variant: The variant configuration
            callback: The status callback
        """
        try:
            logger.info("Running lecture chat pipeline...")
            # Call the parent __call__ method which handles the complete execution
            super().__call__(dto, variant, callback)
        except Exception as e:
            logger.error(
                "An error occurred while running the lecture chat pipeline",
                exc_info=e,
            )
            traceback.print_exc()
            callback.error(
                "An error occurred while running the lecture chat pipeline.",
                tokens=[],
            )

    @classmethod
    def get_variants(cls) -> List[LectureChatVariant]:
        return [
            LectureChatVariant(
                variant_id="default",
                name="Default",
                description="Uses a smaller model for faster and cost-efficient responses.",
                agent_model="gpt-4.1-mini",
                citation_model="gpt-4.1-nano",
            ),
            LectureChatVariant(
                variant_id="advanced",
                name="Advanced",
                description="Uses a larger chat model, balancing speed and quality.",
                agent_model="gpt-4.1",
                citation_model="gpt-4.1-mini",
            ),
        ]

    # method get_agent_params from course chat is not implemented here since it is the same as in the superclass
