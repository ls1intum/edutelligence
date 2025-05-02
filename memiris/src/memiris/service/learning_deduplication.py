import json
from typing import List, Optional

from jinja2 import Template
from ollama import Message
from pydantic import TypeAdapter

from memiris.domain.learning import Learning
from memiris.dto.learning_dto import LearningDto
from memiris.service.ollama_service import ollama_client
from memiris.util.learning_util import dto_to_learning, learning_to_dto


class LearningDeduplicator:
    """
    A class to deduplicate Learnings using a large language model.
    """

    llm: str
    template: Template

    def __init__(self, llm: str, template: Optional[str] = None) -> None:
        """
        Initialize the LearningExtractor
        """
        self.llm = llm

        if template is None:
            # Load the default template from the file located at memiris.default_templates.learning_extraction
            template_path = "./default_templates/learning_deduplication.md.j2"
            with open(template_path, "r", encoding="utf-8") as file:
                template_content = file.read()
            self.template = Template(template_content)
        else:
            # Load the template from the provided string
            self.template = Template(template)

    def deduplicate(self, learnings: List[Learning], **kwargs) -> List[Learning]:
        """
        Deduplicate the given learnings using the LLM.
        """

        learning_array_type_adapter = TypeAdapter(List[LearningDto])
        learning_json_dict = learning_array_type_adapter.json_schema()

        learning_json_schema = json.dumps(learning_json_dict, indent=2)

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
                        [learning_to_dto(learning) for learning in learnings]
                    )
                ),
            ),
        ]

        response = ollama_client.chat(
            model=self.llm,
            messages=messages,
            format=learning_json_dict,
            options={"temperature": 0.05},
        )

        if response and response.message and response.message.content:
            try:
                learning_dtos = learning_array_type_adapter.validate_json(
                    response.message.content
                )
                return [
                    dto_to_learning(learning_dto, reference=None)
                    for learning_dto in learning_dtos
                ]
            except Exception as e:
                print(f"Error parsing response: {e}")
                return learnings

        return learnings
