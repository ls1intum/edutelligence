import logging
import threading
from typing import List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.common.tutor_suggestion import (
    ChannelType,
    faq_content_retrieval,
    get_channel_type,
    lecture_content_retrieval,
)
from iris.domain import FeatureDTO
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.external.model import LanguageModel
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.tutor_suggestion.helper_prompts import (
    question_answered_prompt,
)
from iris.pipeline.shared.utils import filter_variants_by_available_models
from iris.pipeline.tutor_suggestion.tutor_suggestion_channel_base_pipeline import (
    TutorSuggestionChannelBasePipeline,
)
from iris.pipeline.tutor_suggestion.tutor_suggestion_summary_pipeline import (
    TutorSuggestionSummaryPipeline,
)
from iris.vector_database.database import VectorDatabase
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)

ADVANCED_VARIANT = "deepseek-r1:8b"
DEFAULT_VARIANT = "gemma3:27b"


class TutorSuggestionPipeline(Pipeline):
    """
    The TutorSuggestionPipeline creates a tutor suggestion

    when called, it uses the post received as an argument to create a suggestion based on the conversation
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorSuggestionCallback
    variant: str
    dto: CommunicationTutorSuggestionPipelineExecutionDTO
    is_answered: bool = False

    def __init__(self, callback: TutorSuggestionCallback, variant: str = "default"):
        super().__init__(implementation_id="tutor_suggestion_pipeline")
        self.variant = variant
        completion_args = CompletionArguments(temperature=0, max_tokens=8000)

        model = ADVANCED_VARIANT if self.variant == "advanced" else DEFAULT_VARIANT

        self.llm = IrisLangchainChatModel(
            request_handler=ModelVersionRequestHandler(version=model),
            completion_args=completion_args,
        )

        self.callback = callback
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []
        self.db = VectorDatabase()

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Tutor Suggestion Pipeline")
    def __call__(self, dto: CommunicationTutorSuggestionPipelineExecutionDTO):
        """
        Run the pipeline.
        :param dto: execution data transfer object
        """
        self.dto = dto
        self.callback.in_progress("Summarizing post content")
        summary_pipeline = TutorSuggestionSummaryPipeline(
            callback=self.callback, variant=self.variant
        )
        try:
            summary = summary_pipeline(dto=self.dto)
        except AttributeError as e:
            logger.error("AttributeError in summary pipeline: %s", str(e))
            self.callback.error("Error running summary pipeline")
            return
        except Exception as e:
            logger.error("Unexpected error in summary pipeline: %s", str(e))
            self.callback.error("Unexpected error running summary pipeline")
            return

        if summary is None:
            self.callback.error("No summary was generated")
            return

        try:
            is_question_str = summary.get("is_question", "").lower()
            is_question = is_question_str in ["yes", "true", "1"]
            number_of_answers = summary.get("num_answers")
            self.summary_text = summary.get("summary")
        except (AttributeError, TypeError) as e:
            logger.error("Error parsing summary JSON: %s", str(e))
            self.callback.error("Error parsing summary JSON")
            return
        if is_question and number_of_answers > 0:
            self.is_answered = self._check_if_answered(self.summary_text)

        channel_type = get_channel_type(dto)

        lecture_content_result = {}
        faq_content_result = {}

        def get_lecture_content():
            lecture_content_result["data"] = lecture_content_retrieval(
                dto, self.summary_text, self.db
            )
            self.callback.in_progress("Retrieved relevant lecture content")

        def get_faq_content():
            faq_content_result["data"] = faq_content_retrieval(
                self.db, self.summary_text, dto
            )

        lecture_thread = threading.Thread(target=get_lecture_content)
        faq_thread = threading.Thread(target=get_faq_content)

        lecture_thread.start()
        faq_thread.start()
        self.callback.in_progress("Retrieving lecture and FAQ content")

        lecture_thread.join()
        faq_thread.join()

        self.lecture_content = lecture_content_result["data"]
        self.faq_content = faq_content_result["data"]

        if channel_type == ChannelType.TEXT_EXERCISE:
            self._run_pipeline(
                channel_type=ChannelType.TEXT_EXERCISE,
                label="text exercise",
                dto=dto,
            )
        elif channel_type == ChannelType.PROGRAMMING_EXERCISE:
            self._run_pipeline(
                channel_type=ChannelType.PROGRAMMING_EXERCISE,
                label="programming exercise",
                dto=dto,
            )
        elif channel_type == ChannelType.LECTURE:
            self._run_pipeline(
                channel_type=ChannelType.LECTURE,
                label="lecture",
                dto=dto,
            )
        else:
            # If it's a general or other type of channel, we use the lecture pipeline to handle it as it relies on the
            # lecture contents.
            self._run_pipeline(
                channel_type=ChannelType.LECTURE,
                label="lecture",
                dto=dto,
            )

    def _run_pipeline(
        self,
        label: str,
        channel_type: str,
        dto: CommunicationTutorSuggestionPipelineExecutionDTO,
    ):
        """
        Helper method to run a specific pipeline and handle errors.
        :param label: Label for the pipeline being run.
        :param channel_type: Type of the channel (e.g., TEXT_EXERCISE, PROGRAMMING_EXERCISE, LECTURE).
        :param dto: Data transfer object containing the execution data.
        """
        self.callback.in_progress(f"Generating suggestions for {label}")
        pipeline = TutorSuggestionChannelBasePipeline(
            variant=self.variant, callback=self.callback
        )
        try:
            result, tutor_answer = pipeline(
                channel_type,
                self.lecture_content,
                self.faq_content,
                self.summary_text,
                self.is_answered,
                dto,
            )
            for tokens in getattr(pipeline, "tokens", []):
                self._append_tokens(tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE)
        except AttributeError as e:
            self.callback.error(f"Error running {label} pipeline: {e}")
            return
        self.callback.done(
            "Generated tutor suggestions",
            artifact=result,
            final_result=tutor_answer,
            tokens=self.tokens,
        )

    def _check_if_answered(self, summary: str) -> bool:
        self.callback.in_progress("Checking if question is already answered")
        prompt = ChatPromptTemplate.from_messages(
            [("system", question_answered_prompt())]
        )
        try:
            response = (prompt | self.pipeline).invoke({"thread_summary": summary})
            self._append_tokens(
                self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
            )
            return "yes" in response.lower()
        except Exception as e:
            logger.error("Error checking if question is answered: %s", str(e))
            return False

    @classmethod
    def get_variants(cls, available_llms: List[LanguageModel]) -> List[FeatureDTO]:
        """
        Returns available variants for the TutorSuggestionPipeline based on available LLMs.

        Args:
            available_llms: List of available language models

        Returns:
            List of FeatureDTO objects representing available variants
        """
        variant_specs = [
            (
                [DEFAULT_VARIANT],
                FeatureDTO(
                    id="default",
                    name="Default",
                    description="Default tutor suggestion variant using Gemma 3 model.",
                ),
            ),
            (
                [ADVANCED_VARIANT],
                FeatureDTO(
                    id="advanced",
                    name="Advanced",
                    description="Advanced tutor suggestion variant using DeepSeek R1 model.",
                ),
            ),
        ]

        return filter_variants_by_available_models(
            available_llms, variant_specs, pipeline_name="TutorSuggestionPipeline"
        )
