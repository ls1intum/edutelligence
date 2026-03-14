import json
import logging
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

    def _normalize_output_text(self, output_text: str) -> str:
        """Strip markdown code fences and surrounding whitespace from model output."""
        text = output_text.strip()
        if not text.startswith("```"):
            return text

        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[0].strip().lower() == "json":
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    def _extract_balanced_json_array(self, text: str) -> Optional[str]:
        """Return the first balanced JSON array substring found in text."""
        start = text.find("[")
        if start < 0:
            return None

        depth = 0
        in_string = False
        escaped = False

        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1].strip()

        return None

    def _extract_decoder_candidates(self, text: str) -> List[str]:
        """Use stdlib decoder to recover top-level arrays with trailing garbage."""
        decoder = json.JSONDecoder()
        candidates: List[str] = []

        for start, char in enumerate(text):
            if char != "[":
                continue

            parsed: Any = None
            end = 0
            try:
                parsed, end = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                parsed = None

            if isinstance(parsed, list):
                candidates.append(text[start : start + end].strip())
                candidates.append(json.dumps(parsed))
                break

        return candidates

    def _extract_json_array_candidates(self, text: str) -> List[tuple[str, str]]:
        """Build ordered parse candidates from strict to recovery-oriented."""
        candidates: List[tuple[str, str]] = []
        seen: set[str] = set()

        def add(label: str, candidate: Optional[str]) -> None:
            if not candidate:
                return
            normalized = candidate.strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            candidates.append((label, normalized))

        add("raw", text)
        add("balanced-array", self._extract_balanced_json_array(text))

        for index, decoded in enumerate(self._extract_decoder_candidates(text)):
            add(f"decoder-{index}", decoded)

        # Handle common corruption where one or more extra closing brackets are appended.
        trimmed = text.rstrip()
        while trimmed.endswith("]"):
            trimmed = trimmed[:-1].rstrip()
            if not trimmed:
                break
            add("trim-extra-bracket", trimmed)

        return candidates

    def _parse_memory_dlos(self, candidate: str) -> List[MemoryCreationDLO]:
        return MemoryCreationDLO.json_array_type().validate_json(candidate)

    def _convert_dlos_to_memories(
        self, memory_dlos: List[MemoryCreationDLO], tenant: str
    ) -> List[Memory]:
        needed: List[Learning] = []
        lookup_cache: dict[Any, Optional[Learning]] = {}

        for memory_dlo in memory_dlos:
            for learning_id in memory_dlo.learnings:
                if learning_id not in lookup_cache:
                    learning: Optional[Learning] = None
                    try:
                        learning = self.learning_repository.find(tenant, learning_id)
                    except (
                        Exception
                    ) as exc:  # noqa: BLE001 - repository may raise various errors
                        logger.debug(
                            "Learning lookup failed for tenant=%s id=%s: %s",
                            tenant,
                            learning_id,
                            exc,
                        )
                    lookup_cache[learning_id] = learning
                resolved = lookup_cache.get(learning_id)
                if resolved and resolved not in needed:
                    needed.append(resolved)

        return [
            creation_dlo_to_memory(memory_dlo, needed) for memory_dlo in memory_dlos
        ]

    def _parse_memories_from_output(
        self, output_text: str, tenant: str
    ) -> List[Memory]:
        text = self._normalize_output_text(output_text)

        last_exception: Optional[Exception] = None
        for strategy, candidate in self._extract_json_array_candidates(text):
            try:
                memory_dlos = self._parse_memory_dlos(candidate)
                if strategy != "raw":
                    logger.info(
                        "Recovered parseable memory JSON using strategy=%s", strategy
                    )
                return self._convert_dlos_to_memories(memory_dlos, tenant)
            except Exception as exc:  # noqa: BLE001 - parsing may raise pydantic errors
                last_exception = exc
                logger.info("Parse failed using strategy=%s: %s", strategy, exc)

        logger.error(
            "Could not parse agent output into MemoryCreationDLO array. Last error: %s. Truncated preview: %s",
            last_exception,
            text[:2000],
        )
        return []

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
        return self._parse_memories_from_output(output_text, tenant)
