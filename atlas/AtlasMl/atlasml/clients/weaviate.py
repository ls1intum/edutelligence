import logging
from enum import Enum

import weaviate
from weaviate.classes.query import Filter
from weaviate.classes.config import Property
from weaviate.collections.classes.config import DataType

from atlasml.config import settings


# If you define all the collections here all the collections will be created
# automatically when you run the project.
class CollectionNames(str, Enum):
    TEXT = "Text"
    COMPETENCY = "Competency"
    CLUSTERCENTER = "ClusterCenter"


logger = logging.getLogger(__name__)


class WeaviateClient:
    def __init__(
        self,
        host: str = settings.weaviate.host,
        port: int = settings.weaviate.port,
        grpc_port: int = settings.weaviate.grpc_port,
    ):
        self.client = weaviate.connect_to_local(
            host=host,
            port=port,
            grpc_port=grpc_port,
        )

        self._ensure_collections_exist()

    def _check_if_collection_exists(self, collection_name: str):
        """Check if a collection exists and create it if it doesn't."""
        if not self.client.collections.exists(collection_name):
            raise ValueError(f"Collection '{collection_name}' does not exist")

    def _ensure_collections_exist(self):
        """Ensure collections exist with a proper schema."""
        # Define schemas for each collection
        # After, schema updated automatically, and you can fetch the data from the collection with the new properties
        collection_schemas = {
            CollectionNames.TEXT.value: {
                "properties": [
                    {"name": "text_id", "data_type": DataType.TEXT, "indexFilterable": True, "indexNullState": True},
                    {"name": "text", "data_type": DataType.TEXT},
                    {"name": "competency_ids", "data_type": DataType.TEXT_ARRAY, "indexFilterable": True},
                ]
            },
            CollectionNames.COMPETENCY.value: {
                "properties": [
                    {"name": "competency_id", "data_type": DataType.TEXT, "indexFilterable": True},
                    {"name": "name", "data_type":  DataType.TEXT},
                    {"name": "text", "data_type":  DataType.TEXT},
                    {"name": "cluster_id", "data_type": DataType.TEXT, "indexFilterable": True},
                ]
            },
            CollectionNames.CLUSTERCENTER.value: {
                "properties": [
                    {"name": "cluster_id", "data_type":  DataType.TEXT, "indexFilterable": True}
                ]
            },
        }

        for collection_name, schema in collection_schemas.items():
            if not self.client.collections.exists(collection_name):
                self.client.collections.create(
                    name=collection_name,
                    vectorizer_config=weaviate.classes.config.Configure.Vectorizer.none(),
                    properties=schema["properties"],
                )
                logger.info(f"✅ {collection_name} collection created with schema.")
            else:
                collection = self.client.collections.get(collection_name)
                existing_props = {prop.name for prop in collection.config.get(simple=False).properties}

                for prop in schema["properties"]:
                    if prop["name"] not in existing_props:
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
                            data_type = DataType.TEXT  # Default to TEXT for unknown types

                        collection.config.add_property(
                            Property(
                                name=prop["name"],
                                data_type=data_type,
                                index_searchable=prop.get("indexFilterable", False),
                            )
                        )
                        logger.info(
                            f"✅ Added property {prop['name']} to {collection_name}."
                        )

        logger.info("--- All collections initialized with schemas ---")

    def is_alive(self):
        """Check if the Weaviate client is alive."""
        try:
            return self.client.is_live()
        except Exception as e:
            logger.error(f"❌ Weaviate connection failed: {e}")
            return False

    def close(self):
        """Close the Weaviate client."""
        self.client.close()

    def add_embeddings(
        self,
        collection_name: str,
        embeddings: list[float],
        properties: dict | None = None,
    ):
        """
        Add an embedding with a custom ID, description, 
        and additional properties to the specified collection.

        Args:
            collection_name: Name of the collection to add embeddings to.
            id: Unique identifier for the embedding.
            description: Text description associated with the embedding.
            embeddings: Vector representation of the data.
            properties: Additional properties to store with the embedding (optional).

        Returns:
            UUID of the inserted object.
        """
        logger.info(
            f"--- ADDING EMBEDDING TO WEAVIATE COLLECTION '{collection_name}' ---"
        )
        self._check_if_collection_exists(collection_name)
        collection = self.client.collections.get(collection_name)

        data_properties = {}

        if properties and isinstance(properties, dict):
            data_properties.update(properties)

        uuid = collection.data.insert(properties=data_properties, vector=embeddings)

        logger.info("--- EMBEDDING ADDED TO WEAVIATE ---")
        logger.info(f"UUID: {uuid}")
        return uuid

    def get_embeddings(self, collection_name: str, id: str):
        """Get embeddings for a given ID from the specified collection."""
        logger.info(
            f"--- GETTING EMBEDDINGS FROM WEAVIATE COLLECTION '{collection_name}' ---"
        )
        self._check_if_collection_exists(collection_name)

        embedding = self.get_embeddings_rest(collection_name, id)

        logger.info("--- EMBEDDINGS RETRIEVED FROM WEAVIATE ---")

        return embedding

    def get_all_embeddings(
        self, collection_name: str = CollectionNames.COMPETENCY.value
    ):
        """
        Fetch all objects and their vectors from the specified collection using REST

        Args:
            collection_name: Name of the collection to fetch embeddings from. 
                Defaults to 'Competency'.

        Returns:
            List of dictionaries containing id, text, and vector for each object.
        """
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
                    "text": obj.properties.get("text"),
                    "vector": obj.vector,
                    "properties": obj.properties,
                }
            )

        return results

    def get_embeddings_by_property(
        self, collection_name: str, property_name: str, property_value: str
    ):
        """
        Fetch objects and their vectors from the collection that match a property value.

        Args:
            collection_name: Name of the collection to fetch embeddings from.
            property_name: The property name to filter by (e.g., 'name', 'course_id').
            property_value: The value of the property to match.

        Returns:
            List of dictionaries containing id, properties, and vector for each matching
            object.
        """
        logger.info(
            f"--- GETTING EMBEDDINGS BY PROPERTY FROM WEAVIATE "
            f"COLLECTION '{collection_name}' ---"
        )
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

    def search_by_multiple_properties(
        self, collection_name: str, property_filters: dict
    ):
        """
        Search for objects that match multiple property filters.

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
        """Check if a collection exists and create it if it doesn't."""
        if not self.client.collections.exists(collection_name):
            raise ValueError(f"Collection '{collection_name}' does not exist")

    def delete_all_data_from_collection(self, collection_name: str):
        """Delete all data from a collection."""

        self._check_if_collection_exists(collection_name)

        collection = self.client.collections.get(collection_name)
        self.client.collections.delete(collection_name)
        # collection.data.delete_many()
        logger.info(f"--- ALL DATA DELETED FROM {collection_name} ---")

    def delete_data_by_id(self, collection_name: str, id: str):
        """Delete data from a collection by ID."""
        self._check_if_collection_exists(collection_name)

        collection = self.client.collections.get(collection_name)
        collection.data.delete(id)
        logger.info(f"--- DATA DELETED FROM {collection_name} ---")

    def update_property_by_id(self, collection_name: str, id: str, properties: dict):
        """Update a property by ID."""
        self._check_if_collection_exists(collection_name)
        collection = self.client.collections.get(collection_name)
        collection.data.update(
            id,
            properties={
                **properties,
            },
        )
        logger.info(f"--- PROPERTY UPDATED IN {collection_name} ---")

class WeaviateClientSingleton:
    _instance = None

    @classmethod
    def get_instance(cls) -> WeaviateClient:
        """Get a Weaviate client instance using singleton pattern."""
        if cls._instance is None:
            cls._instance = WeaviateClient()
        return cls._instance


def get_weaviate_client() -> WeaviateClient:
    """Get a Weaviate client instance using singleton pattern."""
    return WeaviateClientSingleton.get_instance()
