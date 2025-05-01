import json
from typing import List, Optional

from jinja2 import Template
from ollama import Message
from pydantic import TypeAdapter

from memiris.domain.learning import Learning
from memiris.dto.learning_dto import LearningDto
from memiris.service.ollama_service import ollama_client


class LearningExtractor:
    """
    This class is responsible for extracting learning information from the given data.
    """

    llm: str  # Placeholder for the LLM instance
    template: Template
    focus: Optional[str]

    def __init__(
        self, llm: str, focus: Optional[str] = None, template: Optional[str] = None
    ) -> None:
        """
        Initialize the LearningExtractor
        """
        self.llm = llm
        self.focus = focus

        if template is None:
            # Load the default template from the file located at memiris.default_templates.learning_extraction
            template_path = "./default_templates/learning_extraction.md.j2"
            with open(template_path, "r", encoding="utf-8") as file:
                template_content = file.read()
            self.template = Template(template_content)
        else:
            # Load the template from the provided string
            self.template = Template(template)

    def extract(
        self, text: str, previous_learnings: Optional[List[Learning]] = None, **kwargs
    ) -> list[Learning]:
        """
        Extract learning information from the given data.
        """
        learning_array_type_adapter = TypeAdapter(List[LearningDto])
        learning_json_dict = learning_array_type_adapter.json_schema()

        learning_json_schema = json.dumps(learning_json_dict, indent=2)

        system_message = self.template.render(
            learning_json_schema=learning_json_schema,
            learning_focus=self.focus,
            previous_learnings=(
                [
                    self.learning_to_dto(learning).model_dump()
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

        response = ollama_client.chat(
            model=self.llm,
            messages=messages,
            format=learning_json_dict,
            options={"temperature": 0.05},
        )

        if response and response.message:
            try:
                learning_dtos = learning_array_type_adapter.validate_json(
                    response.message.content or "[]"
                )
                return [
                    self.dto_to_learning(learning_dto, reference=None)
                    for learning_dto in learning_dtos
                ]
            except Exception as e:
                print(f"Error parsing response: {e}")
                return []

        return []

    def dto_to_learning(
        self, learning_dto: LearningDto, reference: Optional[str]
    ) -> Learning:
        """
        Convert a LearningDto to a Learning object.
        """
        return Learning(
            title=learning_dto.title,
            content=learning_dto.content,
            reference=reference or "",
        )

    def learning_to_dto(self, learning: Learning) -> LearningDto:
        """
        Convert a Learning object to a LearningDto.
        """
        return LearningDto(title=learning.title, content=learning.content)
