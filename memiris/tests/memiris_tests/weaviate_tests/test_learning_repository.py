import uuid

import pytest
from memiris_tests.test_utils import compare_vectors, mock_vector
from memiris_tests.weaviate_tests.test_setup import WeaviateTest
from weaviate.client import WeaviateClient

from memiris.domain.learning import Learning
from memiris.repository.weaviate.weaviate_learning_repository import (
    WeaviateLearningRepository,
)


class TestWeaviateLearningRepository(WeaviateTest):
    """
    TestWeaviateLearningRepository is a test class for WeaviateLearningRepository.
    It uses testcontainers to run a Weaviate instance in a Docker container.
    """

    @pytest.fixture
    def learning_repository(self, weaviate_client):
        return WeaviateLearningRepository(weaviate_client)

    def _create_learning(self, learning_repository):
        vec = mock_vector()
        return learning_repository.save(
            "test",
            Learning(
                title="Test Title",
                content="Test Content",
                reference="Test Reference",
                vectors={"vector_0": vec},
            ),
        )

    def test_create(self, learning_repository):
        learning = self._create_learning(learning_repository)

        assert learning is not None
        assert learning.id is not None

    def test_create_with_id(self, learning_repository):
        vec = mock_vector()
        uid = uuid.uuid4()
        learning_repository.learning_collection.tenants.create("test")
        learning = learning_repository.save(
            "test",
            Learning(
                uid=uid,
                title="Test Title",
                content="Test Content",
                reference="Test Reference",
                vectors={"vector_0": vec},
            ),
        )

        assert learning is not None
        assert learning.id == uid

    def test_delete(self, learning_repository):
        learning = self._create_learning(learning_repository)

        learning_repository.delete("test", learning.id)

        assert learning_repository.find("test", learning.id) is None

    def test_get(self, learning_repository):
        learning = self._create_learning(learning_repository)

        retrieved_learning = learning_repository.find("test", learning.id)

        assert retrieved_learning is not None
        assert retrieved_learning.id == learning.id
        assert retrieved_learning.title == learning.title
        assert retrieved_learning.content == learning.content
        assert retrieved_learning.reference == learning.reference

        compare_vectors(learning.vectors, retrieved_learning.vectors)

    def test_update(self, learning_repository):
        learning = self._create_learning(learning_repository)

        learning.title = "Updated Title"
        learning.content = "Updated Content"
        learning.reference = "Updated Reference"
        learning.vectors["vector_0"] = mock_vector()

        learning_repository.save("test", learning)

        updated_learning = learning_repository.find("test", learning.id)

        assert updated_learning is not None
        assert updated_learning.id == learning.id
        assert updated_learning.title == "Updated Title"
        assert updated_learning.content == "Updated Content"
        assert updated_learning.reference == "Updated Reference"
        compare_vectors(learning.vectors, updated_learning.vectors)

    def test_all(self, learning_repository):
        learning1 = self._create_learning(learning_repository)
        learning2 = self._create_learning(learning_repository)
        learning3 = self._create_learning(learning_repository)

        all_learnings = learning_repository.all("test")

        assert all_learnings is not None
        assert len(all_learnings) >= 3

        all_ids = [learning.id for learning in all_learnings]

        assert learning1.id in all_ids
        assert learning2.id in all_ids
        assert learning3.id in all_ids

    def test_search(self, learning_repository):
        learning1 = self._create_learning(learning_repository)
        learning2 = self._create_learning(learning_repository)
        _ = self._create_learning(learning_repository)

        search_results = learning_repository.search(
            "test", "vector_0", learning1.vectors["vector_0"], 1
        )
        assert search_results is not None
        assert len(search_results) >= 1
        assert search_results[0].id == learning1.id

        search_results = learning_repository.search(
            "test", "vector_0", learning2.vectors["vector_0"], 1
        )
        assert search_results is not None
        assert len(search_results) >= 1
        assert search_results[0].id == learning2.id

    def test_search_empty(self, weaviate_client: WeaviateClient, learning_repository):
        weaviate_client.collections.get("Learning").tenants.create("test_empty")
        search_results = learning_repository.search(
            "test_empty", "vector_0", mock_vector(), 1
        )
        assert search_results is not None
        assert len(search_results) == 0

    def test_search_multi(self, learning_repository):
        learning1 = self._create_learning(learning_repository)
        learning2 = self._create_learning(learning_repository)
        _ = self._create_learning(learning_repository)

        search_results = learning_repository.search_multi(
            "test", {"vector_0": learning1.vectors["vector_0"]}, 1
        )
        assert search_results is not None
        assert len(search_results) >= 1
        assert search_results[0].id == learning1.id

        search_results = learning_repository.search_multi(
            "test", {"vector_0": learning2.vectors["vector_0"]}, 1
        )
        assert search_results is not None
        assert len(search_results) >= 1
        assert search_results[0].id == learning2.id

    def test_search_multi_empty(
        self, weaviate_client: WeaviateClient, learning_repository
    ):
        weaviate_client.collections.get("Learning").tenants.create("test_empty")
        search_results = learning_repository.search_multi(
            "test_empty", {"vector_0": mock_vector()}, 1
        )
        assert search_results is not None
        assert len(search_results) == 0
