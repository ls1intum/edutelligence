import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable
from pydantic import BaseModel, Field

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
        completion_args = CompletionArguments()
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(self_hosted=False)
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
        self, dto: CommunicationTutorSuggestionPipelineExecutionDTO, summary: str
    ):
        if summary is None:
            self.callback.error("No summary was generated")
            return

        self.dto = dto
        self.channel_type = get_channel_type(dto)

        self.callback.in_progress(
            "Checking if question is appropriate for the channel type"
        )
        result = channel_type_checker(summary=summary, channel_type=self.channel_type)
        if "no" in result:
            channel_type = result.split(":")[-1].strip()
            self.callback.in_progress(
                f"Channel was not appropriate. New channel_type: {channel_type}"
            )
            logging.info(f"Channel was not appropriate. New channel: {channel_type}")

        self.callback.in_progress("Generating suggestions for text exercise")
        text_exercise_dto = dto.textExerciseDTO
        logging.info(text_exercise_dto)
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


def channel_type_checker(summary: str, channel_type: str) -> str:
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
                " the context of the post. The possible categories are:"
                " 'exercise', 'lecture', 'general'.\n\n",
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
        completion_args=CompletionArguments(),
    )
    pipeline = llm | StrOutputParser()
    return (prompt | pipeline).invoke({})
