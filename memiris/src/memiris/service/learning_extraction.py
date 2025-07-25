from typing import List, Optional

from jinja2 import Template
from langfuse import observe
from ollama import Message

from memiris.domain.learning import Learning
from memiris.dto.learning_creation_dto import LearningCreationDto
from memiris.service.ollama_wrapper import OllamaService
from memiris.util.jinja_util import create_template
from memiris.util.learning_util import (
    creation_dto_to_learning,
    learning_to_creation_dto,
)


class LearningExtractor:
    """
    This class is responsible for extracting learning information from the given data.
    """

    llm: str  # Placeholder for the LLM instance
    template: Template
    focus: Optional[str]
    ollama_service: OllamaService

    def __init__(
        self,
        llm: str,
        ollama_service: OllamaService,
        focus: Optional[str] = None,
        template: Optional[str] = None,
    ) -> None:
        """
        Initialize the LearningExtractor

        Args:
            llm: The name of the language model to use
            ollama_service: The Ollama service to use for LLM calls
            focus: Optional focus for the extraction
            template: Optional template path to use for the extraction prompt
        """
        self.llm = llm
        self.focus = focus
        self.ollama_service = ollama_service
        self.template = create_template(template, "learning_extraction.md.j2")

    @observe(name="learning-extraction")
    def extract(
        self, text: str, previous_learnings: Optional[List[Learning]] = None, **kwargs
    ) -> list[Learning]:
        """
        Extract learning information from the given data.
        """
        learning_json_schema = LearningCreationDto.json_array_schema()

        system_message = self.template.render(
            learning_json_schema=learning_json_schema,
            learning_focus=self.focus,
            previous_learnings=(
                [
                    learning_to_creation_dto(learning).model_dump()
                    for learning in previous_learnings
                ]
                if previous_learnings
                else None
            ),
            **kwargs,
        )

        messages: list[Message] = [
            Message(role="system", content=system_message),
            Message(role="user", content=text),
        ]

        response = self.ollama_service.chat(
            model=self.llm,
            messages=messages,
            response_format=LearningCreationDto.json_array_type().json_schema(),
            options={"temperature": 0.05},
        )

        if response and response.message and response.message.content:
            try:
                learning_dtos = LearningCreationDto.json_array_type().validate_json(
                    response.message.content
                )
                return [
                    creation_dto_to_learning(learning_dto, reference=None)
                    for learning_dto in learning_dtos
                ]
            except Exception as e:
                print(f"Error parsing response: {e}")
                return []

        return []
