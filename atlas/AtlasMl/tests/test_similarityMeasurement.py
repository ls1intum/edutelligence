from enum import Enum

import pytest
from scipy.spatial.distance import cosine, euclidean, jaccard

from atlasml.ml.similarity_measures import (
    compute_cosine_similarity,
    compute_euclidean_distance,
    compute_jaccard_similarity,
)


class MockModelDimension(Enum):
    """Mock class for ModelDimension enum for testing."""

    D2 = 2
    D3 = 3
    D4 = 4


### Cosine Similarity tests ###


def test_cosine_similarity_identical_vectors():
    """Test cosine similarity for identical vectors."""
    vector = [1, 2, 3]
    similarity = compute_cosine_similarity(vector, vector)
    assert similarity == pytest.approx(1.0, rel=1e-6)


def test_cosine_similarity_orthogonal_vectors():
    """Test cosine similarity for orthogonal vectors."""
    vector1 = [1, 0]
    vector2 = [0, 1]
    similarity = compute_cosine_similarity(vector1, vector2)
    assert similarity == pytest.approx(0.0, rel=1e-6)


def test_cosine_similarity_opposite_vectors():
    """Test cosine similarity for opposite vectors."""
    vector1 = [1, 2, 3]
    vector2 = [-1, -2, -3]
    similarity = compute_cosine_similarity(vector1, vector2)
    assert similarity == pytest.approx(-1.0, rel=1e-6)


def test_cosine_similarity_random_vectors():
    """Test cosine similarity with two random vectors."""
    vector1 = [0.5, 1.0, -0.5]
    vector2 = [-0.5, -1.0, 0.5]
    expected_similarity = 1.0 - cosine(vector1, vector2)
    similarity = compute_cosine_similarity(vector1, vector2)
    assert similarity == pytest.approx(expected_similarity, rel=1e-6)


def test_cosine_similarity_mismatched_dimensions():
    """Test if function raises ValueError when vectors have different dimensions."""
    vector1 = [1, 2, 3]
    vector2 = [1, 2]
    with pytest.raises(ValueError, match="Vector dimensions must match"):
        compute_cosine_similarity(vector1, vector2)


### Euclidian Similarity tests ###


def test_euclidean_distance_identical_vectors():
    """Test Euclidean distance for identical vectors (should be 0)."""
    vector = [1, 2, 3]
    distance = compute_euclidean_distance(vector, vector)
    assert distance == pytest.approx(0.0, rel=1e-6)


def test_euclidean_distance_different_vectors():
    """Test Euclidean distance for two different vectors."""
    vector1 = [1, 2, 3]
    vector2 = [4, 5, 6]
    expected_distance = euclidean(vector1, vector2)
    distance = compute_euclidean_distance(vector1, vector2)
    assert distance == pytest.approx(expected_distance, rel=1e-6)


def test_euclidean_distance_with_negative_values():
    """Test Euclidean distance with vectors containing negative values."""
    vector1 = [-1, -2, -3]
    vector2 = [1, 2, 3]
    expected_distance = euclidean(vector1, vector2)
    distance = compute_euclidean_distance(vector1, vector2)
    assert distance == pytest.approx(expected_distance, rel=1e-6)


def test_euclidean_distance_zeros():
    """Test Euclidean distance with zero vectors."""
    vector1 = [0, 0, 0]
    vector2 = [0, 0, 0]
    distance = compute_euclidean_distance(vector1, vector2)
    assert distance == pytest.approx(0.0, rel=1e-6)


def test_euclidean_distance_mismatched_dimensions():
    """Test if function raises ValueError when vectors have different dimensions."""
    vector1 = [1, 2, 3]
    vector2 = [1, 2]
    with pytest.raises(ValueError, match="Vector dimensions must match"):
        compute_euclidean_distance(vector1, vector2)


### Jaccard Similarity tests ###


def test_jaccard_similarity_identical_vectors():
    """Test Jaccard similarity for identical binary vectors (should be 1)."""
    vector = [1, 0, 1, 1, 0]
    similarity = compute_jaccard_similarity(vector, vector)
    assert similarity == pytest.approx(1.0, rel=1e-6)


def test_jaccard_similarity_completely_different_vectors():
    """Test Jaccard similarity for completely different binary vectors (should be 0)."""
    vector1 = [1, 1, 1, 1, 1]
    vector2 = [0, 0, 0, 0, 0]
    similarity = compute_jaccard_similarity(vector1, vector2)
    assert similarity == pytest.approx(0.0, rel=1e-6)


def test_jaccard_similarity_partial_overlap():
    """Test Jaccard similarity for partially overlapping binary vectors."""
    vector1 = [1, 0, 1, 0, 1]
    vector2 = [1, 1, 0, 0, 1]
    expected_similarity = 1.0 - jaccard(vector1, vector2)
    similarity = compute_jaccard_similarity(vector1, vector2)
    assert similarity == pytest.approx(expected_similarity, rel=1e-6)


def test_jaccard_similarity_mismatched_dimensions():
    """Test if a function raises ValueError when vectors have different dimensions."""
    vector1 = [1, 0, 1]
    vector2 = [1, 0]
    with pytest.raises(ValueError, match="Vector dimensions must match"):
        compute_jaccard_similarity(vector1, vector2)
