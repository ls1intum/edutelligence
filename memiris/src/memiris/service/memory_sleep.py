import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional
from uuid import UUID

import langfuse
from jinja2 import Template
from langfuse import observe
from langfuse._client.client import Langfuse
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
    langfuse_client: Langfuse

    template_deduplication: Template
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
        self.template_connector = create_template(
            template_connector, "memory_sleep/memory_connector.md.j2"
        )

        self.langfuse_client = langfuse.get_client()

    @observe(name="memory-sleep")
    def run_sleep(self, tenant: str, **kwargs):
        """
        Run the sleep service for the memory system.
        This method will be called periodically to process recent memories.
        """

        # 1. Load recent memories
        recent_memories = self.memory_repository.find_unslept_memories(tenant)
        logging.debug(
            "Loaded %s unslept memories for tenant %s", len(recent_memories), tenant
        )

        # 2. Deduplicate memories within themselves
        deduplicated_memories = self._deduplicate_memories(
            recent_memories, tenant, **kwargs
        )
        logging.debug(
            "Deduplicated %s memories down to %s memories within themselves for tenant %s",
            len(recent_memories),
            len(deduplicated_memories),
            tenant,
        )

        # 3. Deduplicate memories with existing memories
        deduplicated_memories2 = self._deduplicate_with_existing_memories(
            deduplicated_memories, tenant, **kwargs
        )
        logging.debug(
            "Deduplicated %s memories with existing memories down to %s memories for tenant %s",
            len(deduplicated_memories),
            len(deduplicated_memories2),
            tenant,
        )

        # 4. Connect memories with each other
        self._connect_memories(deduplicated_memories2, tenant, **kwargs)
        logging.debug(
            "Connected %s memories with each other for tenant %s",
            len(deduplicated_memories2),
            tenant,
        )

        # 5. Connect memories with existing memories
        # self._connect_memories(saved_memories, tenant, **kwargs)

        # 6. Resolve transitive connections
        # self._resolve_transitive_connections(saved_memories, tenant, **kwargs)

    @observe(name="internal-only-memory-deduplication")
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
            logging.warning("No recent memories to deduplicate.")
            return []

        # If there's only one memory, no need to deduplicate
        if len(recent_memories) == 1:
            logging.warning("Only one memory found, no deduplication needed.")
            return recent_memories

        # Collect all learning IDs from all memories
        all_learning_ids = []
        for memory in recent_memories:
            if memory.id:  # Only include memories that have an ID
                all_learning_ids.extend(memory.learnings)

        logging.debug(
            "Found %s learning IDs across %s recent memories for tenant %s",
        )

        # Fetch all learnings in a single batch operation to minimize DB calls
        all_learnings = (
            self.learning_repository.find_by_ids(tenant, list(set(all_learning_ids)))
            if all_learning_ids
            else []
        )

        logging.debug(
            "Fetched %s learnings for %s learning IDs in tenant %s",
            len(all_learnings),
            len(list(set(all_learning_ids))),
            tenant,
        )

        logging.debug("Current state is:")
        logging.debug("Memories: %s", recent_memories)
        logging.debug("Learnings: %s", all_learnings)

        # Create a lookup dictionary for quick access to learning objects
        learning_lookup = {str(learning.id): learning for learning in all_learnings}

        # Prepare memory data for LLM processing using the new DTO
        memory_input_dtos = []
        valid_memories = []

        logging.debug("Converting recent memories to input DTOs for deduplication.")

        for memory in recent_memories:
            if not memory.id:
                logging.warning("Skipping memory without ID: %s", memory)
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

        logging.debug(
            "Converted %s valid memories to %s input DTOs for deduplication.",
            len(valid_memories),
            len(memory_input_dtos),
        )

        # If no valid memories with IDs, return original list
        if not memory_input_dtos:
            logging.debug("No valid memories with IDs found for deduplication.")
            return recent_memories

        # Prepare the prompt for the LLM
        memory_json_schema = MemoryDeduplicationDto.json_array_schema()
        memory_input_schema = MemoryDeduplicationInputDto.json_array_schema()

        system_message = self.template_deduplication.render(
            memory_deduplication_json_schema=memory_json_schema,
            memory_deduplication_input_schema=memory_input_schema,
            **kwargs,
        )

        logging.debug("System message for LLM deduplication: %s", system_message)

        # Use type adapter for proper JSON serialization
        memory_input_json = MemoryDeduplicationInputDto.json_array_type().dump_json(
            memory_input_dtos
        )

        logging.debug("Memory input JSON for LLM deduplication: %s", memory_input_json)

        messages = [
            Message(role="system", content=system_message),
            Message(role="user", content=str(memory_input_json)),
        ]

        logging.debug("Sending messages to LLM for deduplication")

        # Call the LLM to deduplicate memories
        response = self.ollama_service.chat(
            model=self.response_llm,
            messages=messages,
            response_format=MemoryDeduplicationDto.json_array_type().json_schema(),
            options={"temperature": 0.05},
        )

        logging.debug(
            "Received response from LLM for deduplication: %s", response.message.content
        )

        # Process LLM response
        if not response or not response.message or not response.message.content:
            logging.warning("No valid response from LLM for deduplication.")
            return recent_memories

        try:
            logging.debug("Parsing deduplicated memories from LLM response.")

            # Parse the deduplicated memories from the LLM response
            memory_dtos = MemoryDeduplicationDto.json_array_type().validate_json(
                response.message.content
            )

            logging.debug(
                "Parsed %s deduplicated memory DTOs from LLM response.",
                len(memory_dtos),
            )

            # Create a lookup of original memories by ID for easy access
            memory_lookup = {str(memory.id): memory for memory in valid_memories}

            # Track which memories were used in deduplication (to be deleted later)
            used_memory_ids = set()
            deduplicated_results = []
            created_from_connections = []

            for memory_dto in memory_dtos:
                # Skip if no memories are referenced (shouldn't happen)
                if not memory_dto.memories:
                    logging.warning(
                        "Skipping memory DTO with no referenced memories: %s",
                        memory_dto,
                    )
                    continue

                # If only one memory is referenced, it wasn't deduplicated
                if len(memory_dto.memories) == 1:
                    memory_id = memory_dto.memories[0]
                    if str(memory_id) in memory_lookup:
                        deduplicated_results.append(memory_lookup[str(memory_id)])
                    logging.warning(
                        "Skipping memory DTO with single reference: %s", memory_dto
                    )
                    continue

                # Multiple memories were combined - create a new consolidated memory
                original_memories = [
                    memory_lookup[str(mid)]
                    for mid in memory_dto.memories
                    if str(mid) in memory_lookup
                ]

                logging.debug(
                    "Found %s original memories for memory DTO: %s",
                    len(original_memories),
                    memory_dto,
                )

                if not original_memories:
                    logging.warning(
                        "No valid original memories found for memory DTO: %s",
                        memory_dto,
                    )
                    continue

                # Combine all learnings from the original memories
                combined_learnings = []
                for memory in original_memories:
                    combined_learnings.extend(memory.learnings)
                    used_memory_ids.add(str(memory.id))

                logging.debug(
                    "Combined %s learnings from original memories.",
                    len(combined_learnings),
                )
                logging.debug(
                    "We have used the following memory IDs so far: %s", used_memory_ids
                )

                # Create new memory with combined information
                new_memory = Memory(
                    uid=uuid.uuid4(),
                    title=memory_dto.title,
                    content=memory_dto.content,
                    learnings=combined_learnings,
                    slept_on=True,  # Mark as slept on since we're processing it
                )

                connection = MemoryConnection(
                    connection_type=ConnectionType.CREATED_FROM,
                    memories=[m.id for m in original_memories] + [new_memory.id],  # type: ignore
                )
                created_from_connections.append(connection)

                logging.debug(
                    "Creating new memory with title: %s and content: %s",
                )

                # Vectorize the new memory
                new_memory.vectors = self.vectorizer.vectorize(new_memory.content)

                deduplicated_results.append(new_memory)

            # Add memories that weren't used in any deduplication
            for memory in valid_memories:
                if str(memory.id) not in used_memory_ids:
                    # Mark as slept on since we're processing it
                    memory.slept_on = True
                    deduplicated_results.append(memory)
                    logging.debug(
                        "Adding unused memory with ID %s to deduplicated results.",
                        memory.id,
                    )

            deduplicated_results = self.memory_repository.save_all(
                tenant, deduplicated_results
            )

            self.memory_connection_repository.save_all(tenant, created_from_connections)

            # Mark the original memories as deleted instead of actually deleting them
            for memory_id in used_memory_ids:
                # Fetch the memory
                try:
                    memory_to_mark = self.memory_repository.find(
                        tenant, UUID(memory_id)
                    )
                    # Mark as deleted
                    memory_to_mark.slept_on = True
                    memory_to_mark.deleted = True
                    # Save the updated memory
                    self.memory_repository.save(tenant, memory_to_mark)
                except Exception as e:
                    print(f"Error marking memory {memory_id} as deleted: {e}")

            return deduplicated_results

        except Exception as e:
            print(f"Error processing deduplicated memories: {e}")
        return recent_memories

    @observe(name="with-existing-memory-deduplication")
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
            logging.warning(
                "No deduplicated memories to process for existing memory deduplication."
            )
            return []

        # If we don't have any vectors, we can't find similar memories
        memories_with_vectors = [m for m in deduplicated_memories if m.vectors]
        if not memories_with_vectors:
            logging.warning(
                "No memories with vectors found for deduplication with existing memories."
            )
            return deduplicated_memories

        logging.debug(
            "Found %s/%s memories with vectors for deduplication with existing memories in tenant %s",
            len(memories_with_vectors),
            len(deduplicated_memories),
            tenant,
        )

        # Process memories in chunks to avoid overwhelming the vector database or LLM
        chunk_size = 5  # Can be adjusted based on performance needs
        memory_chunks = [
            memories_with_vectors[i : i + chunk_size]
            for i in range(0, len(memories_with_vectors), chunk_size)
        ]

        logging.debug(
            "Split deduplicated memories into %s chunks of size %s for processing.",
            len(memory_chunks),
            chunk_size,
        )

        final_deduplicated_memories = []
        memories_without_vectors = [m for m in deduplicated_memories if not m.vectors]

        kwargs["langfuse_parent_observation_id"] = (
            self.langfuse_client.get_current_observation_id()
        )

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

                    logging.debug(
                        "Processed chunk with %s memories, resulting in %s deduplicated memories.",
                        len(future_to_chunk[future]),
                        len(deduplicated_chunk),
                    )
                except Exception as e:
                    print(f"Error processing chunk: {e}")

        logging.debug(
            "Processed all chunks, resulting in %s -> %s total deduplicated memories.",
            len(deduplicated_memories),
            len(final_deduplicated_memories),
        )

        # Add back memories without vectors that couldn't be deduplicated
        final_deduplicated_memories.extend(memories_without_vectors)

        return final_deduplicated_memories

    @observe(name="process-memories-chunk")
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
                logging.warning("Skipping memory without vectors: %s", memory)
                continue

            found_memories = self.memory_repository.search_multi(
                tenant=tenant,
                vectors=memory.vectors,
                count=5,
                # min_similarity=0.7  # Minimum similarity threshold
            )

            logging.debug(
                "Found %s similar memories for memory ID %s in tenant %s",
                len(found_memories),
                memory.id,
                tenant,
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
            logging.debug(
                "No similar memories found for chunk, returning original memory chunk."
            )
            return memory_chunk

        logging.debug(
            "Found %s similar memories for chunk of size %s in tenant %s",
            len(similar_memories),
            len(memory_chunk),
            tenant,
        )

        # Combine the chunk and similar memories for deduplication
        combined_memories = memory_chunk + similar_memories

        # Deduplicate using the same method as for internal deduplication
        deduplicated_chunk = self._deduplicate_memories(
            combined_memories, tenant, **kwargs
        )

        logging.debug(
            "Deduplicated chunk of size %s down to %s memories after comparing with existing memories in tenant %s",
            len(combined_memories),
            len(deduplicated_chunk),
            tenant,
        )

        return deduplicated_chunk

    @observe(name="connect-memories")
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
        if not memories or len(memories) < 2:
            logging.warning("Not enough memories to connect. Returning original list.")
            return memories

        # Prepare memory data for LLM processing
        memory_input_dtos = []
        valid_memories = []

        logging.debug("Converting memories to input DTOs for connection analysis.")

        for memory in memories:
            if not memory.id:
                logging.warning("Skipping memory without ID: %s", memory)
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
            logging.warning(
                "Not enough valid memories with IDs for connection analysis."
            )
            return memories

        logging.debug(
            "Converted %s valid memories to %s input DTOs for connection analysis.",
            len(valid_memories),
            len(memory_input_dtos),
        )

        # Prepare the prompt for the LLM
        memory_connection_json_schema = MemoryConnectionDto.json_array_schema()

        system_message = self.template_connector.render(
            memory_connection_json_schema=memory_connection_json_schema,
            connection_types=get_enum_values_with_descriptions(ConnectionType),
            **kwargs,
        )

        logging.debug(
            "System message for LLM connection analysis: \n%s", system_message
        )

        # Use type adapter for proper JSON serialization
        memory_input_json = MemoryDeduplicationInputDto.json_array_type().dump_json(
            memory_input_dtos
        )

        messages = [
            Message(role="system", content=system_message),
            Message(role="user", content=str(memory_input_json)),
        ]

        logging.debug("Sending messages to LLM for connection analysis")

        # Call the LLM to identify connections between memories
        response = self.ollama_service.chat(
            model=self.response_llm,
            messages=messages,
            response_format=MemoryConnectionDto.json_array_type().json_schema(),
            options={"temperature": 0.05},
        )

        # Process LLM response
        if not response or not response.message or not response.message.content:
            logging.warning("No valid response from LLM for memory connections.")
            return memories

        logging.debug(
            "Received response from LLM for connection analysis: %s",
            response.message.content,
        )

        try:
            logging.debug("Parsing memory connections from LLM response.")

            # Parse the connections from the LLM response
            connection_dtos = MemoryConnectionDto.json_array_type().validate_json(
                response.message.content
            )

            logging.debug(
                "Parsed %s memory connection DTOs from LLM response.",
                len(connection_dtos),
            )

            # Create memory connections from DTOs
            connections = []

            for connection_dto in connection_dtos:
                if len(connection_dto.memories) < 2:
                    logging.warning(
                        "Skipping connection DTO with less than 2 memories: %s",
                        connection_dto,
                    )
                    continue

                try:
                    connection_type = ConnectionType(connection_dto.connection_type)
                except ValueError:
                    connection_type = ConnectionType.RELATED

                connection = MemoryConnection(
                    connection_type=connection_type,
                    memories=connection_dto.memories,
                    description=connection_dto.description,
                    weight=connection_dto.weight or 0.5,
                )

                logging.debug(
                    "Creating connection: %s with type %s, memories %s, description '%s', weight %s",
                )

                connections.append(connection)

            if connections:
                logging.debug(
                    "Saving %s memories connections to the repository.",
                    len(connections),
                )
                connections = self.memory_connection_repository.save_all(
                    tenant, connections
                )
                logging.debug(
                    "Saved %s memories connections to the repository.", len(connections)
                )

            memories_dict = {
                memory.id: memory for memory in valid_memories if memory.id
            }

            logging.debug(
                "Updating %s memories with their connections.", len(memories_dict)
            )

            # Update each memory with its connections
            for connection in connections:
                for memory_id in connection.memories:
                    if str(memory_id) in memories_dict:
                        memory = memories_dict[memory_id]
                        if not memory.connections:
                            memory.connections = []
                        memory.connections.append(connection.id)  # type: ignore

            logging.debug(
                "Updated memories with their connections. Total memories: %s",
                len(memories_dict),
            )

            return memories

        except Exception as e:
            print(f"Error processing memory connections: {e}")
            return memories
