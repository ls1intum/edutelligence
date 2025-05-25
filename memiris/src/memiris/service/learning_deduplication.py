from typing import List, Optional

from jinja2 import Template
from ollama import Message

from memiris.domain.learning import Learning
from memiris.dto.learning_creation_dto import LearningCreationDto
from memiris.service.ollama_wrapper import OllamaService
from memiris.util.jinja_util import create_template
from memiris.util.learning_util import (
    creation_dto_to_learning,
    learning_to_creation_dto,
)


class LearningDeduplicator:
    """
    A class to deduplicate Learnings using a large language model.
    """

    llm: str
    template: Template
    ollama_service: OllamaService

    def __init__(
        self, llm: str, ollama_service: OllamaService, template: Optional[str] = None
    ) -> None:
        """
        Initialize the LearningExtractor

        Args:
            llm: The name of the language model to use
            ollama_service: The Ollama service to use for LLM calls
            template: Optional template path to use for the deduplication prompt
        """
        self.llm = llm
        self.template = create_template(template, "learning_deduplication.md.j2")
        self.ollama_service = ollama_service

    def deduplicate(self, learnings: List[Learning], **kwargs) -> List[Learning]:
        """
        Deduplicate the given learnings using the LLM.
        NOTE: This is currently only meant to be used immediately after the learning extraction.
        If it is used afterward, it will lose the id and reference of the learnings.
        """
        # Early return if there are no learnings to deduplicate
        if not learnings:
            return []

        learning_json_schema = LearningCreationDto.json_array_schema()
        learning_array_type_adapter = LearningCreationDto.json_array_type()

        system_message = self.template.render(
            learning_json_schema=learning_json_schema,
            **kwargs,
        )

        messages: list[Message] = [
            Message(role="system", content=system_message),
            Message(
                role="user",
                content=str(
                    learning_array_type_adapter.dump_json(
                        [learning_to_creation_dto(learning) for learning in learnings]
                    )
                ),
            ),
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
                return learnings

        return learnings
