import json
from typing import Any, Callable, List, Mapping, Optional, Union

from jinja2 import Template
from ollama import Message
from pydantic import TypeAdapter

from memiris.domain.learning import Learning
from memiris.domain.memory import Memory
from memiris.dto.learning_main_dto import LearningDto
from memiris.dto.memory_creation_dto import MemoryCreationDto
from memiris.repository.learning_repository import LearningRepository
from memiris.repository.memory_repository import MemoryRepository
from memiris.service.ollama_service import ollama_client
from memiris.service.vectorizer import Vectorizer
from memiris.tool import learning_tools, memory_tools
from memiris.util.learning_util import learning_to_dto
from memiris.util.memory_util import creation_dto_to_memory


class MemoryCreator:
    """
    A class to create memories using a large language model.
    """

    tool_llm: str
    response_llm: str
    template: Template
    learning_repository: LearningRepository
    memory_repository: MemoryRepository
    vectorizer: Vectorizer

    def __init__(
        self,
        tool_llm: str,
        response_llm: str,
        learning_repository: LearningRepository,
        memory_repository: MemoryRepository,
        vectorizer: Vectorizer,
        template: Optional[str] = None,
    ) -> None:
        """
        Initialize the LearningExtractor
        """
        self.tool_llm = tool_llm
        self.response_llm = response_llm
        self.learning_repository = learning_repository
        self.memory_repository = memory_repository
        self.vectorizer = vectorizer

        if template is None:
            # Load the default template from the file located at memiris.default_templates
            template_path = "./default_templates/memory_creator.md.j2"
            with open(template_path, "r", encoding="utf-8") as file:
                template_content = file.read()
            self.template = Template(template_content)
        else:
            # Load the template from the provided string
            self.template = Template(template)

    def create(self, learnings: List[Learning], tenant: str, **kwargs) -> List[Memory]:
        """
        Create a memory from the given learnings using the LLM.
        """
        learning_array_type_adapter = TypeAdapter(List[LearningDto])

        learnings_string = str(
            learning_array_type_adapter.dump_json(
                [learning_to_dto(learning) for learning in learnings]
            )
        )

        memory_array_type_adapter = TypeAdapter(List[MemoryCreationDto])
        memory_json_dict = memory_array_type_adapter.json_schema()

        memory_json_schema = json.dumps(memory_json_dict, indent=2)

        messages: List[Union[Mapping[str, Any], Message]] = [
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
            response = ollama_client.chat(
                model=self.tool_llm,
                messages=messages,
                tools=(list(tools.values()) if i % 2 == 1 else None),
                options={"temperature": 0.05},
                **kwargs,
            )

            if not response or not response.message:
                break

            messages.append(response.message)

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

            messages.append(
                Message(
                    role="user",
                    content=f"You are now in the {"thinking phase" if i % 2 == 1 else "tool phase"}.\n",
                )
            )

        print("Tool phase done.")

        messages[0].content = self.template.render(  # type: ignore
            memory_json_schema=memory_json_schema,
            is_tool_phase=False,
            options={"temperature": 0.05},
            **kwargs,
        )

        response = ollama_client.chat(
            model=self.response_llm, messages=messages, format=memory_json_dict
        )

        if response and response.message and response.message.content:
            try:
                memory_dtos = memory_array_type_adapter.validate_json(
                    response.message.content
                )

                needed_learnings = []
                for memory_dto in memory_dtos:
                    for learning_id in memory_dto.learnings:
                        try:
                            learning = self.learning_repository.find(
                                tenant, learning_id
                            )
                            if learning:
                                needed_learnings.append(learning)
                        except Exception as e:
                            print(f"Error finding learning with ID {learning_id}: {e}")

                return [
                    creation_dto_to_memory(memory_dto, needed_learnings)
                    for memory_dto in memory_dtos
                ]
            except Exception as e:
                print(f"Error parsing response: {e}")
                return []

        return []
