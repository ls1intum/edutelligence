import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable
from pydantic import BaseModel, Field

from iris.common.pipeline_enum import PipelineEnum
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.llm import CapabilityRequestHandler, CompletionArguments, RequirementList
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.tutor_suggestion_text_exercise_pipeline import (
    TutorSuggestionTextExercisePipeline,
)
from iris.web.status.status_update import TutorSuggestionCallback


def get_channel_type(dto: CommunicationTutorSuggestionPipelineExecutionDTO) -> str:
    """
    Determines the channel type based on the context of the post.
    :return: The channel type as a string.
    """
    if dto.programmingExerciseDTO is not None:
        return "programming_exercise"
    elif dto.textExerciseDTO is not None:
        return "text_exercise"
    elif dto.lecture_id is not None:
        return "lecture"
    else:
        return "general"


class CategoryCheckerInput(BaseModel):
    """
    Input schema for the category checker tool.
    :param category: The category to be validated.
    :param summary: The summary of the post.
    :param channel_type: The channel type of the post.
    """

    category: str = Field(description="The category to be validated.")
    summary: str = Field(description="The summary of the post.")
    channel_type: str = Field(description="The channel type of the post.")


class RunTextExercisePipelineInput(BaseModel):
    """
    Input schema for the text exercise pipeline tool.
    :param summary: The summary of the post.
    :param text_exercise_dto: The TextExerciseDTO object containing details about the text exercise.
    """

    summary: str
    text_exercise_dto: TextExerciseDTO


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

        self.callback.in_progress(
            "Checking if question is appropriate for the channel type"
        )
        result = self.channel_type_checker(
            summary=summary, channel_type=self.channel_type
        )
        if "no" in result:
            self.channel_type = result.split(":")[-1].strip()
            self.callback.in_progress(
                f"Channel was not appropriate. New channel_type: {self.channel_type}"
            )
            logging.info(
                f"Channel was not appropriate. New channel: {self.channel_type}"
            )

        if is_question and number_of_answers > 0:
            self.callback.in_progress("Checking if questions is already answered")

            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You are a verification assistant. Your task is to verify if in this discussion an asked question"
                        "is already answered. Answer with yes or no if the question is already answered. The summarized"
                        "thread is the following:\n\n"
                        "{thread_summary}\n\n",
                    )
                ]
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
                    final_result="The question has already been answered in the thread and should be marked as resolved.",
                    tokens=self.tokens,
                )
                return

        if self.channel_type == "text_exercise":
            self._run_text_exercise_pipeline(
                text_exercise_dto=dto.textExerciseDTO, summary=summary
            )
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
            [
                (
                    "system",
                    "You are a verification assistant. Your task is to verify if the given category is appropriate for"
                    " the context of the post. The only possible categories are:"
                    "'text_exercise', 'programming_exercise', 'lecture', 'general'.\n\n",
                ),
                (
                    "human",
                    f"Summary of the post: {summary}\n\nChannel type:"
                    f" {channel_type}\n\nIs the channel type appropriate for this context? "
                    f"Answer only with 'yes' or 'no'."
                    f"\nIf the channel_type is not appropriate, suggest a more suitable channel_type with the"
                    f" format 'channel_type: <suggested_channel_type>'.",
                ),
            ]
        )
        llm = IrisLangchainChatModel(
            request_handler=CapabilityRequestHandler(
                requirements=RequirementList(self_hosted=True)
            ),
            completion_args=CompletionArguments(temperature=0, max_tokens=2000),
        )
        self.tokens.append(llm.tokens)
        pipeline = llm | StrOutputParser()
        return (prompt | pipeline).invoke({})

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
        if text_exercise_dto is None:
            self.callback.error("No text exercise DTO was provided")
            return
        self.callback.in_progress("Running text exercise pipeline")
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
            final_result=text_exercise_result,
            tokens=self.tokens,
        )
