import logging
import re
from typing import Any, Callable, List, Optional

from jinja2 import Template
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.tools import StructuredTool
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langfuse import observe

from memiris.dlo.learning_main_dlo import LearningDLO
from memiris.dlo.memory_creation_dlo import MemoryCreationDLO
from memiris.domain.learning import Learning
from memiris.domain.memory import Memory
from memiris.repository.learning_repository import LearningRepository
from memiris.repository.memory_repository import MemoryRepository
from memiris.service.improved_langchain_agent import ImprovedLangchainAgent
from memiris.service.memory_creator.memory_creator import MemoryCreator
from memiris.service.vectorizer import Vectorizer
from memiris.tool import learning_tools, memory_tools
from memiris.util.jinja_util import create_template
from memiris.util.learning_util import learning_to_dlo
from memiris.util.memory_util import creation_dlo_to_memory

# Maximum number of agent reasoning/tool-use iterations
MAX_AGENT_STEPS = 20

logger = logging.getLogger(__name__)


class MemoryCreatorLangChain(MemoryCreator):
    """
    A class to create memories using a single LangChain agent with tool-calling.

    - Uses one reasoning-capable LLM (passed as a LangChain `BaseChatModel`).
    - Supports iterative thinking <-> tool calling with a configurable max.
    - Final output is validated against the MemoryCreationDLO pydantic model.
    - Prompts are rendered via Jinja2 like the original implementation.
    """

    llm: BaseChatModel
    template: Template
    learning_repository: LearningRepository
    memory_repository: MemoryRepository
    vectorizer: Vectorizer

    def __init__(
        self,
        llm: BaseChatModel,
        learning_repository: LearningRepository,
        memory_repository: MemoryRepository,
        vectorizer: Vectorizer,
        template: Optional[str] = None,
    ) -> None:
        """
        Initialize the MemoryCreatorLangChain

        Args:
            llm: A LangChain chat model supporting tool calling and reasoning.
            learning_repository: The repository for accessing learning data.
            memory_repository: The repository for accessing memory data.
            vectorizer: The vectorizer service.
            template: Optional Jinja2 template string. If None, use the default file.
        """
        self.llm = llm
        self.learning_repository = learning_repository
        self.memory_repository = memory_repository
        self.vectorizer = vectorizer

        # Use a dedicated template for the LangChain agent variant
        self.template = create_template(template, "memory_creator_langchain.md.j2")

    def _build_tools(self, tenant: str) -> List[StructuredTool]:
        """
        Wrap repository-backed callables as LangChain StructuredTools.
        """
        py_tools: dict[str, Callable[..., Any]] = {
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
        }

        tools: List[StructuredTool] = []
        for name, func in py_tools.items():
            description = func.__doc__ or name
            # Use type hints from the functions for structured tool schemas
            tools.append(
                StructuredTool.from_function(
                    name=name,
                    description=description,
                    func=func,
                )
            )
        return tools

    @observe(name="memory-creation-langchain")
    def create(
        self, learnings: List[Learning], tenant: str, **kwargs: Any
    ) -> List[Memory]:
        """
        Create memories from the given learnings using a LangChain agent.
        """
        learning_array_type_adapter = LearningDLO.json_array_type()

        learnings_string = str(
            learning_array_type_adapter.dump_json(
                [learning_to_dlo(learning) for learning in learnings]
            )
        )

        memory_json_schema = MemoryCreationDLO.json_array_schema()

        # Build tools
        tools = self._build_tools(tenant)

        # Render a single, unified system prompt (no separate thinking/tool phases)
        system_prompt = self.template.render(
            memory_json_schema=memory_json_schema,
            tool_names=[t.name for t in tools],
            **kwargs,
        )

        # Build LC Agent prompt: system + user input + agent scratchpad placeholder
        escaped_system = system_prompt.replace("{", "{{").replace("}", "}}")
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", escaped_system),
                ("human", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ]
        )

        agent = create_tool_calling_agent(self.llm, tools, prompt)
        agent_executor = AgentExecutor(
            agent=ImprovedLangchainAgent(runnable=agent),
            tools=tools,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=MAX_AGENT_STEPS,
            return_intermediate_steps=True,
            early_stopping_method="generate",
        )

        result = agent_executor.invoke({"input": learnings_string})

        output_text = (result or {}).get("output", "") or ""
        text = output_text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json\n"):
                text = text[5:]

        def parse_and_convert(candidate: str) -> List[Memory]:
            memory_dlos = MemoryCreationDLO.json_array_type().validate_json(candidate)
            needed: List[Learning] = []
            for md in memory_dlos:
                for lid in md.learnings:
                    learning: Optional[Learning] = None
                    try:
                        learning = self.learning_repository.find(tenant, lid)
                    except (
                        Exception
                    ) as exc:  # noqa: BLE001 - repository may raise various errors
                        logger.debug(
                            "Learning lookup failed for tenant=%s id=%s: %s",
                            tenant,
                            lid,
                            exc,
                        )
                    if learning:
                        needed.append(learning)
            return [creation_dlo_to_memory(md, needed) for md in memory_dlos]

        try:
            return parse_and_convert(text)
        except Exception as exc:  # noqa: BLE001 - parsing may raise pydantic errors
            logger.debug("Primary parse failed, attempting regex extraction: %s", exc)
            match = re.search(r"\[\s*\{[\s\S]*}\s*]", text)
            if match:
                for i, group in enumerate(match.groups()):
                    logger.debug("Regex group %d: %s", i, group[:1000])  # Log truncated
                    try:
                        return parse_and_convert(match.group(0))
                    except Exception as exc2:  # noqa: BLE001
                        logger.debug("Regex parse failed: %s", exc2)
            logger.error(
                "Could not parse agent output into MemoryCreationDLO array. Truncated preview: %s",
                text[:2000],
            )
            return []
