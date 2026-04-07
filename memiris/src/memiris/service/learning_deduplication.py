from typing import List, Optional

from jinja2 import Template
from langfuse import observe
from ollama import Message

from memiris.dlo.learning_creation_dlo import LearningCreationDLO
from memiris.domain.learning import Learning
from memiris.llm.abstract_language_model import AbstractLanguageModel
from memiris.util.jinja_util import create_template
from memiris.util.learning_util import (
    creation_dlo_to_learning,
    learning_to_creation_dlo,
)


class LearningDeduplicator:
    """
    A class to deduplicate Learnings using a large language model.
    """

    llm: AbstractLanguageModel
    template: Template
    ollama_service: None  # Deprecated: use llm proxy

    def __init__(
        self, llm: AbstractLanguageModel, template: Optional[str] = None
    ) -> None:
        """
        Initialize the LearningExtractor

        Args:
            llm: The bound chat model to use
            template: Optional template path to use for the deduplication prompt
        """
        self.llm = llm
        self.template = create_template(template, "learning_deduplication.md.j2")
        self.ollama_service = None

    @observe(name="learning-deduplication")
    def deduplicate(self, learnings: List[Learning], **kwargs) -> List[Learning]:
        """
        Deduplicate the given learnings using the LLM.
        NOTE: This is currently only meant to be used immediately after the learning extraction.
        If it is used afterward, it will lose the id and reference of the learnings.
        """
        # Early return if there are no learnings to deduplicate
        if not learnings:
            return []

        learning_json_schema = LearningCreationDLO.json_array_schema()
        learning_array_type_adapter = LearningCreationDLO.json_array_type()

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
                        [learning_to_creation_dlo(learning) for learning in learnings]
                    )
                ),
            ),
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
                return learnings

        return learnings
