from typing import List, Optional
from uuid import UUID

from jinja2 import Template
from ollama import Message

from memiris.domain.memory import Memory
from memiris.dto.memory_deduplication_dto import MemoryDeduplicationDto
from memiris.dto.memory_deduplication_input_dto import (
    LearningInfoDto,
    MemoryDeduplicationInputDto,
)
from memiris.repository.learning_repository import LearningRepository
from memiris.repository.memory_repository import MemoryRepository
from memiris.service.ollama_wrapper import OllamaService
from memiris.service.vectorizer import Vectorizer
from memiris.util.jinja_util import create_template


class MemorySleeper:
    """
    The sleep service for the memory system.
    It is responsible for regularly going through the recent memories and combining and connecting them with
    themselves and existing memories.
    """

    tool_llm: str
    response_llm: str
    learning_repository: LearningRepository
    memory_repository: MemoryRepository
    vectorizer: Vectorizer
    ollama_service: OllamaService

    template_deduplication: Template
    template_deduplication_with_tools: Template
    template_connector: Template

    def __init__(
        self,
        tool_llm: str,
        response_llm: str,
        learning_repository: LearningRepository,
        memory_repository: MemoryRepository,
        vectorizer: Vectorizer,
        ollama_service: OllamaService,
        template_deduplication: Optional[str] = None,
        template_deduplication_with_tools: Optional[str] = None,
        template_connector: Optional[str] = None,
    ) -> None:
        """
        Initialize the LearningExtractor

        Args:
            tool_llm: The language model to use for tool operations
            response_llm: The language model to use for responses
            learning_repository: Repository for learning operations
            memory_repository: Repository for memory operations
            vectorizer: Service for vectorizing content
            ollama_service: The Ollama service to use for LLM calls
            template_deduplication: Optional template path for deduplication
            template_deduplication_with_tools: Optional template path for deduplication with tools
            template_connector: Optional template path for connector
        """
        self.tool_llm = tool_llm
        self.response_llm = response_llm

        self.learning_repository = learning_repository
        self.memory_repository = memory_repository
        self.vectorizer = vectorizer
        self.ollama_service = ollama_service

        self.template_deduplication = create_template(
            template_deduplication, "memory_sleep/memory_deduplication.md.j2"
        )
        self.template_deduplication_with_tools = create_template(
            template_deduplication_with_tools,
            "memory_sleep/memory_deduplication_with_tools.md.j2",
        )
        self.template_connector = create_template(
            template_connector, "memory_sleep/memory_connector.md.j2"
        )

    def run_sleep(self, tenant: str, **kwargs):
        """
        Run the sleep service for the memory system.
        This method will be called periodically to process recent memories.
        """

        # 1. Load recent memories
        recent_memories = self.memory_repository.find_unslept_memories(tenant)

        # 2. Deduplicate memories within themselves
        deduplicated_memories = self._deduplicate_memories(
            recent_memories, tenant, **kwargs
        )

        # 3. Deduplicate memories with existing memories
        # deduplicated_memories = self._deduplicate_with_existing_memories(
        #    recent_memories, deduplicated_memories, tenant, **kwargs
        # )

        # 4. Save changed memories
        saved_memories: List[Memory] = []
        for memory in deduplicated_memories:
            saved_memory = self.memory_repository.save(tenant, memory)
            saved_memories.append(saved_memory)

        # 5. Connect memories with each other
        # connected_memories = self._connect_memories(saved_memories, tenant, **kwargs)

        # 6. Connect memories with existing memories
        # self._connect_memories(saved_memories, tenant, **kwargs)

        # 7. Resolve transitive connections
        # self._resolve_transitive_connections(saved_memories, tenant, **kwargs)

    def _deduplicate_memories(
        self, recent_memories: List[Memory], tenant: str, **kwargs
    ) -> List[Memory]:
        """
        Deduplicate recent memories using an LLM.

        This method:
        1. Transforms memories into a format suitable for LLM processing, including relevant learnings
        2. Uses the LLM to identify duplicate memories and consolidate them
        3. Creates new Memory objects with combined information and learning references
        4. Marks original (now deduplicated) memories for deletion
        5. Returns the deduplicated memory list

        Args:
            recent_memories: List of memories to deduplicate
            tenant: The tenant identifier
            **kwargs: Additional arguments to pass to the LLM

        Returns:
            List of deduplicated memories
        """
        if not recent_memories:
            return []

        # If there's only one memory, no need to deduplicate
        if len(recent_memories) == 1:
            return recent_memories

        # Collect all learning IDs from all memories
        all_learning_ids = []
        for memory in recent_memories:
            if memory.id:  # Only include memories that have an ID
                all_learning_ids.extend(memory.learnings)

        # Fetch all learnings in a single batch operation to minimize DB calls
        all_learnings = (
            self.learning_repository.find_by_ids(tenant, all_learning_ids)
            if all_learning_ids
            else []
        )

        # Create a lookup dictionary for quick access to learning objects
        learning_lookup = {str(learning.id): learning for learning in all_learnings}

        # Prepare memory data for LLM processing using the new DTO
        memory_input_dtos = []
        valid_memories = []

        for memory in recent_memories:
            if not memory.id:
                continue

            valid_memories.append(memory)

            # Get associated learnings
            memory_learnings = []
            for learning_id in memory.learnings:
                learning = learning_lookup.get(str(learning_id))
                if learning:
                    memory_learnings.append(
                        LearningInfoDto(
                            id=learning.id,  # type: ignore
                            title=learning.title,
                            content=learning.content,
                        )
                    )

            # Create the input DTO for this memory
            memory_input_dto = MemoryDeduplicationInputDto(
                id=memory.id,
                title=memory.title,
                content=memory.content,
                learnings=memory_learnings,
            )

            memory_input_dtos.append(memory_input_dto)

        # If no valid memories with IDs, return original list
        if not memory_input_dtos:
            return recent_memories

        # Prepare the prompt for the LLM
        memory_json_schema = MemoryDeduplicationDto.json_array_schema()
        memory_input_schema = MemoryDeduplicationInputDto.json_array_schema()

        system_message = self.template_deduplication.render(
            memory_deduplication_json_schema=memory_json_schema,
            memory_deduplication_input_schema=memory_input_schema,
            **kwargs,
        )

        # Use type adapter for proper JSON serialization
        memory_input_json = MemoryDeduplicationInputDto.json_array_type().dump_json(
            memory_input_dtos
        )

        messages = [
            Message(role="system", content=system_message),
            Message(role="user", content=str(memory_input_json)),
        ]

        # Call the LLM to deduplicate memories
        response = self.ollama_service.chat(
            model=self.tool_llm,
            messages=messages,
            response_format=MemoryDeduplicationDto.json_array_type().json_schema(),
            options={"temperature": 0.05},
        )

        # Process LLM response
        if not response or not response.message or not response.message.content:
            return recent_memories

        try:
            # Parse the deduplicated memories from the LLM response
            memory_dtos = MemoryDeduplicationDto.json_array_type().validate_json(
                response.message.content
            )

            # Create a lookup of original memories by ID for easy access
            memory_lookup = {str(memory.id): memory for memory in valid_memories}

            # Track which memories were used in deduplication (to be deleted later)
            used_memory_ids = set()
            deduplicated_results = []

            for memory_dto in memory_dtos:
                # Skip if no memories are referenced (shouldn't happen)
                if not memory_dto.memories:
                    continue

                # If only one memory is referenced, it wasn't deduplicated
                if len(memory_dto.memories) == 1:
                    memory_id = memory_dto.memories[0]
                    if str(memory_id) in memory_lookup:
                        deduplicated_results.append(memory_lookup[str(memory_id)])
                    continue

                # Multiple memories were combined - create a new consolidated memory
                original_memories = [
                    memory_lookup[str(mid)]
                    for mid in memory_dto.memories
                    if str(mid) in memory_lookup
                ]

                if not original_memories:
                    continue

                # Combine all learnings from the original memories
                combined_learnings = []
                for memory in original_memories:
                    combined_learnings.extend(memory.learnings)
                    used_memory_ids.add(str(memory.id))

                # Create new memory with combined information
                new_memory = Memory(
                    title=memory_dto.title,
                    content=memory_dto.content,
                    learnings=combined_learnings,
                    slept_on=True,  # Mark as slept on since we're processing it
                )

                # Vectorize the new memory
                new_memory.vectors = self.vectorizer.vectorize(new_memory.content)

                deduplicated_results.append(new_memory)

            self.memory_repository.save_all(tenant, deduplicated_results)

            # Add memories that weren't used in any deduplication
            for memory in valid_memories:
                if str(memory.id) not in used_memory_ids:
                    # Mark as slept on since we're processing it
                    memory.slept_on = True
                    deduplicated_results.append(memory)

            # Mark the original memories as deleted instead of actually deleting them
            for memory_id in used_memory_ids:
                # Fetch the memory
                try:
                    memory_to_mark = self.memory_repository.find(
                        tenant, UUID(memory_id)
                    )
                    # Mark as deleted
                    memory_to_mark.deleted = True
                    # Save the updated memory
                    self.memory_repository.save(tenant, memory_to_mark)
                except Exception as e:
                    print(f"Error marking memory {memory_id} as deleted: {e}")

            return deduplicated_results

        except Exception as e:
            print(f"Error processing deduplicated memories: {e}")
        return recent_memories


#        def _deduplicate_with_existing_memories(
#            self,
#            recent_memories: List[Memory],
#            deduplicated_memories: List[Memory],
#            tenant: str,
#            **kwargs,
#        ) -> List[Memory]:
#            pass
#
#        def _connect_memories(
#            self, memories: List[Memory], tenant: str, **kwargs
#        ) -> List[Memory]:
#            """
#            Connect memories with each other.
#            This method will be called after deduplication to create links between memories.
#            """
#            pass
#
#        def _resolve_transitive_connections(
#            self, memories: List[Memory], tenant: str, **kwargs
#        ) -> None:
#            """
#            Resolve transitive connections between memories.
#            This method will ensure that if A is connected to B and B is connected to C, then A is also connected to C.
#            """
#            pass
