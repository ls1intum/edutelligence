import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.llm import CapabilityRequestHandler, CompletionArguments, RequirementList
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.tutor_suggestion_agent_pipeline import TutorSuggestionAgentPipeline
from iris.pipeline.tutor_suggestion_summary_pipeline import (
    TutorSuggestionSummaryPipeline,
)
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)


class TutorSuggestionPipeline(Pipeline):
    """
    The TutorSuggestionPipeline creates a tutor suggestion

    when called it uses the post received as an argument to create a suggestion based on the conversation
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorSuggestionCallback

    def __init__(self, callback: TutorSuggestionCallback):
        super().__init__(implementation_id="tutor_suggestion_pipeline")
        completion_args = CompletionArguments()
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

    @traceable(name="Tutor Suggestion Pipeline")
    def __call__(self, dto: CommunicationTutorSuggestionPipelineExecutionDTO):
        """
        Run the pipeline.
        :param dto: execution data transfer object
        """
        self.callback.in_progress("Summarizing post content")
        summary_pipeline = TutorSuggestionSummaryPipeline(callback=self.callback)
        try:
            summary = summary_pipeline(dto=dto)
        except AttributeError as e:
            self.callback.error("Error running summary pipeline")
            return

        logger.info(summary)

        self.callback.in_progress("Generating tutor suggestion")

        tutor_suggestion_agent_pipeline = TutorSuggestionAgentPipeline(
            callback=self.callback
        )

        try:
            tutor_suggestion_agent_pipeline(dto=dto, summary=summary)
        except AttributeError as e:
            logger.error(e)
