from typing import List, Optional

from jinja2 import Template
from langfuse import observe
from ollama import Message

from memiris.dlo.learning_creation_dlo import LearningCreationDLO
from memiris.domain.learning import Learning
from memiris.service.ollama_wrapper import AbstractLanguageModel
from memiris.util.jinja_util import create_template
from memiris.util.learning_util import (
    creation_dlo_to_learning,
    learning_to_creation_dlo,
)


class LearningExtractor:
    """
    This class is responsible for extracting learning information from the given data.
    """

    llm: AbstractLanguageModel  # Bound chat model wrapper
    template: Template
    focus: Optional[str]

    def __init__(
        self,
        llm: AbstractLanguageModel,
        focus: Optional[str] = None,
        template: Optional[str] = None,
    ) -> None:
        """
        Initialize the LearningExtractor

        Args:
            llm: The bound chat model to use
            focus: Optional focus for the extraction
            template: Optional template path to use for the extraction prompt
        """
        self.llm = llm
        self.focus = focus
        self.template = create_template(template, "learning_extraction.md.j2")

    @observe(name="learning-extraction")
    def extract(
        self, text: str, previous_learnings: Optional[List[Learning]] = None, **kwargs
    ) -> list[Learning]:
        """
        Extract learning information from the given data.
        """
        learning_json_schema = LearningCreationDLO.json_array_schema()

        system_message = self.template.render(
            learning_json_schema=learning_json_schema,
            learning_focus=self.focus,
            previous_learnings=(
                [
                    learning_to_creation_dlo(learning).model_dump()
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

        response = self.llm.chat(
            messages=messages,
            response_format=LearningCreationDLO.json_array_type().json_schema(),
            options={"temperature": 0.05},
        )

        if response and response.message and response.message.content:
            try:
                learning_dlos = LearningCreationDLO.json_array_type().validate_json(
                    response.message.content
                )
                return [
                    creation_dlo_to_learning(learning_dlo, reference=None)
                    for learning_dlo in learning_dlos
                ]
            except Exception as e:
                print(f"Error parsing response: {e}")
                return []

        return []
