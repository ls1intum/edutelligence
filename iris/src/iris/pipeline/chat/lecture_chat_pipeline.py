import json
import os
import random
import re
from datetime import datetime
from typing import Any, Callable, List, Optional, cast

import pytz
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)
from iris.tracing import observe

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
    create_tool_generate_mcq_questions,
    create_tool_get_course_details,
    create_tool_lecture_content_retrieval,
)
from ...vector_database.lecture_unit_page_chunk_schema import LectureUnitPageChunkSchema
from ...vector_database.lecture_unit_schema import LectureUnitSchema
from ...web.status.status_update import LectureChatCallback
from ..abstract_agent_pipeline import AbstractAgentPipeline, AgentPipelineExecutionState
from ..shared.citation_pipeline import CitationPipeline, InformationType
from ..shared.mcq_generation_pipeline import McqGenerationPipeline
from ..shared.utils import datetime_to_string, format_custom_instructions

logger = get_logger(__name__)


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

    def __init__(self, local: bool = False):
        super().__init__(implementation_id="lecture_chat_pipeline")
        self.session_title_pipeline = SessionTitleGenerationPipeline(local=local)
        self.citation_pipeline = CitationPipeline(local=local)
        self.mcq_pipeline = McqGenerationPipeline(local=local)
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
        if allow_lecture_tool and not getattr(state, "mcq_parallel", False):
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

        # MCQ generation tool — only if parallel generation is NOT active
        if not getattr(state, "mcq_parallel", False):
            if not hasattr(state, "mcq_result_storage"):
                setattr(state, "mcq_result_storage", {})
            user_language = "en"
            if state.dto.user and state.dto.user.lang_key:
                user_language = state.dto.user.lang_key
            lecture_content, _ = self._retrieve_lecture_content_for_mcq(state)
            tool_list.append(
                create_tool_generate_mcq_questions(
                    self.mcq_pipeline,
                    state.dto.chat_history,
                    callback,
                    getattr(state, "mcq_result_storage", {}),
                    user_language,
                    lecture_content=lecture_content,
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

        Also detects MCQ intent and sets flags on state BEFORE get_tools() runs,
        since the abstract pipeline calls build_system_message before get_tools.

        Returns:
            str: The system message content
        """
        # Detect MCQ intent early — flags must be set before get_tools() runs
        user_message = self.get_text_of_latest_user_message(state)
        is_mcq, count = self._detect_mcq_intent(user_message)
        if is_mcq:
            setattr(state, "mcq_parallel", True)
            setattr(state, "mcq_count", count)

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
            "mcq_parallel": getattr(state, "mcq_parallel", False),
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

    @staticmethod
    def _detect_mcq_intent(user_message: str) -> tuple[bool, int]:
        """Detect MCQ generation intent from user message.

        Returns:
            Tuple of (is_mcq_intent, question_count). Count defaults to 1.
        """
        message_lower = user_message.lower()

        # Check for explicit count patterns (e.g., "5 questions", "another 3")
        count_patterns = [
            r"(\d+)\s*(?:more\s+)?(?:question|mcq|quiz)",
            r"(?:another|more|give me|generate|create)\s+(\d+)",
        ]
        for pattern in count_patterns:
            match = re.search(pattern, message_lower)
            if match:
                return True, int(match.group(1))

        # Then check keyword phrases
        mcq_keywords = [
            "quiz",
            "mcq",
            "multiple choice",
            "test me",
            "quiz me",
            "test my knowledge",
            "generate a question",
            "generate questions",
            "ask me a question",
            "ask me questions",
            "ask me some questions",
            "give me a question",
            "give me questions",
            "another question",
            "more questions",
            "one more",
        ]
        if any(kw in message_lower for kw in mcq_keywords):
            return True, 1

        return False, 0

    def _retrieve_lecture_content_for_mcq(
        self,
        state: AgentPipelineExecutionState[
            LectureChatPipelineExecutionDTO, LectureChatVariant
        ],
    ) -> tuple[Optional[str], list[dict]]:
        """Fetch lecture unit summaries directly from Weaviate for MCQ generation.

        Uses a simple filtered fetch instead of the full RAG pipeline
        (query rewriting, HyDE, reranking) to keep MCQ generation fast.

        Returns:
            Tuple of (formatted content string, list of lecture unit metadata dicts)
        """
        if not should_allow_lecture_tool(state.db, state.dto.course.id):
            return None, []
        try:
            # Fetch actual page text content (not summaries) to avoid hallucinated content
            chunk_filter = Filter.by_property(
                LectureUnitPageChunkSchema.COURSE_ID.value
            ).equal(state.dto.course.id)

            # Narrow to specific lecture if available
            if state.dto.lecture and state.dto.lecture.id is not None:
                chunk_filter &= Filter.by_property(
                    LectureUnitPageChunkSchema.LECTURE_ID.value
                ).equal(state.dto.lecture.id)

            chunks = state.db.lectures.query.fetch_objects(
                filters=chunk_filter,
                return_properties=[
                    LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value,
                    LectureUnitPageChunkSchema.LECTURE_ID.value,
                    LectureUnitPageChunkSchema.PAGE_NUMBER.value,
                    LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value,
                ],
            )

            if not chunks.objects:
                return None, []

            # Also fetch lecture unit names for metadata
            unit_filter = Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
                state.dto.course.id
            )
            unit_results = state.db.lecture_units.query.fetch_objects(
                filters=unit_filter,
                return_properties=[
                    LectureUnitSchema.LECTURE_UNIT_ID.value,
                    LectureUnitSchema.LECTURE_NAME.value,
                    LectureUnitSchema.LECTURE_UNIT_NAME.value,
                ],
            )
            unit_name_map: dict[int, dict] = {}
            for obj in unit_results.objects:
                props = obj.properties
                lu_id = props.get(LectureUnitSchema.LECTURE_UNIT_ID.value)
                if lu_id is not None:
                    unit_name_map[lu_id] = {
                        "lecture_name": props.get(
                            LectureUnitSchema.LECTURE_NAME.value, ""
                        ),
                        "unit_name": props.get(
                            LectureUnitSchema.LECTURE_UNIT_NAME.value, ""
                        ),
                    }

            content = ""
            units_data: dict[int, dict] = {}
            for obj in chunks.objects:
                props = obj.properties
                lu_id = props.get(LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value)
                page = props.get(LectureUnitPageChunkSchema.PAGE_NUMBER.value, 1)
                text = props.get(LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value, "")
                names = unit_name_map.get(lu_id, {})
                lecture_name = names.get("lecture_name", "")
                unit_name = names.get("unit_name", "")

                if text:
                    content += f"Lecture: {lecture_name}, Unit: {unit_name}, Page {page}\n{text}\n\n"

                if lu_id is not None:
                    if lu_id not in units_data:
                        units_data[lu_id] = {
                            "lecture_unit_id": lu_id,
                            "lecture_name": lecture_name,
                            "unit_name": unit_name,
                            "pages": set(),
                        }
                    units_data[lu_id]["pages"].add(page)

            lecture_units_meta = []
            for data in units_data.values():
                pages = sorted(data["pages"])
                data["first_page"] = str(pages[0]) if pages else "1"
                del data["pages"]
                lecture_units_meta.append(data)

            return (content if content.strip() else None), lecture_units_meta
        except Exception as e:
            logger.warning("Failed to fetch lecture summaries for MCQ: %s", str(e))
            return None, []

    def pre_agent_hook(
        self,
        state: AgentPipelineExecutionState[
            LectureChatPipelineExecutionDTO, LectureChatVariant
        ],
    ) -> None:
        """Spawn parallel MCQ generation thread if intent was detected in build_system_message."""
        if not getattr(state, "mcq_parallel", False):
            return

        preparing_messages = [
            "Preparing to generate questions...",
            "Getting your quiz ready...",
            "Setting up a challenge for you...",
            "Putting together some questions...",
        ]
        state.callback.in_progress(
            "Preparing quiz...",
            chat_message=random.choice(preparing_messages),  # nosec B311
        )

        if not hasattr(state, "mcq_result_storage"):
            setattr(state, "mcq_result_storage", {})

        user_language = "en"
        if state.dto.user and state.dto.user.lang_key:
            user_language = state.dto.user.lang_key

        user_message = self.get_text_of_latest_user_message(state)
        count = getattr(state, "mcq_count", 1)

        # Retrieve lecture content before spawning MCQ thread
        lecture_content, lecture_units_meta = self._retrieve_lecture_content_for_mcq(
            state
        )
        setattr(state, "mcq_lecture_units_meta", lecture_units_meta)

        setattr(
            state,
            "mcq_thread",
            self.mcq_pipeline.run_in_thread(
                command=user_message,
                chat_history=state.dto.chat_history,
                user_language=user_language,
                result_storage=getattr(state, "mcq_result_storage", {}),
                count=count,
                lecture_content=lecture_content,
            ),
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

        For parallel MCQ:
        - Single question: join thread, integrate MCQ into the agent's message
        - Multiple questions: send agent intro first, then stream each MCQ one-by-one

        Returns:
            str: The final result
        """
        mcq_thread = getattr(state, "mcq_thread", None)
        mcq_parallel = getattr(state, "mcq_parallel", False)
        mcq_count = getattr(state, "mcq_count", 1)

        # For non-parallel MCQ (tool-calling fallback): replace placeholder inline
        if not mcq_parallel:
            mcq_storage = getattr(state, "mcq_result_storage", {})
            if mcq_storage.get("mcq_json"):
                mcq_json = mcq_storage["mcq_json"]
                if "[MCQ_RESULT]" in state.result:
                    state.result = state.result.replace("[MCQ_RESULT]", mcq_json)
                else:
                    state.result = state.result + "\n" + mcq_json
                for token in self.mcq_pipeline.tokens:
                    self._track_tokens(state, token)
                self.mcq_pipeline.tokens.clear()

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

        # For parallel MCQ: join thread and integrate into the message
        if mcq_thread:
            mcq_thread.join(timeout=120)
            mcq_storage = getattr(state, "mcq_result_storage", {})
            mcq_queue = mcq_storage.get("queue")
            lecture_units_meta = getattr(state, "mcq_lecture_units_meta", [])

            if mcq_count == 1:
                # Single question: append directly
                found_mcq = False
                if mcq_queue:
                    while not mcq_queue.empty():
                        msg_type, data = mcq_queue.get_nowait()
                        if msg_type == "mcq":
                            data = self._add_mcq_citations(data, lecture_units_meta)
                            state.result = state.result + "\n" + data
                            found_mcq = True
                        elif msg_type == "error":
                            logger.error("MCQ generation error: %s", data)
                if not found_mcq:
                    logger.warning("No MCQ was produced by the parallel thread")
                    state.result += "\n\nSorry, I was unable to generate the question. Please try again."
            else:
                # Multiple questions: collect all, bundle as mcq-set for carousel
                collected_questions: list[dict] = []
                if mcq_queue:
                    while not mcq_queue.empty():
                        msg_type, data = mcq_queue.get_nowait()
                        if msg_type == "mcq":
                            try:
                                data = self._add_mcq_citations(data, lecture_units_meta)
                                parsed = json.loads(data)
                                # Flatten: if a worker returned mcq-set, extract individual questions
                                if parsed.get("type") == "mcq-set":
                                    collected_questions.extend(
                                        parsed.get("questions", [])
                                    )
                                else:
                                    collected_questions.append(parsed)
                            except json.JSONDecodeError:
                                logger.error("Invalid MCQ JSON received: %s", data)
                        elif msg_type == "error":
                            logger.error(
                                "MCQ generation error for multi-question: %s",
                                data,
                            )
                if collected_questions:
                    mcq_set = json.dumps(
                        {
                            "type": "mcq-set",
                            "questions": collected_questions[:mcq_count],
                        }
                    )
                    state.result = state.result + "\n" + mcq_set
                else:
                    logger.warning(
                        "No MCQ questions collected for mcq-set (requested %d)",
                        mcq_count,
                    )
                    state.result += "\n\nSorry, I was unable to generate the questions. Please try again."

            for token in self.mcq_pipeline.tokens:
                self._track_tokens(state, token)
            self.mcq_pipeline.tokens.clear()

        # Send the complete response (text + MCQ integrated)
        state.callback.done(
            "Response created",
            final_result=state.result,
            tokens=state.tokens,
            session_title=session_title,
            accessed_memories=getattr(state, "accessed_memory_storage", []),
        )

        return state.result

    @staticmethod
    def _add_mcq_citations(mcq_json_str: str, lecture_units_meta: list[dict]) -> str:
        """Add citation markers to MCQ explanations and strip them from options.

        Uses the LLM-generated "source" field to match the correct lecture unit.
        Same citation format as the regular citation pipeline:
        [cite:L:<lecture_unit_id>:<page>:<start>:<end>:<keyword>:<summary>]
        """
        if not lecture_units_meta:
            return mcq_json_str
        try:
            parsed = json.loads(mcq_json_str)
        except (json.JSONDecodeError, TypeError):
            return mcq_json_str

        citation_re = re.compile(r"\[cite:[^\]]*\]")

        def _find_matching_unit(source: str) -> Optional[dict]:
            """Match the LLM source field to a lecture unit."""
            if not lecture_units_meta:
                return None
            if len(lecture_units_meta) == 1:
                return lecture_units_meta[0]
            if source:
                source_lower = source.lower().strip()
                for meta in lecture_units_meta:
                    unit_name = (meta.get("unit_name") or "").lower()
                    if source_lower in unit_name or unit_name in source_lower:
                        return meta
                    lecture_name = (meta.get("lecture_name") or "").lower()
                    if source_lower in lecture_name or lecture_name in source_lower:
                        return meta
            return None

        def _process_question(q: dict) -> None:
            for opt in q.get("options", []):
                if "text" in opt:
                    opt["text"] = citation_re.sub("", opt["text"]).strip()
            if "question" in q:
                q["question"] = citation_re.sub("", q["question"]).strip()

            source = q.pop("source", "")
            meta = _find_matching_unit(source)
            if meta:
                lu_id = meta.get("lecture_unit_id", "")
                unit_name = meta.get("unit_name", "")
                page = meta.get("first_page", "1")
                q["explanation"] = (
                    q.get("explanation", "")
                    + f" [cite:L:{lu_id}:{page}:::{unit_name}:{unit_name}]"
                )

        if parsed.get("type") == "mcq-set":
            for q in parsed.get("questions", []):
                _process_question(q)
        elif parsed.get("type") == "mcq":
            _process_question(parsed)

        return json.dumps(parsed)

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
        Generate a session title from the latest user prompt and the model output.

        Args:
            state: The current pipeline execution state
            output: The agent's output
            dto: The pipeline execution DTO

        Returns:
            The generated session title or None if not applicable
        """
        return self.update_session_title(state, output, dto.session_title)

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
            local = dto.settings is not None and dto.settings.is_local()
            super().__call__(dto, variant, callback, local=local)
        except Exception as e:
            logger.error(
                "An error occurred while running the lecture chat pipeline",
                exc_info=e,
            )
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
                cloud_agent_model="gpt-5-mini",
                cloud_citation_model="gpt-5-nano",
                local_agent_model="gpt-oss:120b",
                local_citation_model="gpt-oss:120b",
            ),
            LectureChatVariant(
                variant_id="advanced",
                name="Advanced",
                description="Uses a larger chat model, balancing speed and quality.",
                cloud_agent_model="gpt-5.2",
                cloud_citation_model="gpt-5-mini",
                local_agent_model="gpt-oss:120b",
                local_citation_model="gpt-oss:120b",
            ),
        ]
