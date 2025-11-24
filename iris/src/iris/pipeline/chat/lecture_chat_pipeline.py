import logging
import traceback
from typing import Any, Callable, List, Optional, cast

from langsmith import traceable

from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)

from ...common.memiris_setup import get_tenant_for_user
from ...common.pyris_message import IrisMessageRole, PyrisMessage
from ...domain.chat.lecture_chat.lecture_chat_pipeline_execution_dto import (
    LectureChatPipelineExecutionDTO,
)
from ...domain.variant.lecture_chat_variant import LectureChatVariant
from ...retrieval.lecture.lecture_retrieval import LectureRetrieval
from ...retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from ...tools import (
    create_tool_get_course_details,
    create_tool_lecture_content_retrieval,
)
from ...web.status.status_update import LectureChatCallback
from ..abstract_agent_pipeline import AbstractAgentPipeline, AgentPipelineExecutionState
from ..shared.citation_pipeline import CitationPipeline, InformationType
from ..shared.utils import format_custom_instructions

logger = logging.getLogger(__name__)


def chat_history_system_prompt():
    """
    Returns the system prompt for the chat history
    """
    return """This is the chat history of your conversation with the student so far. Read it so you
    know what already happened, but never re-use any message you already wrote. Instead, always write new and original
    responses. The student can reference the messages you've already written."""


def lecture_initial_prompt():
    """
    Returns the initial prompt for the lecture chat
    """
    return """You're Iris, the AI programming tutor integrated into Artemis, the online learning platform of the
     Technical University of Munich (TUM). You are a guide and an educator. Your main goal is to answer the student's
     questions about the lectures. To provide the best possible answer, the following relevant lecture content is
     provided to you: lecture slides, lecture transcriptions, and lecture segments. Lecture segments contain a
     combined summary of a section of lecture slides and transcription content.
     student's question. If the context provided to you is not enough to formulate an answer to the student question
     you can simply ask the student to elaborate more on his question. Use only the parts of the context provided for
     you that is relevant to the student's question. If the user greets you greet him back,
     and ask him how you can help.
     Always respond in the same language as the user. If they use English, you use English.
     If they use German, you use German, but then always use "du" instead of "Sie".
     """


class LectureChatPipeline(
    AbstractAgentPipeline[LectureChatPipelineExecutionDTO, LectureChatVariant]
):
    """
    Lecture chat pipeline that answers course related questions from students.
    """

    # compared with the lecture chat pipeline this does not work with Jinja
    # no FAQs used here compared to lecture (FAQs seem to refer to lecture level?)
    # no event used here compared to lecture (no JOL)
    session_title_pipeline: SessionTitleGenerationPipeline
    citation_pipeline: CitationPipeline
    lecture_retriever: Optional[LectureRetrieval]

    def __init__(self):
        super().__init__(implementation_id="lecture_chat_pipeline")
        self.session_title_pipeline = SessionTitleGenerationPipeline()
        self.citation_pipeline = CitationPipeline()
        self.lecture_retriever = None

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
        # Add memiris? (see course pipeline)
        # Add FAQ? (see course pipeline)
        allow_lecture_tool = should_allow_lecture_tool(state.db, state.dto.course.id)

        if not hasattr(state, "lecture_content_storage"):
            setattr(state, "lecture_content_storage", {})

        callback = state.callback
        if not isinstance(callback, LectureChatCallback):
            callback = cast(LectureChatCallback, state.callback)

        tool_list: list[Callable] = [
            create_tool_get_course_details(state.dto.course, callback),
        ]
        if allow_lecture_tool:
            self.lecture_retriever = LectureRetrieval(state.db.client)
            tool_list.append(
                create_tool_lecture_content_retrieval(
                    self.lecture_retriever,
                    state.dto.course.id,
                    state.dto.settings.artemis_base_url if state.dto.settings else "",
                    callback,
                    self.get_text_of_latest_user_message(state),
                    state.message_history,
                    getattr(state, "lecture_content_storage", {}),
                    lecture_id=state.dto.lecture.id if state.dto.lecture else None,
                    lecture_unit_id=state.dto.lecture_unit_id,
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
        # course pipeline somewhat more complex with Jinja but in the end returnes a string aswell
        allow_lecture_tool = should_allow_lecture_tool(state.db, state.dto.course.id)

        instructions: list[str] = [
            lecture_initial_prompt(),
            chat_history_system_prompt(),
        ]

        lecture_name = state.dto.lecture.title if state.dto.lecture else None
        course_name = state.dto.course.name if state.dto.course else None
        if lecture_name:
            instructions.append(
                f"You are currently helping with the lecture '{lecture_name}'."
            )
        if course_name:
            instructions.append(f"The lecture belongs to the course '{course_name}'.")

        if allow_lecture_tool:
            instructions.append(
                "You have access to the lecture_content_retrieval tool. Always call it exactly once before producing "
                "the final answer so that you can ground your response in the latest lecture slides, transcripts, "
                "and segment summaries."
            )
        else:
            instructions.append(
                "Lecture retrieval is currently unavailable for this course. Rely on the conversation so far and be "
                "transparent if you are missing specific lecture details."
            )

        custom_instructions = format_custom_instructions(
            state.dto.custom_instructions or ""
        )
        if custom_instructions:
            instructions.append(custom_instructions)

        return "\n\n".join(instructions)

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
        # Add FAQs if FAQ tool is used
        if hasattr(state, "lecture_content_storage") and hasattr(state, "faq_storage"):
            state.result = self._process_citations(
                state,
                state.result,
                state.lecture_content_storage,
                state.dto,
                state.variant,
            )

        session_title = self._generate_session_title(state, state.result, state.dto)

        # course: sends accessed_memories with status update
        state.callback.done(
            "Response created",
            final_result=state.result,
            tokens=state.tokens,
            session_title=session_title,
        )

        return state.result

    def _process_citations(
        self,
        state: AgentPipelineExecutionState[
            LectureChatPipelineExecutionDTO, LectureChatVariant
        ],
        output: str,
        lecture_content_storage: dict[str, Any],
        dto: LectureChatPipelineExecutionDTO,
        variant: LectureChatVariant,
    ) -> str:
        """
        Process citations for lecture content.

        Args:
            state: The current pipeline execution state
            output: The agent's output
            lecture_content_storage: Storage for lecture content
            dto: The pipeline execution DTO
            variant: The variant configuration

        Returns:
            str: The output with citations added
        """
        if lecture_content_storage.get("content"):
            base_url = dto.settings.artemis_base_url if dto.settings else ""
            output = self.citation_pipeline(
                lecture_content_storage["content"],
                output,
                InformationType.PARAGRAPHS,
                variant=variant.id,
                base_url=base_url,
            )
        if hasattr(self.citation_pipeline, "tokens") and self.citation_pipeline.tokens:
            for token in self.citation_pipeline.tokens:
                self._track_tokens(state, token)

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

        if len(dto.chat_history) == 1:
            first_user_msg = dto.chat_history[0].contents[0].text_content
            return super()._create_session_title(state, output, first_user_msg)
        return None

    @traceable(name="Lecture Chat Pipeline")
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
            # course: token=[]  argument
            callback.error("An error occurred while running the lecture chat pipeline.")

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
