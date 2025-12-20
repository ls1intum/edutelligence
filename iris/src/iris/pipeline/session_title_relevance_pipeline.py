import logging
import os
import traceback

from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline.sub_pipeline import SubPipeline

logger = logging.getLogger(__name__)


class SessionTitleRelevancePipeline(SubPipeline):
    """
    Pipeline that determines whether a session title is still relevant or should be regenerated for a chat.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    tokens: TokenUsageDTO

    def __init__(self):
        super().__init__(implementation_id="session_title_relevance_pipeline")

        # Set the langchain chat model
        model = "gpt-4.1-mini"
        request_handler = ModelVersionRequestHandler(version=model)
        completion_args = CompletionArguments(temperature=0, max_tokens=1024)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler,
            completion_args=completion_args,
        )
        # Set up Jinja2 environment and load the prompt template
        template_dir = os.path.join(os.path.dirname(__file__), "prompts", "templates")
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml", "j2"]),
        )
        self.prompt_template = self.jinja_env.get_template(
            "session_title_relevance_prompt.j2"
        )
        # Create the pipeline
        self.pipeline = self.llm | StrOutputParser()

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Session Title Relevance Pipeline")
    def __call__(self, current_title: str, recent_messages: list[str], **kwargs) -> str:
        prompt_text = self.prompt_template.render(
            current_title=current_title,
            recent_messages=recent_messages,
        )
        prompt = ChatPromptTemplate.from_messages([("system", prompt_text)])
        try:
            logger.info("Running Session Title Relevance Pipeline")
            should_update = (prompt | self.pipeline).invoke({})
            self.tokens = self.llm.tokens
            self.tokens.pipeline = PipelineEnum.IRIS_SESSION_TITLE_RELEVANCE_PIPELINE
            return should_update
        except Exception as e:
            logger.error(
                "An error occurred while running the session title relevance pipeline",
                exc_info=e,
            )
            traceback.print_exc()
            return None
