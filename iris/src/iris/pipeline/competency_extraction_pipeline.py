from typing import Optional

from langchain.output_parsers import PydanticOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
)

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain import CompetencyExtractionPipelineExecutionDTO
from iris.domain.data.competency_dto import Competency
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.domain.variant.variant import Variant
from iris.llm import (
    CompletionArguments,
    LlmRequestHandler,
)
from iris.pipeline import Pipeline
from iris.pipeline.prompts.competency_extraction import system_prompt
from iris.tracing import observe
from iris.web.status.status_update import CompetencyExtractionCallback

logger = get_logger(__name__)


class CompetencyExtractionPipeline(Pipeline):
    """CompetencyExtractionPipeline extracts and processes competencies from course content.

    It leverages a language model to generate competency JSON, parses the output using a Pydantic output parser,
    and handles errors during parsing, appending tokens, and final result notification.
    """

    PIPELINE_ID = "competency_extraction_pipeline"
    ROLES = {"chat"}
    VARIANT_DEFS = [
        ("default", "Default", "Default competency extraction variant"),
    ]

    callback: CompetencyExtractionCallback
    request_handler: LlmRequestHandler
    output_parser: PydanticOutputParser

    def __init__(
        self,
        callback: Optional[CompetencyExtractionCallback] = None,
        variant: Variant | None = None,
        local: bool = False,
    ):
        super().__init__(implementation_id=self.PIPELINE_ID)
        if variant is None:
            raise ValueError("Variant is required for CompetencyExtractionPipeline")
        self.callback = callback
        model = variant.model("chat", local)
        self.request_handler = LlmRequestHandler(model_id=model)
        self.output_parser = PydanticOutputParser(pydantic_object=Competency)
        self.tokens = []

    @observe(name="Competency Extraction Pipeline")
    def __call__(
        self,
        dto: CompetencyExtractionPipelineExecutionDTO,
        prompt: Optional[ChatPromptTemplate] = None,
        **kwargs,
    ):
        if not dto.course_description:
            raise ValueError("Course description is required")
        if not dto.taxonomy_options:
            raise ValueError("Taxonomy options are required")
        if not dto.max_n:
            raise ValueError("Non-zero max_n is required")

        taxonomy_options = ", ".join(dto.taxonomy_options)
        current_competencies = "\n\n".join(
            [c.model_dump_json(indent=4) for c in dto.current_competencies]
        )
        if current_competencies:
            current_competencies = (
                f"\nHere are the current competencies in the course:\n{current_competencies}\n"
                f"Do not repeat these competencies.\n"
            )

        prompt = system_prompt.format(
            taxonomy_list=taxonomy_options,
            course_description=dto.course_description,
            max_n=dto.max_n,
            current_competencies=current_competencies,
        )
        prompt = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[TextMessageContentDTO(text_content=prompt)],
        )

        response = self.request_handler.chat(
            [prompt], CompletionArguments(temperature=0.4), tools=None
        )
        self._append_tokens(
            response.token_usage, PipelineEnum.IRIS_COMPETENCY_GENERATION
        )
        response = response.contents[0].text_content

        generated_competencies: list[Competency] = []

        # Find all competencies in the response up to the max_n
        competencies = response.split("\n\n")[: dto.max_n]
        for i, competency in enumerate(competencies):
            logger.debug("Processing competency %s: %s", i + 1, competency)
            if "{" not in competency or "}" not in competency:
                logger.debug("Skipping competency without JSON")
                continue
            # Get the competency JSON object
            start = competency.index("{")
            end = competency.index("}") + 1
            competency = competency[start:end]
            try:
                competency = self.output_parser.parse(competency)
            except Exception as e:
                logger.debug("Error parsing competency: %s", e)
                continue
            logger.debug("Generated competency: %s", competency)
            generated_competencies.append(competency)
        self.callback.done(final_result=generated_competencies, tokens=self.tokens)
