import logging
from typing import List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.common.tutor_suggestion import get_channel_type, ChannelType
from iris.domain import FeatureDTO
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.external.model import LanguageModel
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.tutor_suggestion.question_answered_prompt import (
    question_answered_prompt,
)
from iris.pipeline.shared.utils import filter_variants_by_available_models
from iris.pipeline.tutor_suggestion.tutor_suggestion_lecture_pipeline import (
    TutorSuggestionLecturePipeline,
)
from iris.pipeline.tutor_suggestion.tutor_suggestion_programming_exercise_pipeline import (
    TutorSuggestionProgrammingExercisePipeline,
)
from iris.pipeline.tutor_suggestion.tutor_suggestion_summary_pipeline import (
    TutorSuggestionSummaryPipeline,
)
from iris.pipeline.tutor_suggestion.tutor_suggestion_text_exercise_pipeline import (
    TutorSuggestionTextExercisePipeline,
)
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)

ADVANCED_VARIANT = "deepseek-r1:8b"
DEFAULT_VARIANT = "gemma3:27b"


class TutorSuggestionPipeline(Pipeline):
    """
    The TutorSuggestionPipeline creates a tutor suggestion

    when called it uses the post received as an argument to create a suggestion based on the conversation
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorSuggestionCallback
    variant: str
    dto: CommunicationTutorSuggestionPipelineExecutionDTO

    def __init__(self, callback: TutorSuggestionCallback, variant: str = "default"):
        super().__init__(implementation_id="tutor_suggestion_pipeline")
        self.variant = variant
        completion_args = CompletionArguments(temperature=0, max_tokens=8000)

        if variant == "advanced":
            model = ADVANCED_VARIANT
        else:
            model = DEFAULT_VARIANT

        self.llm = IrisLangchainChatModel(
            request_handler=ModelVersionRequestHandler(version=model),
            completion_args=completion_args,
        )

        self.callback = callback
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

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

        logger.info(summary)

        if summary is None:
            self.callback.error("No summary was generated")
            return

        try:
            is_question_str = summary.get("is_question", "").lower()
            is_question = is_question_str in ["yes", "true", "1"]
            number_of_answers = summary.get("num_answers")
            summary = summary.get("summary")
            logger.info(
                "is_question: %s, num_answers: %s", is_question, number_of_answers
            )
        except (AttributeError, TypeError) as e:
            logger.error("Error parsing summary JSON: %s", str(e))
            self.callback.error("Error parsing summary JSON")
            return
        is_answered = False
        if is_question and number_of_answers > 0:
            self.callback.in_progress("Checking if questions is already answered")

            prompt = ChatPromptTemplate.from_messages(
                [("system", question_answered_prompt())]
            )

            try:
                response = (prompt | self.pipeline).invoke({"thread_summary": summary})
                logger.info(response)
                self._append_tokens(
                    self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
                )
            except Exception as e:
                logger.error("Error checking if question is answered: %s", str(e))
                response = "no"
            if "yes" in response.lower():
                is_answered = True

        channel_type = get_channel_type(dto)

        logging.info(channel_type)
        if channel_type == ChannelType.TEXT_EXERCISE:
            self._run_text_exercise_pipeline(
                text_exercise_dto=dto.text_exercise,
                summary=summary,
                is_answered=is_answered,
            )
        elif channel_type == ChannelType.PROGRAMMING_EXERCISE:
            self._run_programming_exercise_pipeline(dto=dto, summary=summary)
        elif channel_type == ChannelType.LECTURE:
            self._run_lecture_pipeline(dto=dto, summary=summary)
        else:
            self.callback.error("Not implemented yet")

    def _run_text_exercise_pipeline(
        self, text_exercise_dto: TextExerciseDTO, summary: str, is_answered: bool
    ):
        """
        Run the text exercise pipeline.
        :param text_exercise_dto: The TextExerciseDTO object containing details about the text exercise.
        :param summary: The summary of the post.
        :return: The result of the text exercise pipeline.
        """
        self.callback.in_progress("Generating suggestions for text exercise")
        text_exercise_pipeline = TutorSuggestionTextExercisePipeline(
            variant=self.variant, callback=self.callback
        )
        try:
            logging.info(summary)
            text_exercise_result, tutor_answer = text_exercise_pipeline(
                dto=text_exercise_dto,
                chat_summary=summary,
                chat_history=self.dto.chat_history,
                is_answered=is_answered,
            )
        except AttributeError as e:
            self.callback.error(f"Error running text exercise pipeline: {e}")
            return

        self.callback.done(
            "Generated tutor suggestions",
            artifact=text_exercise_result,
            final_result=tutor_answer,
            tokens=self.tokens,
        )

    def _run_programming_exercise_pipeline(
        self,
        dto: CommunicationTutorSuggestionPipelineExecutionDTO,
        summary: str,
    ):
        """
        Run the programming exercise pipeline.
        :param dto: The CommunicationTutorSuggestionPipelineExecutionDTO object containing details about the
        programming exercise.
        :param summary: The summary of the post.
        :return: The result of the programming exercise pipeline.
        """
        self.callback.in_progress("Generating suggestions for programming exercise")
        programming_exercise_pipeline = TutorSuggestionProgrammingExercisePipeline(
            variant=self.variant
        )
        try:
            programming_exercise_result = programming_exercise_pipeline(
                dto=dto, chat_summary=summary
            )
        except AttributeError as e:
            self.callback.error(f"Error running programming exercise pipeline: {e}")
            return

        self.callback.done(
            "Generated tutor suggestions",
            artifact=programming_exercise_result,
            tokens=self.tokens,
        )

    def _run_lecture_pipeline(
        self,
        dto: CommunicationTutorSuggestionPipelineExecutionDTO,
        summary: str,
    ):
        """
        Run the lecture pipeline.
        :param dto: The CommunicationTutorSuggestionPipelineExecutionDTO object containing details about the lecture.
        :param summary: The summary of the post.
        :return: The result of the lecture pipeline.
        """
        self.callback.in_progress("Generating suggestions for lecture")

        lecture_pipeline = TutorSuggestionLecturePipeline(
            callback=self.callback, variant=self.variant
        )

        try:
            lecture_result = lecture_pipeline(dto=dto, chat_summary=summary)
        except AttributeError as e:
            self.callback.error(f"Error running lecture pipeline: {e}")
            return

        self.callback.done(
            "Generated tutor suggestions",
            artifact=lecture_result,
            tokens=self.tokens,
        )

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
                ["gemma3:27b"],
                FeatureDTO(
                    id="default",
                    name="Default",
                    description="Default tutor suggestion variant using Gemma 3 model.",
                ),
            )
        ]

        return filter_variants_by_available_models(
            available_llms, variant_specs, pipeline_name="TutorSuggestionPipeline"
        )
