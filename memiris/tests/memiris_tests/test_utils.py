import random
from typing import Mapping, Sequence


def mock_vector(size: int = 4) -> list[float]:
    """Generate a mock vector for testing."""

    return [round(random.uniform(-1, 1), 2) for _ in range(size)]


def compare_vectors(
    vectors1: Mapping[str, Sequence[float]], vectors2: Mapping[str, Sequence[float]]
):
    assert len(vectors1) == len(vectors2)
    for key in vectors1:
        assert key in vectors2
        assert len(vectors1[key]) == len(vectors2[key])
        for i in range(len(vectors1[key])):
            assert abs(vectors1[key][i] - vectors1[key][i]) < 1e-6
