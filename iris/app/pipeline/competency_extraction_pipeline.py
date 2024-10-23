import logging
from typing import Optional

from langchain.output_parsers import PydanticOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
)

from app.common.PipelineEnum import PipelineEnum
from app.common.pyris_message import PyrisMessage, IrisMessageRole
from app.domain import (
    CompetencyExtractionPipelineExecutionDTO,
)
from app.domain.data.text_message_content_dto import TextMessageContentDTO
from app.domain.data.competency_dto import Competency
from app.llm import CapabilityRequestHandler, RequirementList, CompletionArguments
from app.pipeline import Pipeline
from app.web.status.status_update import CompetencyExtractionCallback
from app.pipeline.prompts.competency_extraction import system_prompt

logger = logging.getLogger(__name__)


class CompetencyExtractionPipeline(Pipeline):
    callback: CompetencyExtractionCallback
    request_handler: CapabilityRequestHandler
    output_parser: PydanticOutputParser

    def __init__(self, callback: Optional[CompetencyExtractionCallback] = None):
        super().__init__(
            implementation_id="competency_extraction_pipeline_reference_impl"
        )
        self.callback = callback
        self.request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=4.5,
                context_length=16385,
            )
        )
        self.output_parser = PydanticOutputParser(pydantic_object=Competency)
        self.tokens = []

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
            [prompt], CompletionArguments(temperature=0.4)
        )
        self._append_tokens(
            response.token_usage, PipelineEnum.IRIS_COMPETENCY_GENERATION
        )
        response = response.contents[0].text_content

        generated_competencies: list[Competency] = []

        # Find all competencies in the response up to the max_n
        competencies = response.split("\n\n")[: dto.max_n]
        for i, competency in enumerate(competencies):
            logger.debug(f"Processing competency {i + 1}: {competency}")
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
                logger.debug(f"Error parsing competency: {e}")
                continue
            logger.debug(f"Generated competency: {competency}")
            generated_competencies.append(competency)
        self.callback.done(final_result=generated_competencies, tokens=self.tokens)
