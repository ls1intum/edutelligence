import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.llm import CapabilityRequestHandler, CompletionArguments, RequirementList
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.tutor_suggestion.programming_exercise_prompt import (
    programming_exercise_prompt,
)
from iris.pipeline.tutor_suggestion_summary_pipeline import _extract_json_from_text
from iris.pipeline.tutor_suggestion_text_exercise_pipeline import (
    _extract_html_from_text,
    _has_html,
)

logger = logging.getLogger(__name__)


class TutorSuggestionProgrammingExercisePipeline(Pipeline):

    llm: IrisLangchainChatModel
    pipeline: Runnable

    def __init__(self):
        super().__init__(
            implementation_id="tutor_suggestion_programming_exercise_pipeline"
        )
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(self_hosted=False)
        )
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler,
            completion_args=completion_args,
        )

        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Tutor Suggestion Programming Exercise Pipeline")
    def __call__(
        self, dto: CommunicationTutorSuggestionPipelineExecutionDTO, chat_summary: str
    ):
        """
        Run the pipeline.
        :param dto: execution data transfer object
        """
        logger.info("Running Tutor Suggestion Programming Exercise Pipeline")

        return self._run_programming_exercise_pipeline(dto=dto, summary=chat_summary)

    def _run_programming_exercise_pipeline(
        self, dto: CommunicationTutorSuggestionPipelineExecutionDTO, summary: str
    ):
        self.prompt = ChatPromptTemplate.from_messages(
            [("system", programming_exercise_prompt())]
        )
        problem_statement = dto.exercise.problem_statement
        exercise_title = dto.exercise.name
        programming_language = dto.exercise.programming_language

        try:
            response = (self.prompt | self.pipeline).invoke(
                {
                    "thread_summary": summary,
                    "exercise_title": exercise_title,
                    "programming_language": programming_language,
                    "problem_statement": problem_statement,
                }
            )
            logger.info(response)
            json = _extract_json_from_text(response)
            try:
                result = json.get("result")
            except AttributeError:
                logger.error("No result found in JSON response.")
                return None
            if _has_html(result):
                html_response = _extract_html_from_text(result)
                self._append_tokens(
                    self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
                )
            else:
                html_response = (
                    "<p>I was not able to answer this question based on the text exercise.</p><br>"
                    "<p>It seems that the question is too general or not related to the programming exercise."
                    "</p>"
                )
                self._append_tokens(
                    self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
                )
            return html_response
        except Exception as e:
            logger.error(
                f"Failed to generate suggestions for programming exercise: {e}"
            )
            return "Error generating suggestions for programming exercise"
