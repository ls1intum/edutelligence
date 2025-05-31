from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional
from uuid import UUID

from jinja2 import Template
from ollama import Message

from memiris.domain.memory import Memory
from memiris.domain.memory_connection import ConnectionType, MemoryConnection
from memiris.dto.memory_connection_dto import MemoryConnectionDto
from memiris.dto.memory_deduplication_dto import MemoryDeduplicationDto
from memiris.dto.memory_deduplication_input_dto import (
    LearningInfoDto,
    MemoryDeduplicationInputDto,
)
from memiris.repository.learning_repository import LearningRepository
from memiris.repository.memory_connection_repository import MemoryConnectionRepository
from memiris.repository.memory_repository import MemoryRepository
from memiris.service.ollama_wrapper import OllamaService
from memiris.service.vectorizer import Vectorizer
from memiris.util.enum_util import get_enum_values_with_descriptions
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
    memory_connection_repository: MemoryConnectionRepository
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
        memory_connection_repository: MemoryConnectionRepository,
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
        self.memory_connection_repository = memory_connection_repository
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
        deduplicated_memories2 = self._deduplicate_with_existing_memories(
            deduplicated_memories, tenant, **kwargs
        )

        # 4. Connect memories with each other
        self._connect_memories(deduplicated_memories2, tenant, **kwargs)

        # 5. Connect memories with existing memories
        # self._connect_memories(saved_memories, tenant, **kwargs)

        # 6. Resolve transitive connections
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

            deduplicated_results = self.memory_repository.save_all(
                tenant, deduplicated_results
            )

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

    def _deduplicate_with_existing_memories(
        self,
        deduplicated_memories: List[Memory],
        tenant: str,
        **kwargs,
    ) -> List[Memory]:
        """
        Deduplicate deduplicated memories with existing memories in the system.
        For this the memories will be split into chunks, and each chunk will be processed in parallel:
        1. Find existing memories that are similar to those in the chunk
        2. Transform the chunk into a format suitable for LLM processing
        3. Use the LLM to identify duplicate memories and consolidate them using the _deduplicate_memories method
        4. Done

        Args:
            deduplicated_memories: List of memories that have already been deduplicated within themselves
            tenant: The tenant identifier
            **kwargs: Additional arguments to pass to the LLM

        Returns:
            List of deduplicated memories after comparing with existing memories
        """
        if not deduplicated_memories:
            return []

        # If we don't have any vectors, we can't find similar memories
        memories_with_vectors = [m for m in deduplicated_memories if m.vectors]
        if not memories_with_vectors:
            return deduplicated_memories

        # Process memories in chunks to avoid overwhelming the vector database or LLM
        chunk_size = 5  # Can be adjusted based on performance needs
        memory_chunks = [
            memories_with_vectors[i : i + chunk_size]
            for i in range(0, len(memories_with_vectors), chunk_size)
        ]

        final_deduplicated_memories = []
        memories_without_vectors = [m for m in deduplicated_memories if not m.vectors]

        # Process each chunk in parallel
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_chunk = {
                executor.submit(self._process_chunk, chunk, tenant, **kwargs): chunk
                for chunk in memory_chunks
            }

            for future in as_completed(future_to_chunk):
                try:
                    deduplicated_chunk = future.result()
                    final_deduplicated_memories.extend(deduplicated_chunk)
                except Exception as e:
                    print(f"Error processing chunk: {e}")

        # Add back memories without vectors that couldn't be deduplicated
        final_deduplicated_memories.extend(memories_without_vectors)

        return final_deduplicated_memories

    def _process_chunk(
        self, memory_chunk: List[Memory], tenant: str, **kwargs
    ) -> List[Memory]:
        """
        Process a chunk of memories to find similar existing memories and deduplicate them.

        Args:
            memory_chunk: List of memories in the chunk
            tenant: The tenant identifier
            **kwargs: Additional arguments to pass to the LLM

        Returns:
            List of deduplicated memories for the chunk
        """
        # Find similar memories in the repository
        similar_memories = []
        for memory in memory_chunk:
            # Find existing memories with similar vectors
            if not memory.vectors:
                continue

            found_memories = self.memory_repository.search_multi(
                tenant=tenant,
                vectors=memory.vectors,
                count=5,
                # min_similarity=0.7  # Minimum similarity threshold
            )

            # Exclude memories that are already in our input set
            for found_memory in found_memories:
                if (
                    found_memory not in memory_chunk
                    and found_memory not in similar_memories
                ):
                    similar_memories.append(found_memory)

        # If no similar memories found, just keep the original chunk
        if not similar_memories:
            return memory_chunk

        # Combine the chunk and similar memories for deduplication
        combined_memories = memory_chunk + similar_memories

        # Deduplicate using the same method as for internal deduplication
        deduplicated_chunk = self._deduplicate_memories(
            combined_memories, tenant, **kwargs
        )

        return deduplicated_chunk

    def _connect_memories(
        self, memories: List[Memory], tenant: str, **kwargs
    ) -> List[Memory]:
        """
        Connect memories with each other using an LLM.

        This method:
        1. Transforms memories into a format suitable for LLM processing
        2. Uses the LLM to identify meaningful connections between memories
        3. Creates MemoryConnection objects to represent these relationships
        4. Stores the connections in the repository
        5. Returns the original memories (connections are stored separately)

        Args:
            memories: List of memories to analyze for connections
            tenant: The tenant identifier
            **kwargs: Additional arguments to pass to the LLM

        Returns:
            The original list of memories (connections are stored separately)
        """
        if (
            not memories or len(memories) < 2
        ):  # Need at least 2 memories to form connections
            return memories

        # Prepare memory data for LLM processing
        memory_input_dtos = []
        valid_memories = []

        for memory in memories:
            if not memory.id:
                continue

            valid_memories.append(memory)

            # Create the input DTO for this memory (simplified for connection identification)
            memory_input_dto = MemoryDeduplicationInputDto(
                id=memory.id,
                title=memory.title,
                content=memory.content,
                learnings=[],  # We don't need detailed learning info for connections
            )

            memory_input_dtos.append(memory_input_dto)

        # If insufficient valid memories, return original list
        if len(memory_input_dtos) < 2:
            return memories

        # Prepare the prompt for the LLM
        memory_connection_json_schema = MemoryConnectionDto.json_array_schema()

        system_message = self.template_connector.render(
            memory_connection_json_schema=memory_connection_json_schema,
            connection_types=get_enum_values_with_descriptions(ConnectionType),
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

        # Call the LLM to identify connections between memories
        response = self.ollama_service.chat(
            model=self.tool_llm,
            messages=messages,
            response_format=MemoryConnectionDto.json_array_type().json_schema(),
            options={"temperature": 0.05},
        )

        # Process LLM response
        if not response or not response.message or not response.message.content:
            return memories

        try:
            # Parse the connections from the LLM response
            connection_dtos = MemoryConnectionDto.json_array_type().validate_json(
                response.message.content
            )

            # Create memory connections from DTOs
            connections = []

            for connection_dto in connection_dtos:
                if len(connection_dto.memories) < 2:
                    continue

                try:
                    connection_type = ConnectionType(connection_dto.connection_type)
                except ValueError:
                    connection_type = ConnectionType.RELATED

                connection = MemoryConnection(
                    connection_type=connection_type,
                    memories=connection_dto.memories,
                    description=connection_dto.description,
                    confidence=connection_dto.confidence or 0.5,
                )

                connections.append(connection)

            if connections:
                connections = self.memory_connection_repository.save_all(
                    tenant, connections
                )

            memories_dict = {
                memory.id: memory for memory in valid_memories if memory.id
            }

            # Update each memory with its connections
            for connection in connections:
                for memory_id in connection.memories:
                    if str(memory_id) in memories_dict:
                        memory = memories_dict[memory_id]
                        if not memory.connections:
                            memory.connections = []
                        memory.connections.append(connection.id)  # type: ignore

            return memories

        except Exception as e:
            print(f"Error processing memory connections: {e}")
            return memories
