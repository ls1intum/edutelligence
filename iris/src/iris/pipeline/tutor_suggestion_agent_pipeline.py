import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.llm import CapabilityRequestHandler, CompletionArguments, RequirementList
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.tutor_suggestion.channel_type_checker_prompt import (
    channel_type_checker_prompt,
)
from iris.pipeline.prompts.tutor_suggestion.question_answered_prompt import (
    question_answered_prompt,
)
from iris.pipeline.tutor_suggestion_lecture_pipeline import TutorSuggestionLecturePipeline
from iris.pipeline.tutor_suggestion_programming_exercise_pipeline import (
    TutorSuggestionProgrammingExercisePipeline,
)
from iris.pipeline.tutor_suggestion_text_exercise_pipeline import (
    TutorSuggestionTextExercisePipeline,
)
from iris.web.status.status_update import TutorSuggestionCallback


def get_channel_type(dto: CommunicationTutorSuggestionPipelineExecutionDTO) -> str:
    """
    Determines the channel type based on the context of the post.
    :return: The channel type as a string.
    """
    if dto.exercise is not None:
        return "programming_exercise"
    elif dto.textExercise is not None:
        return "text_exercise"
    elif dto.lecture_id is not None:
        return "lecture"
    else:
        return "general"


class TutorSuggestionAgentPipeline(Pipeline):

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorSuggestionCallback
    dto: CommunicationTutorSuggestionPipelineExecutionDTO
    channel_type: str

    def __init__(self, callback: TutorSuggestionCallback):
        super().__init__(implementation_id="tutor_suggestion_agent_pipeline")
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(self_hosted=True)
        )
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler,
            completion_args=completion_args,
        )
        self.callback = callback
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Tutor Suggestion Agent Pipeline")
    def __call__(
        self,
        dto: CommunicationTutorSuggestionPipelineExecutionDTO,
        summary: dict[str, str],
    ):
        if summary is None:
            self.callback.error("No summary was generated")
            return

        try:
            is_question = "yes" in summary.get("is_question").lower()
            number_of_answers = summary.get("num_answers")
            summary = summary.get("summary")
            logging.info(
                "is_question: %s, num_answers: %s", is_question, number_of_answers
            )
        except AttributeError as e:
            self.callback.error("Error parsing summary JSON")
            return

        self.dto = dto
        self.channel_type = get_channel_type(dto)

        if is_question and number_of_answers > 0:
            self.callback.in_progress("Checking if questions is already answered")

            prompt = ChatPromptTemplate.from_messages(
                [("system", question_answered_prompt())]
            )

            try:
                response = (prompt | self.pipeline).invoke({"thread_summary": summary})
                self._append_tokens(
                    self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
                )
            except Exception as e:
                logging.error(e)
                response = "no"
            logging.info(response)
            if "yes" in response.lower():
                self.callback.done(
                    "The question has already been answered",
                    tutor_suggestion="The question has already been answered in the thread and should be marked as resolved.",
                    tokens=self.tokens,
                )
                return

        logging.info(self.channel_type)
        if self.channel_type == "text_exercise":
            self._run_text_exercise_pipeline(
                text_exercise_dto=dto.textExercise, summary=summary
            )
        elif self.channel_type == "programming_exercise":
            self._run_programming_exercise_pipeline(dto=dto, summary=summary)
        elif self.channel_type == "lecture":
            self._run_lecture_pipeline(dto=dto, summary=summary)
        else:
            self.callback.error("Not implemented yet")

    def channel_type_checker(self, summary: str, channel_type: str) -> str:
        """
        Validates if the given channel type is appropriate for the context of the post.

        :param summary: The summary of the post.
        :param channel_type: The channel type of the post.
        :return: A validation result as a string.
        """
        prompt = ChatPromptTemplate.from_messages(
            ["system", channel_type_checker_prompt()]
        )
        llm = IrisLangchainChatModel(
            request_handler=CapabilityRequestHandler(
                requirements=RequirementList(self_hosted=True)
            ),
            completion_args=CompletionArguments(temperature=0, max_tokens=2000),
        )
        self.tokens.append(llm.tokens)
        pipeline = llm | StrOutputParser()
        return (prompt | pipeline).invoke(
            {"channel_type": channel_type, "summary": summary}
        )

    def _run_text_exercise_pipeline(
        self, text_exercise_dto: TextExerciseDTO, summary: str
    ):
        """
        Run the text exercise pipeline.
        :param text_exercise_dto: The TextExerciseDTO object containing details about the text exercise.
        :param summary: The summary of the post.
        :return: The result of the text exercise pipeline.
        """
        self.callback.in_progress("Generating suggestions for text exercise")
        text_exercise_pipeline = TutorSuggestionTextExercisePipeline()
        try:
            logging.info(summary)
            text_exercise_result = text_exercise_pipeline(
                dto=text_exercise_dto, chat_summary=summary
            )
        except AttributeError as e:
            self.callback.error(f"Error running text exercise pipeline: {e}")
            return

        self.callback.done(
            "Generated tutor suggestions",
            tutor_suggestion=text_exercise_result,
            tokens=self.tokens,
        )

    def _run_programming_exercise_pipeline(
        self, dto: CommunicationTutorSuggestionPipelineExecutionDTO, summary: str
    ):
        """
        Run the programming exercise pipeline.
        :param dto: The CommunicationTutorSuggestionPipelineExecutionDTO object containing details about the programming exercise.
        :param summary: The summary of the post.
        :return: The result of the programming exercise pipeline.
        """
        self.callback.in_progress("Generating suggestions for programming exercise")
        programming_exercise_pipeline = TutorSuggestionProgrammingExercisePipeline()
        try:
            programming_exercise_result = programming_exercise_pipeline(
                dto=dto, chat_summary=summary
            )
        except AttributeError as e:
            self.callback.error(f"Error running programming exercise pipeline: {e}")
            return

        self.callback.done(
            "Generated tutor suggestions",
            tutor_suggestion=programming_exercise_result,
            tokens=self.tokens,
        )

    def _run_lecture_pipeline(
        self, dto: CommunicationTutorSuggestionPipelineExecutionDTO, summary: str
    ):
        """
        Run the lecture pipeline.
        :param dto: The CommunicationTutorSuggestionPipelineExecutionDTO object containing details about the lecture.
        :param summary: The summary of the post.
        :return: The result of the lecture pipeline.
        """
        self.callback.in_progress("Generating suggestions for lecture")

        lecture_pipeline = TutorSuggestionLecturePipeline(callback=self.callback)

        try:
            lecture_result = lecture_pipeline(
                dto=dto, chat_summary=summary
            )
        except AttributeError as e:
            self.callback.error(f"Error running lecture pipeline: {e}")
            return

        self.callback.done(
            "Generated tutor suggestions",
            final_result=lecture_result,
            tokens=self.tokens,
        )



