from typing import List, Optional

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
from iris.domain.variant.competency_extraction_variant import (
    CompetencyExtractionVariant,
)
from iris.llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from iris.pipeline import Pipeline
from iris.pipeline.prompts.competency_extraction import system_prompt
from iris.tracing import observe
from iris.web.status.status_update import CompetencyExtractionCallback

logger = get_logger(__name__)


class CompetencyExtractionPipeline(Pipeline[CompetencyExtractionVariant]):
    """CompetencyExtractionPipeline extracts and processes competencies from course content.

    It leverages a language model to generate competency JSON, parses the output using a Pydantic output parser,
    and handles errors during parsing, appending tokens, and final result notification.
    """

    callback: CompetencyExtractionCallback
    request_handler: ModelVersionRequestHandler
    output_parser: PydanticOutputParser

    def __init__(self, callback: Optional[CompetencyExtractionCallback] = None):
        super().__init__(
            implementation_id="competency_extraction_pipeline_reference_impl"
        )
        self.callback = callback
        self.request_handler = ModelVersionRequestHandler(version="gpt-4.1")
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

    @classmethod
    def get_variants(cls) -> List[CompetencyExtractionVariant]:
        """
        Returns available variants for the CompetencyExtractionPipeline.

        Returns:
            List of CompetencyExtractionVariant objects representing available variants
        """
        return [
            CompetencyExtractionVariant(
                variant_id="default",
                name="Default",
                description="Default competency extraction variant using GPT-4.1",
                agent_model="gpt-4.1",
            )
        ]
