from typing import Any, Callable, List, Mapping, Optional, Union

from jinja2 import Template
from langfuse import observe
from ollama import Message

from memiris.dlo.learning_main_dlo import LearningDLO
from memiris.dlo.memory_creation_dlo import MemoryCreationDLO
from memiris.domain.learning import Learning
from memiris.domain.memory import Memory
from memiris.llm.abstract_language_model import AbstractLanguageModel
from memiris.repository.learning_repository import LearningRepository
from memiris.repository.memory_repository import MemoryRepository
from memiris.service.memory_creator.memory_creator import MemoryCreator
from memiris.service.vectorizer import Vectorizer
from memiris.tool import learning_tools, memory_tools
from memiris.util.jinja_util import create_template
from memiris.util.learning_util import learning_to_dlo
from memiris.util.memory_util import creation_dlo_to_memory


class MemoryCreatorMultiModel(MemoryCreator):
    """
    A class to create memories using a large language model.
    """

    tool_llm: AbstractLanguageModel
    thinking_llm: AbstractLanguageModel
    response_llm: AbstractLanguageModel
    template: Template
    learning_repository: LearningRepository
    memory_repository: MemoryRepository
    vectorizer: Vectorizer
    ollama_service: None  # Deprecated: use model proxies

    def __init__(
        self,
        tool_llm: AbstractLanguageModel,
        thinking_llm: AbstractLanguageModel,
        response_llm: AbstractLanguageModel,
        learning_repository: LearningRepository,
        memory_repository: MemoryRepository,
        vectorizer: Vectorizer,
        template: Optional[str] = None,
    ) -> None:
        """
        Initialize the MemoryCreator

        Args:
            tool_llm: The bound model to use for tool operations
            thinking_llm: The bound model to use for thinking operations
            response_llm: The bound model to use for the final JSON response
            learning_repository: The repository for accessing learning data
            memory_repository: The repository for accessing memory data
            vectorizer: The vectorizer service
            template: Optional template path
        """
        self.tool_llm = tool_llm
        self.thinking_llm = thinking_llm
        self.response_llm = response_llm
        self.learning_repository = learning_repository
        self.memory_repository = memory_repository
        self.vectorizer = vectorizer
        self.ollama_service = None

        self.template = create_template(template, "memory_creator.md.j2")

    @observe(name="memory-creation")
    def create(self, learnings: List[Learning], tenant: str, **kwargs) -> List[Memory]:
        """
        Create a memory from the given learnings using the LLM.
        """
        learning_array_type_adapter = LearningDLO.json_array_type()

        learnings_string = str(
            learning_array_type_adapter.dump_json(
                [learning_to_dlo(learning) for learning in learnings]
            )
        )

        memory_json_schema = MemoryCreationDLO.json_array_schema()

        messages: List[Union[Mapping[str, Any], Message]] = [
            # The system message will be set later based on the phase
            Message(role="system", content="TODO"),
            Message(
                role="user",
                content=learnings_string,
            ),
        ]

        def done_tool():
            """
            A tool to indicate that you are done with the current phase and want to go to the final phase.
            This should only be used once you have thought enough and have used the other tools at your disposal.
            """
            pass

        tools: dict[str, Callable] = {
            "find_learnings_by_id": learning_tools.create_tool_find_learnings_by_id(
                self.learning_repository, tenant
            ),
            "find_similar_learnings": learning_tools.create_tool_find_similar_learnings(
                self.learning_repository, tenant
            ),
            "search_learnings": learning_tools.create_tool_search_learnings(
                self.learning_repository, self.vectorizer, tenant
            ),
            "find_similar_memories": memory_tools.create_tool_find_similar(
                self.memory_repository, tenant
            ),
            "search_memories": memory_tools.create_tool_search_memories(
                self.memory_repository, self.vectorizer, tenant
            ),
            "done_tool": done_tool,
        }

        print("Starting tool phase...")
        for i in range(0, 10):
            system_message = self.template.render(
                memory_json_schema=memory_json_schema,
                is_tool_phase=i % 2 == 1,
                is_thinking_phase=i % 2 == 0,
                **kwargs,
            )

            messages[0].content = system_message  # type: ignore

            # Call the LLM to get the response
            response = (self.tool_llm if i % 2 == 1 else self.thinking_llm).chat(
                messages=messages,
                tools=(list(tools.values()) if i % 2 == 1 else None),
                options={"temperature": 0.05},
                **kwargs,
            )

            if not response or not response.message:
                break

            # Append assistant message in normalized mapping form
            messages.append(
                {
                    "role": "assistant",
                    "content": response.message.content or "",
                    "name": None,
                }
            )

            print(response.message)

            if response.message.tool_calls:
                done = False
                for tool in response.message.tool_calls:
                    if tool.function.name == "done_tool":
                        done = True
                        print("TOOL: Done")
                    if function_to_call := tools.get(tool.function.name):
                        output = function_to_call(**tool.function.arguments)  # type: ignore
                        messages.append(
                            {
                                "role": "tool",
                                "content": str(output),
                                "name": tool.function.name,
                            }
                        )
                if done:
                    break

            phase = "thinking phase" if i % 2 == 1 else "tool phase"
            messages.append(
                Message(
                    role="user",
                    content=f"You are now in the {phase}.\n",
                )
            )

        print("Tool phase done.")

        messages[0].content = self.template.render(  # type: ignore
            memory_json_schema=memory_json_schema,
            is_tool_phase=False,
            options={"temperature": 0.05},
            **kwargs,
        )

        response = self.response_llm.chat(
            messages=messages,
            response_format=MemoryCreationDLO.json_array_type().json_schema(),
        )

        if response and response.message and response.message.content:
            try:
                memory_dlos = MemoryCreationDLO.json_array_type().validate_json(
                    response.message.content
                )

                needed_learnings = []
                for memory_dlo in memory_dlos:
                    for learning_id in memory_dlo.learnings:
                        try:
                            learning = self.learning_repository.find(
                                tenant, learning_id
                            )
                            if learning:
                                needed_learnings.append(learning)
                        except Exception as e:
                            print(f"Error finding learning with ID {learning_id}: {e}")

                return [
                    creation_dlo_to_memory(memory_dlo, needed_learnings)
                    for memory_dlo in memory_dlos
                ]
            except Exception as e:
                print(f"Error parsing response: {e}")
                return []

        return []
