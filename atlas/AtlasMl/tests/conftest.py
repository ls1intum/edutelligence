import os
from pathlib import Path

# Set environment variables before any other imports
os.environ["ATLAS_API_KEYS"] = "secret-token,test-token"
os.environ["WEAVIATE_HOST"] = "localhost"
os.environ["WEAVIATE_PORT"] = "8080"
os.environ["TESTING"] = "true"

import pytest
from unittest.mock import patch
import logging
import asyncio

logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def test_env():
    """Setup test environment variables and configuration"""
    # Set test environment variables
    test_vars = {
        "ATLAS_API_KEYS": "secret-token, test-token",
        "WEAVIATE_HOST": "localhost",
        "WEAVIATE_PORT": "8080",
        "TESTING": "true",
    }

    # Store original values
    original_values = {}
    for key, value in test_vars.items():
        original_values[key] = os.environ.get(key)
        os.environ[key] = value

    yield

    # Restore original values
    for key, original_value in original_values.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value


@pytest.fixture(autouse=True)
def mock_generate_embeddings_openai():
    with (
        patch(
            "atlasml.ml.embeddings.generate_embeddings_openai",
            return_value=[0.1, 0.2, 0.3],
        ),
        patch("atlasml.ml.embeddings.AzureOpenAI") as mock_mainembedding_azure_openai,
        patch("openai.AzureOpenAI") as mock_openai_azure_openai,
    ):
        # Mock the embeddings.create method to return a fake embedding
        mock_instance = mock_mainembedding_azure_openai.return_value
        mock_instance.embeddings.create.return_value = type(
            "obj",
            (object,),
            {"data": [type("obj", (object,), {"embedding": [0.1, 0.2, 0.3]})()]},
        )()
        mock_instance2 = mock_openai_azure_openai.return_value
        mock_instance2.embeddings.create.return_value = type(
            "obj",
            (object,),
            {"data": [type("obj", (object,), {"embedding": [0.1, 0.2, 0.3]})()]},
        )()
        yield


# Simple mock objects for Weaviate
class MockWeaviateObject:
    """Mock object representing a Weaviate response object."""

    def __init__(self, uuid: str, properties: dict, vector: list = None):
        self.uuid = uuid
        self.properties = properties
        self.vector = vector or [0.1, 0.2, 0.3]


class MockWeaviateQueryResult:
    """Mock query result."""

    def __init__(self, objects=None):
        self.objects = objects or []


class MockWeaviateQuery:
    """Mock collection query operations."""

    def __init__(self, collection_name):
        self.collection_name = collection_name
        self._should_fail_fetch = False

    def fetch_objects(self, filters=None, include_vector=False):
        """Mock fetch objects operation."""
        if self._should_fail_fetch:
            raise Exception("Mock fetch error")

        # Return schema-appropriate test data based on collection name
        objects = []
        if self.collection_name == "Exercise":
            objects = [
                MockWeaviateObject(
                    uuid="exercise-uuid-1",
                    properties={
                        "exercise_id": 1,
                        "title": "Linear Equations Exercise",
                        "description": "Solve linear equations",
                        "competency_ids": ["1", "2"],
                        "course_id": 1,
                    },
                    vector=[0.1, 0.2, 0.3],
                )
            ]
        elif self.collection_name == "Competency":
            objects = [
                MockWeaviateObject(
                    uuid="competency-uuid-1",
                    properties={
                        "competency_id": 1,
                        "title": "Algebra",
                        "description": "Basic algebra concepts",
                        "cluster_id": "1",
                        "cluster_similarity_score": 0.85,
                        "course_id": 1,
                    },
                    vector=[0.1, 0.2, 0.3],
                )
            ]
        elif self.collection_name == "SEMANTIC_CLUSTER":
            objects = [
                MockWeaviateObject(
                    uuid="cluster-uuid-1",
                    properties={
                        "cluster_id": "1",
                        "label_id": "algebra-basics",
                        "course_id": 1,
                    },
                    vector=[0.1, 0.2, 0.3],
                )
            ]

        return MockWeaviateQueryResult(objects)

    def set_fail_fetch(self, should_fail: bool):
        """Set whether fetch operations should fail."""
        self._should_fail_fetch = should_fail


class MockDeleteResult:
    """Mock delete operation result."""
    
    def __init__(self, successful_count: int):
        self.successful = successful_count


class MockWeaviateData:
    """Mock collection data operations."""

    def __init__(self):
        self._should_fail_insert = False
        self._should_fail_update = False
        self._should_fail_delete = False

    def insert(self, properties=None, vector=None):
        """Mock insert operation."""
        if self._should_fail_insert:
            raise Exception("Mock insert error")
        return "test-uuid"

    def update(self, uuid, properties=None, vector=None):
        """Mock update operation."""
        if self._should_fail_update:
            raise Exception("Mock update error")
        return True

    def delete_many(self, where=None):
        """Mock delete_many operation."""
        if self._should_fail_delete:
            raise Exception("Mock delete error")
        # Return mock result with successful count
        return MockDeleteResult(2)

    def set_fail_insert(self, should_fail: bool):
        """Set whether insert operations should fail."""
        self._should_fail_insert = should_fail

    def set_fail_update(self, should_fail: bool):
        """Set whether update operations should fail."""
        self._should_fail_update = should_fail

    def set_fail_delete(self, should_fail: bool):
        """Set whether delete operations should fail."""
        self._should_fail_delete = should_fail


class MockWeaviateConfig:
    """Mock collection config operations."""

    def add_property(self, property_obj):
        """Mock add property operation."""
        return True

    def get(self, simple=True):
        """Mock get config operation."""

        class MockConfigResult:
            def __init__(self):
                self.properties = []

        return MockConfigResult()


class MockWeaviateCollection:
    """Mock Weaviate collection."""

    def __init__(self, name: str):
        self.name = name
        self.data = MockWeaviateData()
        self.query = MockWeaviateQuery(name)
        self.config = MockWeaviateConfig()
        self._dynamic_objects = []  # Track dynamically added objects

    def iterator(self, include_vector=False):
        """Mock iterator method that returns schema-appropriate data."""
        if self.name == "Exercise":
            return [
                MockWeaviateObject(
                    uuid="exercise-uuid-1",
                    properties={
                        "exercise_id": 1,
                        "title": "Linear Equations Exercise",
                        "description": "Solve linear equations",
                        "competency_ids": ["1", "2"],
                        "course_id": 1,
                    },
                    vector=[0.1, 0.2, 0.3],
                ),
                MockWeaviateObject(
                    uuid="exercise-uuid-2",
                    properties={
                        "exercise_id": 2,
                        "title": "Calculus Derivatives Exercise",
                        "description": "Calculus derivatives",
                        "competency_ids": ["3"],
                        "course_id": 1,
                    },
                    vector=[0.4, 0.5, 0.6],
                ),
            ]
        elif self.name == "Competency":
            return [
                MockWeaviateObject(
                    uuid="competency-uuid-1",
                    properties={
                        "competency_id": 1,
                        "title": "Algebra",
                        "description": "Basic algebra concepts",
                        "cluster_id": "1",
                        "cluster_similarity_score": 0.85,
                        "course_id": 1,
                    },
                    vector=[0.1, 0.2, 0.3],
                ),
                MockWeaviateObject(
                    uuid="competency-uuid-2",
                    properties={
                        "competency_id": 2,
                        "title": "Calculus",
                        "description": "Basic calculus concepts",
                        "cluster_id": "2",
                        "cluster_similarity_score": 0.92,
                        "course_id": 1,
                    },
                    vector=[0.4, 0.5, 0.6],
                ),
            ]
        elif self.name == "SEMANTIC_CLUSTER":
            static_objects = [
                MockWeaviateObject(
                    uuid="cluster-uuid-1",
                    properties={
                        "cluster_id": "1",
                        "label_id": "algebra-basics",
                        "course_id": 1,
                    },
                    vector=[0.1, 0.2, 0.3],
                ),
                MockWeaviateObject(
                    uuid="cluster-uuid-2",
                    properties={
                        "cluster_id": "2",
                        "label_id": "calculus-basics",
                        "course_id": 1,
                    },
                    vector=[0.4, 0.5, 0.6],
                ),
            ]
            # Return dynamic objects if available, otherwise return static objects
            return self._dynamic_objects if self._dynamic_objects else static_objects
        return []

    def add_dynamic_object(self, obj):
        """Add a dynamic object to this collection."""
        self._dynamic_objects.append(obj)

    def clear_dynamic_objects(self):
        """Clear all dynamic objects."""
        self._dynamic_objects = []


class MockWeaviateCollections:
    """Mock Weaviate collections manager."""

    def __init__(self):
        self._existing_collections = {"Exercise", "Competency", "SEMANTIC_CLUSTER"}
        self._collection_instances = {}

    def get(self, name: str):
        """Get a collection by name."""
        if name not in self._collection_instances:
            self._collection_instances[name] = MockWeaviateCollection(name)
        return self._collection_instances[name]

    def exists(self, name: str) -> bool:
        """Check if collection exists."""
        return name in self._existing_collections

    def create(self, name: str, vectorizer_config=None, properties=None):
        """Create a new collection."""
        self._existing_collections.add(name)
        collection = MockWeaviateCollection(name)
        self._collection_instances[name] = collection
        return collection

    def delete(self, name: str):
        """Delete a collection."""
        self._existing_collections.discard(name)
        if name in self._collection_instances:
            del self._collection_instances[name]


class MockWeaviateClient:
    """Simple mock Weaviate client."""

    def __init__(self):
        self.collections = MockWeaviateCollections()
        self._is_live = True
        self._closed = False
        self._should_fail_is_live = False

    def is_live(self) -> bool:
        """Mock is_live check."""
        if self._should_fail_is_live:
            raise Exception("Mock connection error")
        return self._is_live and not self._closed

    def close(self):
        """Mock close operation."""
        self._closed = True

    def set_fail_is_live(self, should_fail: bool):
        """Set whether is_live should fail."""
        self._should_fail_is_live = should_fail

    def set_alive_status(self, status: bool):
        """Set the alive status for testing."""
        self._is_live = status

    def get_all_embeddings(self, collection_name: str):
        """Mock get_all_embeddings method to match WeaviateClient interface."""
        collection = self.collections.get(collection_name)
        if not collection:
            return []

        results = []
        for obj in collection.iterator():
            # Convert MockWeaviateObject to the expected format
            results.append(
                {
                    "id": obj.uuid,
                    "vector": {
                        "default": obj.vector
                    },  # Wrap vector in dict with "default" key
                    "properties": obj.properties,
                }
            )
        return results

    def add_embeddings(self, collection_name: str, vector, properties):
        """Mock add_embeddings method."""
        collection = self.collections.get(collection_name)
        if collection:
            # Create a new object and add it to the collection's dynamic objects
            uuid = f"dynamic-{collection_name}-{len(collection._dynamic_objects)}"
            obj = MockWeaviateObject(uuid=uuid, properties=properties, vector=vector)
            collection.add_dynamic_object(obj)
            return uuid
        return "mock-uuid"

    def get_embeddings_by_property(
        self, collection_name: str, property_name: str, property_value: str
    ):
        """Mock get_embeddings_by_property method."""
        collection = self.collections.get(collection_name)
        if not collection:
            return []

        results = []
        for obj in collection.iterator():
            if obj.properties.get(property_name) == property_value:
                results.append(
                    {
                        "id": obj.uuid,
                        "vector": {"default": obj.vector},
                        "properties": obj.properties,
                    }
                )
        return results

    def update_property_by_id(
        self, collection_name: str, obj_id: str, properties: dict, vector=None
    ):
        """Mock update_property_by_id method."""
        collection = self.collections.get(collection_name)
        if collection:
            collection.data.update(obj_id, properties=properties, vector=vector)
        return True

    def delete_all_data_from_collection(self, collection_name: str):
        """Mock delete_all_data_from_collection method."""
        collection = self.collections.get(collection_name)
        if collection:
            # Clear the collection data
            collection._collection_instances = {}

    def _ensure_collections_exist(self):
        """Mock _ensure_collections_exist method."""
        # Do nothing - collections are already set up in MockWeaviateCollections
        pass

    def delete_by_property(self, collection_name: str, property_name: str, property_value):
        """Mock delete_by_property method."""
        collection = self.collections.get(collection_name)
        if collection:
            # Clear dynamic objects that match the property
            collection.clear_dynamic_objects()
            return {"deleted_count": 1}
        return {"deleted_count": 0}


@pytest.fixture
def mock_weaviate_client():
    """Fixture providing a mock Weaviate client with dependency injection support."""
    mock_client = MockWeaviateClient()

    # Patch both weaviate.connect_to_local and weaviate.connect_to_custom functions
    with patch("weaviate.connect_to_local", return_value=mock_client):
        with patch("weaviate.connect_to_custom", return_value=mock_client):
            # Also patch the singleton to ensure fresh instances in tests
            with patch("atlasml.clients.weaviate.WeaviateClientSingleton._instance", None):
                # Patch get_weaviate_client to return our mock
                with patch(
                    "atlasml.ml.pipeline_workflows.get_weaviate_client",
                    return_value=mock_client,
                ):
                    yield mock_client


@pytest.fixture
def weaviate_test_data(mock_weaviate_client):
    """Fixture that sets up test data in mock Weaviate collections."""
    from atlasml.clients.weaviate import CollectionNames

    # Add test data to competency collection
    competency_collection = mock_weaviate_client.collections.get(
        CollectionNames.COMPETENCY.value
    )
    competency_collection.add_object(
        MockWeaviateObject(
            uuid="comp-1",
            properties={
                "competency_id": 1,
                "title": "Algebra",
                "description": "Basic algebra concepts",
                "course_id": 1,
                "cluster_id": "cluster-1",
            },
        )
    )
    competency_collection.add_object(
        MockWeaviateObject(
            uuid="comp-2",
            properties={
                "competency_id": 2,
                "title": "Calculus",
                "description": "Basic calculus concepts",
                "course_id": 1,
                "cluster_id": "cluster-2",
            },
        )
    )
    # Add test data to cluster collection
    cluster_collection = mock_weaviate_client.collections.get(
        CollectionNames.SEMANTIC_CLUSTER.value
    )
    cluster_collection.add_object(
        MockWeaviateObject(
            uuid="cluster-1",
            properties={
                "cluster_id": "cluster-1",
                "course_id": 1,
                "label_id": "cluster-1",
            },
            vector=[0.1, 0.2, 0.3],
        )
    )
    cluster_collection.add_object(
        MockWeaviateObject(
            uuid="cluster-2",
            properties={
                "cluster_id": "cluster-2",
                "course_id": 1,
                "label_id": "cluster-2",
            },
            vector=[0.2, 0.2, 0.2],
        )
    )

    # Add test data to exercise collection
    exercise_collection = mock_weaviate_client.collections.get(
        CollectionNames.EXERCISE.value
    )
    exercise_collection.add_object(
        MockWeaviateObject(
            uuid="ex-1",
            properties={
                "exercise_id": 1,
                "title": "Linear Equations Exercise",
                "description": "Solve linear equations",
                "course_id": 1,
            },
        )
    )

    yield mock_weaviate_client


@pytest.fixture
def mock_weaviate_settings():
    """Fixture providing mock Weaviate settings."""
    from atlasml.config import WeaviateSettings

    return WeaviateSettings(
        host="localhost",
        port=8080,
        api_key=None,
        scheme="http"
    )
