"""
Weaviate client wrapper for AtlasML.

This module provides:
- A typed, singleton-backed `WeaviateClient` for connection management
- Schema bootstrap for core collections (Exercise, Competency, SemanticCluster)
- High-level CRUD/search helpers that return simple Python structures

Connection configuration is provided by `atlasml.config.WeaviateSettings`.
The client supports both local HTTP connections and remote HTTPS connections
with API key authentication. gRPC is used for optimal performance as required
by the Weaviate Python client v4.

Typical usage within request handlers:
    from atlasml.clients.weaviate import get_weaviate_client, CollectionNames

    client = get_weaviate_client()
    items = client.get_all_embeddings(CollectionNames.COMPETENCY.value)

All operations raise `WeaviateOperationError` on failure and avoid leaking
low-level exceptions to the API layer.
"""

import logging
from enum import Enum
from typing import Optional, Dict, List, Any

import weaviate
from weaviate.classes.query import Filter
from weaviate.classes.config import Property
from weaviate.collections.classes.config import DataType
from weaviate.exceptions import WeaviateConnectionError, WeaviateQueryError
from weaviate.classes.init import Auth

from atlasml.config import WeaviateSettings, get_settings


# If you define all the collections here all the collections will be created
# automatically when you run the project.
class CollectionNames(str, Enum):
    """Canonical collection names used by AtlasML in Weaviate."""
    EXERCISE = "Exercise"
    COMPETENCY = "Competency"
    SEMANTIC_CLUSTER = "SemanticCluster"


COLLECTION_SCHEMAS = {
    CollectionNames.EXERCISE.value: {
        "properties": [
            {
                "name": "exercise_id",
                "data_type": DataType.NUMBER,
                "indexFilterable": True,
                "indexNullState": True,
            },
            {"name": "description", "data_type": DataType.TEXT},
            {
                "name": "competency_ids",
                "data_type": DataType.NUMBER_ARRAY,
                "indexFilterable": True,
            },
            {"name": "course_id", "data_type": DataType.NUMBER, "indexFilterable": True},
        ]
    },
    CollectionNames.COMPETENCY.value: {
        "properties": [
            {
                "name": "competency_id",
                "data_type": DataType.NUMBER,
                "indexFilterable": True,
            },
            {"name": "title", "data_type": DataType.TEXT},
            {"name": "description", "data_type": DataType.TEXT},
            {"name": "cluster_id", "data_type": DataType.TEXT, "indexFilterable": True},
            {"name": "cluster_similarity_score", "data_type": DataType.NUMBER},
            {"name": "course_id", "data_type": DataType.NUMBER, "indexFilterable": True},
        ]
    },
    CollectionNames.SEMANTIC_CLUSTER.value: {
        "properties": [
            {"name": "cluster_id", "data_type": DataType.TEXT, "indexFilterable": True},
            {"name": "label_id", "data_type": DataType.TEXT, "indexFilterable": True},
            {"name": "course_id", "data_type": DataType.NUMBER, "indexFilterable": True},
        ]
    },
}


logger = logging.getLogger(__name__)


class WeaviateConnectionError(Exception):
    """Custom exception for Weaviate connection errors."""

    pass


class WeaviateOperationError(Exception):
    """Custom exception for Weaviate operation errors."""

    pass


class WeaviateClient:
    """High-level Weaviate client with schema initialization and helpers.

    The constructor establishes a connection and ensures required collections
    exist with the configured schema. Access the underlying SDK via
    `self.client` if you need advanced operations not covered here.
    """
    def __init__(self, weaviate_settings: WeaviateSettings = None):
        if weaviate_settings is None:
            weaviate_settings = get_settings().weaviate

        try:
            # Determine connection method based on scheme and API key
            if weaviate_settings.scheme == "https" or weaviate_settings.api_key:
                # Use custom connection for HTTPS or authenticated connections
                logger.info(
                    f"Connecting to Weaviate at {weaviate_settings.scheme}://{weaviate_settings.host}:{weaviate_settings.port} "
                    f"(gRPC port: {weaviate_settings.grpc_port}, authenticated: {bool(weaviate_settings.api_key)})"
                )

                # Prepare authentication if API key is provided
                auth_credentials = None
                if weaviate_settings.api_key:
                    auth_credentials = Auth.api_key(weaviate_settings.api_key)

                # For HTTPS connections, gRPC should also be secure
                grpc_secure = weaviate_settings.scheme == "https"

                self.client = weaviate.connect_to_custom(
                    http_host=weaviate_settings.host,
                    http_port=weaviate_settings.port,
                    http_secure=(weaviate_settings.scheme == "https"),
                    grpc_host=weaviate_settings.host,
                    grpc_port=weaviate_settings.grpc_port,
                    grpc_secure=grpc_secure,
                    auth_credentials=auth_credentials,
                )
            else:
                # Use local connection for HTTP without authentication
                logger.info(
                    f"Connecting to local Weaviate at {weaviate_settings.host}:{weaviate_settings.port} "
                    f"(gRPC port: {weaviate_settings.grpc_port})"
                )
                self.client = weaviate.connect_to_local(
                    host=weaviate_settings.host,
                    port=weaviate_settings.port,
                    grpc_port=weaviate_settings.grpc_port,
                )

            logger.info(
                f"✅ Connected to Weaviate at {weaviate_settings.scheme}://{weaviate_settings.host}:{weaviate_settings.port} "
                f"(gRPC: {weaviate_settings.grpc_port})"
            )
        except WeaviateConnectionError as e:
            logger.error(f"❌ Failed to connect to Weaviate: {e}")
            raise WeaviateConnectionError(f"Could not connect to Weaviate server: {e}")
        except Exception as e:
            logger.error(f"❌ Unexpected error connecting to Weaviate: {e}")
            raise WeaviateConnectionError(f"Unexpected connection error: {e}")

        try:
            self._ensure_collections_exist()
        except Exception as e:
            logger.error(f"❌ Failed to initialize collections: {e}")
            self.client.close()
            raise WeaviateOperationError(f"Failed to initialize collections: {e}")

    def _check_if_collection_exists(self, collection_name: str):
        """Check if a collection exists and create it if it doesn't."""
        if not self.client.collections.exists(collection_name):
            raise ValueError(f"Collection '{collection_name}' does not exist")

    def _ensure_collections_exist(self):
        """Ensure collections exist with a proper schema."""
        try:
            # Define schemas for each collection
            # After, schema updated automatically, and you can fetch the data from the collection with the new properties
            for collection_name, schema in COLLECTION_SCHEMAS.items():
                try:
                    if not self.client.collections.exists(collection_name):
                        self.client.collections.create(
                            name=collection_name,
                            vectorizer_config=weaviate.classes.config.Configure.Vectorizer.none(),
                            properties=schema["properties"],
                        )
                        logger.info(
                            f"✅ {collection_name} collection created with schema."
                        )
                    else:
                        collection = self.client.collections.get(collection_name)
                        existing_props = {
                            prop.name
                            for prop in collection.config.get(simple=False).properties
                        }

                        for prop in schema["properties"]:
                            if prop["name"] not in existing_props:
                                try:
                                    # Convert string data type to DataType enum
                                    data_type_str = prop["data_type"]
                                    if data_type_str == "text":
                                        data_type = DataType.TEXT
                                    elif data_type_str == "int":
                                        data_type = DataType.INT
                                    elif data_type_str == "text[]":
                                        data_type = DataType.TEXT_ARRAY
                                    elif data_type_str == "number":
                                        data_type = DataType.NUMBER
                                    else:
                                        data_type = (
                                            DataType.TEXT
                                        )  # Default to TEXT for unknown types

                                    collection.config.add_property(
                                        Property(
                                            name=prop["name"],
                                            data_type=data_type,
                                            index_searchable=prop.get(
                                                "indexFilterable", False
                                            ),
                                        )
                                    )
                                    logger.info(
                                        f"✅ Added property {prop['name']} to {collection_name}."
                                    )
                                except Exception as e:
                                    logger.error(
                                        f"❌ Failed to add property {prop['name']} to {collection_name}: {e}"
                                    )
                                    # Continue with other properties
                except Exception as e:
                    logger.error(
                        f"❌ Failed to create/update collection {collection_name}: {e}"
                    )
                    raise WeaviateOperationError(
                        f"Failed to initialize collection {collection_name}: {e}"
                    )

            logger.info("--- All collections initialized with schemas ---")
        except Exception as e:
            logger.error(f"❌ Failed to ensure collections exist: {e}")
            raise

    def is_alive(self):
        """Return True if the Weaviate service responds to liveness checks."""
        try:
            return self.client.is_live()
        except Exception as e:
            logger.error(f"❌ Weaviate connection failed: {e}")
            return False

    def close(self):
        """Close the underlying Weaviate client connection."""
        self.client.close()

    def add_embeddings(
        self,
        collection_name: str,
        embeddings: list[float],
        properties: dict | None = None,
    ) -> str:
        """
        Insert a vector and optional properties into a collection.

        Args:
            collection_name: Name of the collection to add embeddings to.
            embeddings: Vector representation of the data.
            properties: Additional properties to store with the embedding (optional).

        Returns:
            UUID string of the inserted object.

        Raises:
            WeaviateOperationError: If the operation fails.
            ValueError: If collection doesn't exist or parameters are invalid.
        """
        try:
            logger.info(
                f"--- ADDING EMBEDDING TO WEAVIATE COLLECTION '{collection_name}' ---"
            )

            if not embeddings or not isinstance(embeddings, list):
                raise ValueError("Embeddings must be a non-empty list of floats")

            self._check_if_collection_exists(collection_name)
            collection = self.client.collections.get(collection_name)

            data_properties = {}
            if properties and isinstance(properties, dict):
                data_properties.update(properties)

            uuid = collection.data.insert(properties=data_properties, vector=embeddings)

            logger.info("--- EMBEDDING ADDED TO WEAVIATE ---")
            logger.info(f"UUID: {uuid}")
            return uuid

        except ValueError:
            # Re-raise validation errors
            raise
        except WeaviateQueryError as e:
            logger.error(f"❌ Weaviate query error adding embedding: {e}")
            raise WeaviateOperationError(
                f"Failed to add embedding to {collection_name}: {e}"
            )
        except Exception as e:
            logger.error(f"❌ Unexpected error adding embedding: {e}")
            raise WeaviateOperationError(f"Unexpected error adding embedding: {e}")

    def get_embeddings(self, collection_name: str, id: str):
        """Get vector and metadata for an object by UUID from a collection."""
        logger.info(
            f"--- GETTING EMBEDDINGS FROM WEAVIATE COLLECTION '{collection_name}' ---"
        )
        self._check_if_collection_exists(collection_name)

        embedding = self.get_embeddings_rest(collection_name, id)

        logger.info("--- EMBEDDINGS RETRIEVED FROM WEAVIATE ---")

        return embedding

    def get_all_embeddings(
        self, collection_name: str = CollectionNames.COMPETENCY.value
    ) -> List[Dict[str, Any]]:
        """
        Fetch all objects and their vectors from a collection.

        Args:
            collection_name: Name of the collection to fetch embeddings from.
                Defaults to 'Competency'.

        Returns:
            List of dictionaries containing id, text, and vector for each object.

        Raises:
            WeaviateOperationError: If the operation fails.
            ValueError: If collection doesn't exist.
        """
        try:
            self._check_if_collection_exists(collection_name)

            results = []
            collection = self.client.collections.get(collection_name)
            response = collection.iterator(
                include_vector=True,
            )

            for obj in response:
                results.append(
                    {
                        "id": obj.uuid,
                        "title": obj.properties.get("title"),
                        "description": obj.properties.get("description"),
                        "vector": obj.vector,
                        "properties": obj.properties,
                    }
                )

            logger.info(f"Retrieved {len(results)} embeddings from {collection_name}")
            return results

        except ValueError:
            # Re-raise validation errors
            raise
        except WeaviateQueryError as e:
            logger.error(f"❌ Weaviate query error getting embeddings: {e}")
            raise WeaviateOperationError(
                f"Failed to get embeddings from {collection_name}: {e}"
            )
        except Exception as e:
            logger.error(f"❌ Unexpected error getting embeddings: {e}")
            raise WeaviateOperationError(f"Unexpected error getting embeddings: {e}")

    def get_embeddings_by_property(
        self, collection_name: str, property_name: str, property_value: int | str
    ) -> List[Dict[str, Any]]:
        """
        Fetch objects and vectors filtered by a property equality filter.

        Args:
            collection_name: Name of the collection to fetch embeddings from.
            property_name: The property name to filter by (e.g., 'name', 'course_id').
            property_value: The value of the property to match.

        Returns:
            List of dictionaries containing id, properties, and vector for each matching
            object.

        Raises:
            WeaviateOperationError: If the operation fails.
            ValueError: If collection doesn't exist or parameters are invalid.
        """
        try:
            logger.info(
                f"--- GETTING EMBEDDINGS BY PROPERTY FROM WEAVIATE "
                f"COLLECTION '{collection_name}' ---"
            )

            if not property_name or not property_value:
                raise ValueError("Property name and value must be provided")

            self._check_if_collection_exists(collection_name)

            collection = self.client.collections.get(collection_name)

            response = collection.query.fetch_objects(
                filters=Filter.by_property(property_name).equal(property_value),
                include_vector=True,
            )

            results = []
            for obj in response.objects:
                results.append(
                    {"id": obj.uuid, "properties": obj.properties, "vector": obj.vector}
                )

            logger.info(
                f"--- FOUND {len(results)} EMBEDDINGS MATCHING "
                f"{property_name}={property_value} ---"
            )
            return results

        except ValueError:
            # Re-raise validation errors
            raise
        except WeaviateQueryError as e:
            logger.error(f"❌ Weaviate query error getting embeddings by property: {e}")
            raise WeaviateOperationError(f"Failed to get embeddings by property: {e}")
        except Exception as e:
            logger.error(f"❌ Unexpected error getting embeddings by property: {e}")
            raise WeaviateOperationError(
                f"Unexpected error getting embeddings by property: {e}"
            )

    def search_by_multiple_properties(
        self, collection_name: str, property_filters: dict
    ):
        """
        Search for objects that match multiple property equality filters.

        Args:
            collection_name: Name of the collection to search in.
            property_filters: Dictionary of property names and values to filter by.
                Example: {"category": "math", "difficulty": 3}

        Returns:
            List of dictionaries containing id, properties,
            and vector for each matching object.
        """
        logger.info(
            f"--- SEARCHING BY MULTIPLE PROPERTIES IN COLLECTION "
            f"'{collection_name}' --- {property_filters}"
        )
        self._check_if_collection_exists(collection_name)

        collection = self.client.collections.get(collection_name)

        # Build filters for each property
        filters = []
        for prop_name, prop_value in property_filters.items():
            if isinstance(prop_value, str):
                filter_obj = {
                    "path": [prop_name],
                    "operator": "Equal",
                    "valueText": prop_value,
                }
            elif isinstance(prop_value, int):
                filter_obj = {
                    "path": [prop_name],
                    "operator": "Equal",
                    "valueNumber": prop_value,
                }
            elif isinstance(prop_value, list):
                # For array properties like tags
                filter_obj = {
                    "path": [prop_name],
                    "operator": "ContainsAny",
                    "valueTextArray": (
                        prop_value
                        if all(isinstance(v, str) for v in prop_value)
                        else None
                    ),
                }
            else:
                logger.warning(
                    f"Unsupported property type for {prop_name}: {type(prop_value)}"
                )
                continue

            filters.append(filter_obj)

        # Combine filters with AND operator
        if len(filters) > 1:
            combined_filter = {"operator": "And", "operands": filters}
        elif len(filters) == 1:
            combined_filter = filters[0]
        else:
            logger.warning("No valid filters provided")
            return []

        response = collection.query.fetch_objects(
            filters=combined_filter, include_vector=True
        )

        results = []
        for obj in response.objects:
            results.append(
                {"id": obj.uuid, "properties": obj.properties, "vector": obj.vector}
            )

        logger.info(
            f"--- FOUND {len(results)} EMBEDDINGS MATCHING MULTIPLE PROPERTIES ---"
        )
        return results

    def _check_if_collection_exists(self, collection_name: str):
        """Raise ValueError if the collection does not exist."""
        if not self.client.collections.exists(collection_name):
            raise ValueError(f"Collection '{collection_name}' does not exist")

    def delete_all_data_from_collection(self, collection_name: str):
        """Delete and recreate a collection, effectively wiping all data."""

        self._check_if_collection_exists(collection_name)
        logger.info(f"{collection_name} ---> ALL DATA DELETED")

        self.client.collections.delete(collection_name)

        self.recreate_collection(collection_name)

    def recreate_collection(self, collection_name: str):
        """Create a collection from its schema after deletion."""
        logger.info(f"--- RECREATING COLLECTION '{collection_name}' ---")
        if collection_name not in COLLECTION_SCHEMAS:
            raise ValueError(f"No schema defined for collection '{collection_name}'")

        schema = COLLECTION_SCHEMAS[collection_name]

        # Create the collection with the schema
        self.client.collections.create(
            name=collection_name,
            vectorizer_config=weaviate.classes.config.Configure.Vectorizer.none(),
            properties=schema["properties"],
        )
        logger.info(f"{collection_name} ---> RECREATED")

    def update_property_by_id(
        self,
        collection_name: str,
        id: str,
        properties: dict,
        vector: Optional[List[float]] = None,
    ) -> bool:
        """Update properties and optionally the vector for an object by UUID.

        Args:
            collection_name: Target collection name
            id: Object UUID to update
            properties: Property dictionary to merge/update
            vector: Optional replacement vector

        Returns:
            True if the update call succeeds

        Raises:
            WeaviateOperationError: On query failure
            ValueError: If input is invalid or collection missing
        """
        try:
            if not id or not properties:
                raise ValueError("ID and properties must be provided")

            self._check_if_collection_exists(collection_name)
            collection = self.client.collections.get(collection_name)
            collection.data.update(
                id,
                properties={
                    **properties,
                },
                vector=vector,
            )
            logger.info(f"--- PROPERTY UPDATED IN {collection_name} ---")
            return True

        except ValueError:
            # Re-raise validation errors
            raise
        except WeaviateQueryError as e:
            logger.error(f"❌ Weaviate query error updating property: {e}")
            raise WeaviateOperationError(
                f"Failed to update property in {collection_name}: {e}"
            )
        except Exception as e:
            logger.error(f"❌ Unexpected error updating property: {e}")
            raise WeaviateOperationError(f"Unexpected error updating property: {e}")

    def delete_by_property(
        self,
        collection_name: str,
        property_name: str,
        property_value: str | int,
    ) -> int:
        """Delete objects where property_name equals property_value.

        Returns the number of successfully deleted objects.
        """
        try:
            logger.info(
                f"--- DELETING BY PROPERTY FROM WEAVIATE "
                f"COLLECTION '{collection_name}' ---"
            )

            if not property_name or not property_value:
                raise ValueError("Property name and value must be provided")

            self._check_if_collection_exists(collection_name)

            collection = self.client.collections.get(collection_name)

            result = collection.data.delete_many(
                where=Filter.by_property(property_name).equal(property_value)
            )

            deleted_count = result.successful

            logger.info(
                f"--- DELETED {deleted_count} OBJECTS MATCHING "
                f"{property_name}={property_value} ---"
            )
            return deleted_count

        except ValueError:
            # Re-raise validation errors
            raise
        except WeaviateQueryError as e:
            logger.error(f"❌ Weaviate query error deleting by property: {e}")
            raise WeaviateOperationError(f"Failed to delete by property: {e}")
        except Exception as e:
            logger.error(f"❌ Unexpected error deleting by property: {e}")
            raise WeaviateOperationError(
                f"Unexpected error deleting by property: {e}"
            )


class WeaviateClientSingleton:
    _instance = None
    _settings = None

    @classmethod
    def get_instance(cls, weaviate_settings: WeaviateSettings = None) -> WeaviateClient:
        """Get a cached `WeaviateClient` instance keyed by settings."""
        if weaviate_settings is None:
            weaviate_settings = get_settings().weaviate

        # Recreate instance if settings changed
        if cls._instance is None or cls._settings != weaviate_settings:
            if cls._instance is not None:
                cls._instance.close()
            cls._instance = WeaviateClient(weaviate_settings)
            cls._settings = weaviate_settings
        return cls._instance


def get_weaviate_settings() -> WeaviateSettings:
    """Return resolved Weaviate settings from the global config."""
    return get_settings().weaviate


def get_weaviate_client(weaviate_settings: WeaviateSettings = None) -> WeaviateClient:
    """Convenience accessor for the shared `WeaviateClient` instance."""
    return WeaviateClientSingleton.get_instance(weaviate_settings)


def create_weaviate_client(
    weaviate_settings: WeaviateSettings = None,
) -> WeaviateClient:
    """Create or fetch a `WeaviateClient` using provided or global settings."""
    if weaviate_settings is None:
        weaviate_settings = get_settings().weaviate
    return get_weaviate_client(weaviate_settings)
