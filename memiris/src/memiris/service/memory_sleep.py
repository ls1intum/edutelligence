import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple
from uuid import UUID

import langfuse
from jinja2 import Template
from langfuse import observe
from langfuse._client.client import Langfuse
from ollama import Message

from memiris.dlo.memory_connection_dlo import MemoryConnectionDLO
from memiris.dlo.memory_deduplication_dlo import MemoryDeduplicationDLO
from memiris.dlo.memory_deduplication_input_dlo import (
    LearningInfoDLO,
    MemoryDeduplicationInputDLO,
)
from memiris.domain.learning import Learning
from memiris.domain.memory import Memory
from memiris.domain.memory_connection import ConnectionType, MemoryConnection
from memiris.repository.learning_repository import LearningRepository
from memiris.repository.memory_connection_repository import MemoryConnectionRepository
from memiris.repository.memory_repository import MemoryRepository
from memiris.service.ollama_wrapper import AbstractLanguageModel
from memiris.service.vectorizer import Vectorizer
from memiris.util.enum_util import get_enum_values_with_descriptions
from memiris.util.grouping import greedy_cover_max_groups
from memiris.util.jinja_util import create_template


class MemorySleeper:
    """
    The sleep service for the memory system.
    It is responsible for regularly going through the recent memories and combining and connecting them with
    themselves and existing memories.
    """

    tool_llm: AbstractLanguageModel
    response_llm: AbstractLanguageModel
    learning_repository: LearningRepository
    memory_repository: MemoryRepository
    memory_connection_repository: MemoryConnectionRepository
    vectorizer: Vectorizer
    ollama_service: None  # Deprecated: use model proxies
    langfuse_client: Langfuse

    template_deduplication: Template
    template_connector: Template

    learning_cache: dict[UUID, Learning]
    memory_cache: dict[UUID, Memory]

    max_threads: int  # Maximum number of threads for parallel processing
    group_size: int  # Size of memory groups, can be larger to meet the max_groups limit
    max_groups: int  # Maximum number of groups to process in parallel

    def __init__(
        self,
        tool_llm: AbstractLanguageModel,
        response_llm: AbstractLanguageModel,
        learning_repository: LearningRepository,
        memory_repository: MemoryRepository,
        memory_connection_repository: MemoryConnectionRepository,
        vectorizer: Vectorizer,
        template_deduplication: Optional[str] = None,
        template_connector: Optional[str] = None,
        max_threads: int | None = None,
        group_size: int | None = None,
        max_groups: int | None = None,
    ) -> None:
        """
        Initialize the LearningExtractor

        Args:
            tool_llm: The language model to use for tool operations
            response_llm: The language model to use for responses
            learning_repository: Repository for learning operations
            memory_repository: Repository for memory operations
            vectorizer: Service for vectorizing content
            ollama_service: Deprecated. Use model proxies.
            template_deduplication: Optional template path for deduplication
            template_deduplication_with_tools: Optional template path for deduplication with tools
            template_connector: Optional template path for connector
            max_threads: Maximum number of threads for parallel processing
            group_size: Size of memory groups for processing
        """
        self.tool_llm = tool_llm
        self.response_llm = response_llm

        self.learning_repository = learning_repository
        self.memory_repository = memory_repository
        self.memory_connection_repository = memory_connection_repository
        self.vectorizer = vectorizer
        self.ollama_service = None

        self.template_deduplication = create_template(
            template_deduplication, "memory_sleep/memory_deduplication.md.j2"
        )
        self.template_connector = create_template(
            template_connector, "memory_sleep/memory_connector.md.j2"
        )

        self.langfuse_client = langfuse.get_client()

        self.learning_cache: dict[UUID, Learning] = {}
        self.memory_cache: dict[UUID, Memory] = {}

        self.max_threads = max_threads or 5
        self.group_size = group_size or 20
        self.max_groups = max(1, max_groups or 5)

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
        if not recent_memories:
            logging.warning("No unslept memories found for tenant %s", tenant)
            return

        recent_memories = self._general_cleanup(tenant, recent_memories)

        for recent_memory in recent_memories:
            if recent_memory.id:
                self.memory_cache[recent_memory.id] = recent_memory

        # 2. Connect memories with each other
        logging.debug("Connecting memories for tenant %s", tenant)
        connection_dlos = self._create_memory_connections(recent_memories, **kwargs)

        connections = self._save_memory_connections(connection_dlos, tenant, **kwargs)

        logging.debug(
            "Created %s connections for %s recent memories in tenant %s",
            len(connections),
            len(recent_memories),
            tenant,
        )

        duplicate_connections = [
            connection
            for connection in connections
            if connection.connection_type == ConnectionType.DUPLICATE
        ]

        # 3. TODO: Filter out connections that contain memories with a CONFLICT connection

        # 4. Deduplicate memories using LLM
        self._deduplicate_memories(duplicate_connections, tenant, **kwargs)

    @observe(name="memory-cleanup")
    def _general_cleanup(self, tenant: str, memories: List[Memory]) -> List[Memory]:
        """
        General cleanup of memories. Currently, does the following:
        1. Deletes memories with no learnings.

        Args:
            tenant: The tenant identifier
            memories: List of Memory objects to process

        Returns:
            The updated list of Memory objects after cleanup
        """
        updated_memories = []

        for memory in memories:
            if len(memory.learnings) < 1:
                logging.warning(
                    "Memory %s has no learnings, permanently deleting.", memory.id
                )
                self.memory_repository.delete(tenant, memory.id)  # type: ignore
            else:
                updated_memories.append(memory)

        return updated_memories

    @observe(name="memory-data-caching")
    def _data_caching(
        self, duplicate_connections: List[MemoryConnectionDLO], tenant: str
    ):
        all_memory_ids = set(
            memory_id
            for connection in duplicate_connections
            for memory_id in connection.memories
        )

        all_memories = (
            self.memory_repository.find_by_ids(tenant, list(all_memory_ids))
            if all_memory_ids
            else []
        )

        for memory in all_memories:
            self.memory_cache[memory.id] = memory  # type: ignore

        all_learning_ids = set(
            learning_id
            for connection in duplicate_connections
            for memory_id in connection.memories
            if memory_id in self.memory_cache
            for learning_id in self.memory_cache[memory_id].learnings
        )

        logging.debug(
            "Found %s learning IDs across %s connections for tenant %s",
            len(set(all_learning_ids)),
            len(duplicate_connections),
            tenant,
        )

        # Fetch all learnings in a single batch operation to minimize DB calls
        all_learnings = (
            self.learning_repository.find_by_ids(tenant, list(all_learning_ids))
            if all_learning_ids
            else []
        )

        for learning in all_learnings:
            self.learning_cache[learning.id] = learning  # type: ignore

    @observe(name="memory-deduplication")
    def _deduplicate_memories(
        self, connections: List[MemoryConnection], tenant: str, **kwargs
    ) -> List[Memory]:
        """
        Deduplicate memories using an LLM.

        This method:
        1. Processes connections of type DUPLICATE
        2. Identifies and consolidates duplicate memories
        3. Creates new Memory objects with combined information and learning references
        4. Marks original (now deduplicated) memories for deletion
        5. Returns the deduplicated memory list

        Args:
            memory_cache: Cache of Memory objects indexed by their IDs
            connections: List of MemoryConnectionDLO objects representing connections between memories
            tenant: The tenant identifier
            **kwargs: Additional arguments to pass to the LLM

        Returns:
            List of deduplicated memories
        """
        if not connections:
            logging.warning("No connections provided for deduplication.")
            return []

        # Filter connections to only include those of type DUPLICATE
        duplicate_connections = [
            connection
            for connection in connections
            if connection.connection_type == ConnectionType.DUPLICATE
        ]

        if not duplicate_connections:
            logging.warning("No duplicate connections found for deduplication.")
            return []

        # Group memories by their IDs from the processed connections
        memory_groups: list[list[MemoryDeduplicationInputDLO]] = []
        current_group: list[MemoryDeduplicationInputDLO] = []

        for connection in duplicate_connections:
            if len(connection.memories) < 2:
                logging.warning(
                    "Skipping connection with less than 2 memories: %s", connection
                )
                continue

            new_group_elements = [
                MemoryDeduplicationInputDLO(
                    id=memory_id,
                    title=self.memory_cache[memory_id].title,
                    content=self.memory_cache[memory_id].content,
                    learnings=[
                        LearningInfoDLO(
                            id=learning_id,
                            title=self.learning_cache[learning_id].title,
                            content=self.learning_cache[learning_id].content,
                        )
                        for learning_id in self.memory_cache[memory_id].learnings
                    ],
                )
                for memory_id in connection.memories
            ]

            if len(current_group) > self.group_size:
                memory_groups.append(current_group)
                current_group = []
            elif len(current_group) + len(new_group_elements) > self.group_size * 1.5:
                memory_groups.append(current_group)
                current_group = new_group_elements
            else:
                current_group.extend(new_group_elements)

        if current_group:
            memory_groups.append(current_group)

        if not memory_groups:
            logging.warning("No valid memory groups found for deduplication.")
            return []

        logging.debug(
            "Created %s memory groups for deduplication, largest has %s memories.",
            len(memory_groups),
            max(len(group) for group in memory_groups),
        )

        # Process each memory group in parallel
        deduplicated_memories: List[Memory] = []
        created_from_connections: List[MemoryConnection] = []
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = {
                executor.submit(
                    self._process_memory_group_for_deduplication,
                    memory_group,
                    **kwargs,
                ): memory_group
                for memory_group in memory_groups[: self.max_groups]
            }

            for future in as_completed(futures):
                try:
                    result: Tuple[List[Memory], List[MemoryConnection]] = (
                        future.result()
                    )
                    memories = result[0]
                    connections = result[1]
                    if memories:
                        deduplicated_memories.extend(memories)
                    if connections:
                        created_from_connections.extend(connections)

                except Exception as e:
                    logging.error("Error processing memory group: %s", e, exc_info=True)

        logging.debug(
            "Processed %s memory groups, resulting in %s deduplicated memories.",
            len(memory_groups),
            len(deduplicated_memories),
        )

        if not deduplicated_memories:
            logging.warning("No deduplicated memories found after processing groups.")
            return []

        saved_memories = self.memory_repository.save_all(tenant, deduplicated_memories)

        saved_connections = self.memory_connection_repository.save_all(
            tenant, created_from_connections
        )

        for memory in saved_memories:
            if memory.deleted:
                self.memory_cache.pop(memory.id)  # type: ignore
            self.memory_cache[memory.id] = memory  # type: ignore

        for connection in saved_connections:
            for memory_id in connection.memories:
                self.memory_cache[memory_id].connections.append(connection.id)  # type: ignore

        return saved_memories

    @observe(name="process-memory-group-for-deduplication")
    def _process_memory_group_for_deduplication(
        self, memory_group: List[MemoryDeduplicationInputDLO], **kwargs
    ) -> Tuple[List[Memory], List[MemoryConnection]]:
        """
        Process a group of memories for deduplication.

        This method:
        1. Calls the LLM to deduplicate the memories
        2. Processes the LLM response to create new Memory objects
        3. Marks original memories as deleted

        Args:
            memory_group: List of MemoryDeduplicationInputDLO objects representing a group of memories
            tenant: The tenant identifier
            **kwargs: Additional arguments to pass to the LLM

        Returns:
            List of deduplicated Memory objects
        """
        if not memory_group:
            logging.warning("Empty memory group provided for deduplication.")
            return [], []

        # Prepare the prompt for the LLM
        memory_json_schema = MemoryDeduplicationDLO.json_array_schema()
        memory_input_schema = MemoryDeduplicationInputDLO.json_array_schema()

        system_message = self.template_deduplication.render(
            memory_deduplication_json_schema=memory_json_schema,
            memory_deduplication_input_schema=memory_input_schema,
            **kwargs,
        )

        logging.debug("System message for LLM deduplication: %s", system_message)

        # Use type adapter for proper JSON serialization
        memory_input_json = MemoryDeduplicationInputDLO.json_array_type().dump_json(
            memory_group
        )

        logging.debug("Memory input JSON for LLM deduplication: %s", memory_input_json)

        messages = [
            Message(role="system", content=system_message),
            Message(role="user", content=str(memory_input_json)),
        ]

        logging.debug("Sending messages to LLM for deduplication")

        # Call the LLM to deduplicate memories
        response = self.response_llm.chat(
            messages=messages,
            response_format=MemoryDeduplicationDLO.json_array_type().json_schema(),
            options={"temperature": 0.05},
        )

        logging.debug(
            "Received response from LLM for deduplication: %s", response.message.content
        )

        # Process LLM response
        if not response or not response.message or not response.message.content:
            logging.warning("No valid response from LLM for deduplication.")
            return [], []

        try:
            logging.debug("Parsing deduplicated memories from LLM response.")

            # Parse the deduplicated memories from the LLM response
            memory_dlos = MemoryDeduplicationDLO.json_array_type().validate_json(
                response.message.content
            )
            logging.debug(
                "Parsed %s deduplicated memory DLOs from LLM response.",
                len(memory_dlos),
            )

            # Track which memories were used in deduplication (to be deleted later)
            used_memory_ids = set()
            deduplicated_results = []
            created_from_connections = []

            for memory_dlo in memory_dlos:
                # Skip if no memories are referenced (shouldn't happen)
                if not memory_dlo.memories:
                    logging.warning(
                        "Skipping memory DLO with no referenced memories: %s",
                        memory_dlo,
                    )
                    continue

                # If only one memory is referenced, it wasn't deduplicated
                if len(memory_dlo.memories) == 1:
                    continue

                # Multiple memories were combined - create a new consolidated memory
                original_memories = [
                    self.memory_cache[memory_id] for memory_id in memory_dlo.memories
                ]

                logging.debug(
                    "Found %s original memories for memory DLO: %s",
                    len(original_memories),
                    memory_dlo,
                )

                if not original_memories:
                    logging.warning(
                        "No valid original memories found for memory DLO: %s",
                        memory_dlo,
                    )
                    continue

                # Combine all learnings from the original memories
                combined_learnings = []
                for memory in original_memories:
                    combined_learnings.extend(memory.learnings)
                    used_memory_ids.add(memory.id)

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
                    title=memory_dlo.title,
                    content=memory_dlo.content,
                    learnings=combined_learnings,
                    slept_on=True,  # Mark as slept on since we're processing it
                )

                connection = MemoryConnection(
                    connection_type=ConnectionType.CREATED_FROM,
                    memories=[new_memory.id] + [m.id for m in original_memories],  # type: ignore
                )
                created_from_connections.append(connection)

                logging.debug(
                    "Creating new memory with title: %s and content: %s",
                    new_memory.title,
                    new_memory.content,
                )
                # Vectorize the new memory
                new_memory.vectors = self.vectorizer.vectorize(new_memory.content)
                deduplicated_results.append(new_memory)

            for memory_id in used_memory_ids:
                self.memory_cache[memory_id].slept_on = True  # type: ignore
                self.memory_cache[memory_id].deleted = True  # type: ignore
                deduplicated_results.append(self.memory_cache[memory_id])  # type: ignore

            return deduplicated_results, created_from_connections
        except Exception as e:
            logging.error(
                "Error processing deduplicated memories: %s", e, exc_info=True
            )
            return [], []

    @observe(name="process-memory-connections-duplication")
    def _process_connection_type_duplicate(
        self, connections: List[MemoryConnectionDLO]
    ) -> List[MemoryConnectionDLO]:
        """
        Processing for the DUPLICATE connection type.
        This method processes connections of type DUPLICATE, ensuring that

        """
        seen_connections: dict[UUID, list[UUID]] = {}

        unique_connections: List[MemoryConnectionDLO] = []

        filtered_connections: List[MemoryConnectionDLO] = [
            connection
            for connection in connections
            if connection.connection_type == ConnectionType.DUPLICATE
        ]

        # Sorted by size of memories, largest first
        sorted_connections = sorted(
            filtered_connections,
            key=lambda x: len(x.memories),
            reverse=True,
        )

        for connection in sorted_connections:
            if len(connection.memories) < 2:
                logging.warning(
                    "Skipping connection with less than 2 memories: %s", connection
                )
                continue

            # Check if the connection is a full duplicate of existing connections
            first_memory = connection.memories[0]
            other_memories = connection.memories[1:]
            if first_memory in seen_connections:
                if all(
                    other_memory in seen_connections[first_memory]
                    for other_memory in other_memories
                ):
                    logging.debug(
                        "Skipping duplicate connection for memory %s with others %s",
                        first_memory,
                        other_memories,
                    )
                    continue

            # Add the connection to the unique list
            for memory in connection.memories:
                if memory not in seen_connections:
                    seen_connections[memory] = []
                seen_connections[memory].extend(
                    other for other in connection.memories if other != memory
                )

            logging.debug(
                "Adding unique connection for memory %s with others %s",
                first_memory,
                other_memories,
            )
            unique_connections.append(connection)

        logging.debug(
            "Processed %s connections of type DUPLICATE, resulting in %s unique connections.",
            len(filtered_connections),
            len(unique_connections),
        )

        final_connections: List[MemoryConnectionDLO] = []

        # Collect the seen connections into as few unique connections as possible
        for memory_id, ids in seen_connections.items():
            if len(ids) < 2:
                logging.debug(
                    "Skipping memory %s with less than 2 seen connections: %s",
                    memory_id,
                    ids,
                )
                continue

            # Create a new connection with the seen memories
            new_connection = MemoryConnectionDLO(
                connection_type=ConnectionType.DUPLICATE,
                memories=[memory_id] + ids,
                description="Automatically deduplicated connection",
                weight=1.0,
            )
            final_connections.append(new_connection)

            for other_memory in ids:
                seen_connections[other_memory].remove(memory_id)

        return final_connections

    @observe(name="process-memory-connections-other")
    def _process_other_connection_types(
        self, connections: List[MemoryConnectionDLO]
    ) -> List[MemoryConnectionDLO]:
        """
        Process other connection types (RELATED, CONTRADICTS, SAME_TOPIC).
        This method processes connections of types other than DUPLICATE.
        """

        filtered_connections: List[MemoryConnectionDLO] = [
            connection
            for connection in connections
            if connection.connection_type != ConnectionType.DUPLICATE
        ]

        # Turn all connections into 2 memory connections
        processed_connections: List[MemoryConnectionDLO] = []
        for connection in filtered_connections:
            if len(connection.memories) < 2:
                logging.warning(
                    "Skipping connection with less than 2 memories: %s", connection
                )
                continue

            # Create a connection for each pair of memories
            for i in range(len(connection.memories)):
                for j in range(i + 1, len(connection.memories)):
                    new_connection = MemoryConnectionDLO(
                        connection_type=connection.connection_type,
                        memories=[
                            connection.memories[i],
                            connection.memories[j],
                        ],
                        description=connection.description,
                        weight=connection.weight,
                    )
                    processed_connections.append(new_connection)

        # Remove duplicates from the processed connections
        seen_connections: set[Tuple[UUID, UUID]] = set()
        unique_connections: List[MemoryConnectionDLO] = []

        # Sort by weight
        sorted_connections: List[MemoryConnectionDLO] = sorted(
            processed_connections,
            key=lambda x: x.weight or 0.5,
            reverse=True,
        )

        for connection in sorted_connections:
            if len(connection.memories) != 2:
                logging.warning(
                    "Skipping connection with more or less than 2 memories: %s",
                    connection,
                )
                continue

            memory_pair = tuple(sorted(connection.memories))
            if memory_pair in seen_connections:
                logging.debug(
                    "Skipping duplicate connection for memory pair %s",
                    memory_pair,
                )
                continue

            logging.debug(
                "Adding unique connection for memory pair %s: %s",
                memory_pair,
                connection,
            )

            seen_connections.add(memory_pair)  # type: ignore
            unique_connections.append(connection)

        logging.debug(
            "Processed %s connections of other types, resulting in %s unique connections.",
            len(filtered_connections),
            len(unique_connections),
        )
        return unique_connections

    @observe(name="process-memory-group-for-connecting")
    def _process_memory_group_for_connecting(
        self, memory_group: List[MemoryDeduplicationInputDLO], **kwargs
    ) -> List[MemoryConnectionDLO]:
        """
        Process a group of memories to identify connections using an LLM.

        Args:
            memory_group: List of MemoryDeduplicationInputDLO objects representing the memory group
            tenant: The tenant identifier
            **kwargs: Additional arguments to pass to the LLM

        Returns:
            List of MemoryConnectionDLO objects representing the identified connections
        """
        if not memory_group or len(memory_group) < 2:
            logging.warning("Not enough memories in group to process connections.")
            return []

        # Prepare the prompt for the LLM
        memory_connection_json_schema = MemoryConnectionDLO.json_array_schema()

        system_message = self.template_connector.render(
            memory_connection_json_schema=memory_connection_json_schema,
            connection_types=get_enum_values_with_descriptions(ConnectionType),
            **kwargs,
        )

        logging.debug(
            "System message for LLM connection analysis: \n%s", system_message
        )

        # Use type adapter for proper JSON serialization
        memory_input_json = MemoryDeduplicationInputDLO.json_array_type().dump_json(
            memory_group
        )

        messages = [
            Message(role="system", content=system_message),
            Message(role="user", content=str(memory_input_json)),
        ]

        logging.debug("Sending messages to LLM for connection analysis")

        # Call the LLM to identify connections between memories
        response = self.response_llm.chat(
            messages=messages,
            response_format=MemoryConnectionDLO.json_array_type().json_schema(),
            options={"temperature": 0.05},
        )

        # Process LLM response
        if not response or not response.message or not response.message.content:
            logging.warning("No valid response from LLM for memory connections.")
            return []

        logging.debug(
            "Received response from LLM for connection analysis: %s",
            response.message.content,
        )

        try:
            logging.debug("Parsing memory connections from LLM response.")

            # Parse the connections from the LLM response
            connection_dlos = MemoryConnectionDLO.json_array_type().validate_json(
                response.message.content
            )

            logging.debug(
                "Parsed %s memory connection DLOs from LLM response.",
                len(connection_dlos),
            )

            return connection_dlos
        except Exception as e:
            logging.error(
                "Error processing memory connections: %s. Response content: %s",
                e,
                response.message.content if response.message else "No content",
            )
            return []

    @observe(name="connect-memories")
    def _create_memory_connections(
        self, memories: List[Memory], **kwargs
    ) -> List[MemoryConnectionDLO]:
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
            return []

        # Prepare memory data for LLM processing
        memory_input_dlos = []
        valid_memories = []

        logging.debug("Converting memories to input DLOs for connection analysis.")

        for memory in memories:
            if not memory.id:
                logging.warning("Skipping memory without ID: %s", memory)
                continue

            valid_memories.append(memory)

            # Create the input DLO for this memory (simplified for connection identification)
            memory_input_dlo = MemoryDeduplicationInputDLO(
                id=memory.id,
                title=memory.title,
                content=memory.content,
                learnings=[],  # We don't need detailed learning info for connections
            )

            memory_input_dlos.append(memory_input_dlo)

        # If insufficient valid memories, return original list
        if len(memory_input_dlos) < 2:
            logging.warning(
                "Not enough valid memories with IDs for connection analysis."
            )
            return []

        logging.debug(
            "Converted %s valid memories to %s input DLOs for connection analysis.",
            len(valid_memories),
            len(memory_input_dlos),
        )

        memory_groups = greedy_cover_max_groups(
            memory_input_dlos, self.group_size, self.max_groups
        )

        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            kwargs["langfuse_parent_observation_id"] = (
                self.langfuse_client.get_current_observation_id()
            )

            futures = {
                executor.submit(
                    self._process_memory_group_for_connecting, group, **kwargs
                ): group
                for group in memory_groups
            }

            all_connections: list[MemoryConnectionDLO] = []

            for future in as_completed(futures):
                try:
                    connections = future.result()
                    logging.debug(
                        "Processed memory group with %s memories, resulting in %s connections.",
                        len(futures[future]),
                        len(connections),
                    )
                    if connections:
                        all_connections.extend(connections)
                except Exception as e:
                    print(f"Error processing memory group: {e}")

        logging.debug(
            "Processed all memory groups, resulting in %s total connections.",
            len(all_connections),
        )
        if not all_connections:
            logging.warning("No connections found between memories.")
            return []

        # Process the connections to handle duplicates and other types
        logging.debug("Processing connections to handle duplicates and other types.")
        duplicate_connections = self._process_connection_type_duplicate(all_connections)
        other_connections = self._process_other_connection_types(all_connections)
        all_connections = duplicate_connections + other_connections

        logging.debug(
            "Processed connections, resulting in %s connections.",
            len(all_connections),
        )

        if not all_connections:
            logging.warning("No valid connections found after processing.")
            return []

        return all_connections

    @observe(name="save-memory-connections")
    def _save_memory_connections(
        self, connection_dlos: List[MemoryConnectionDLO], tenant: str
    ) -> List[MemoryConnection]:
        try:
            logging.debug("Parsing memory connections from LLM response.")
            # Create memory connections from DLOs
            connections = []

            for connection_dlo in connection_dlos:
                if len(connection_dlo.memories) < 2:
                    logging.warning(
                        "Skipping connection DLO with less than 2 memories: %s",
                        connection_dlo,
                    )
                    continue

                try:
                    connection_type = ConnectionType(connection_dlo.connection_type)
                except ValueError:
                    connection_type = ConnectionType.RELATED

                connection = MemoryConnection(
                    connection_type=connection_type,
                    memories=connection_dlo.memories,
                    description=connection_dlo.description,
                    weight=connection_dlo.weight or 0.5,
                )

                logging.debug(
                    "Creating connection with type %s, memories %s, description '%s', weight %s",
                    connection.connection_type,
                    connection.memories,
                    connection.description,
                    connection.weight,
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

            # Update each memory with its connections
            for connection in connections:
                for memory_id in connection.memories:
                    if memory_id in self.memory_cache:
                        memory = self.memory_cache[memory_id]
                        if not memory.connections:
                            memory.connections = []
                        memory.connections.append(connection.id)  # type: ignore

            return connections

        except Exception as e:
            print(f"Error processing memory connections: {e}")
            return []
