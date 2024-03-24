import logging
from exercise_chat_pipeline import ExerciseChatPipeline
from lecture_chat_pipeline import LectureChatPipeline
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import Runnable
from ...domain import TutorChatPipelineExecutionDTO
from ...web.status.status_update import TutorChatStatusCallback
from ...llm import BasicRequestHandler, CompletionArguments
from ...llm.langchain import IrisLangchainChatModel
from ..pipeline import Pipeline

logger = logging.getLogger(__name__)


class TutorChatPipeline(Pipeline):
    """Tutor chat pipeline that answers exercises related questions from students."""

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorChatStatusCallback

    def __init__(self, callback: TutorChatStatusCallback):
        super().__init__(implementation_id="tutor_chat_pipeline")
        # Set the langchain chat model
        request_handler = BasicRequestHandler("gpt35")
        completion_args = CompletionArguments(temperature=0.2, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.callback = callback

        # Create the pipelines
        self.pipeline = self.llm | StrOutputParser()
        self.exercise_pipeline = ExerciseChatPipeline(callback=callback, pipeline=self.pipeline, llm=self.llm)
        self.lecture_pipeline = LectureChatPipeline(callback=callback, pipeline=self.pipeline, llm=self.llm)

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __call__(self, dto: TutorChatPipelineExecutionDTO, **kwargs):
        """
        Runs the pipeline
            :param kwargs: The keyword arguments
        """
        # Lecture or Exercise query ?
        if dto.exercise is None:
            # Execute lecture content pipeline
            self.lecture_pipeline.__call__(dto)
        else:
            routing_prompt = PromptTemplate.from_template(
                """Given the user question below, classify it as either being about `Lecture_content` or
                `Programming_Exercise`.

                Do not respond with more than one word.

                <question>
                {question}
                </question>

                Classification:"""
            )
            chain = (routing_prompt | self.pipeline)
            response = chain.invoke({"question": dto.chat_history[-1]})
            if "Lecture_content" in response:
                # Execute lecture content pipeline
                self.lecture_pipeline.__call__(dto)
            else:
                self.exercise_pipeline.__call__(dto)

