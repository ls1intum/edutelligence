"""The semantic chunker keeps LangChain SemanticChunker's output.

The expected chunks below were produced by ``langchain_experimental``'s
``SemanticChunker`` (0.4.x) with the same fake embeddings, before Iris replaced
it; transcriptions must keep being chunked the same way.
"""

import hashlib
import random

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm.semantic_chunker import split_semantically  # noqa: E402

TEXT = (
    "Merge sort splits the array. It sorts both halves! Then it merges them. "
    "Is that stable? Yes. "
    "Heaps are trees. The root is the minimum. Insertion moves up. "
    "Removal moves down. "
    "Dijkstra uses a heap. It finds shortest paths? Only without negative edges. "
    "That is the rule."
)


def _embedding(text: str) -> list[float]:
    generator = random.Random(hashlib.sha256(text.encode()).hexdigest())
    return [generator.uniform(-1, 1) for _ in range(8)]


def _embed_documents(texts: list[str]) -> list[list[float]]:
    return [_embedding(text) for text in texts]


@pytest.mark.parametrize(
    "kind,amount,min_chunk_size,expected",
    [
        (
            "percentile",
            50.0,
            None,
            [
                "Merge sort splits the array. It sorts both halves!",
                "Then it merges them.",
                "Is that stable?",
                "Yes. Heaps are trees.",
                "The root is the minimum. Insertion moves up.",
                "Removal moves down.",
                "Dijkstra uses a heap. It finds shortest paths? Only without "
                "negative edges. That is the rule.",
            ],
        ),
        (
            "percentile",
            50.0,
            40,
            [
                "Merge sort splits the array. It sorts both halves!",
                "Then it merges them. Is that stable? Yes. Heaps are trees.",
                "The root is the minimum. Insertion moves up.",
                "Removal moves down. Dijkstra uses a heap. It finds shortest paths? "
                "Only without negative edges. That is the rule.",
            ],
        ),
        (
            "standard_deviation",
            0.5,
            None,
            [
                "Merge sort splits the array. It sorts both halves!",
                "Then it merges them.",
                "Is that stable? Yes. Heaps are trees.",
                "The root is the minimum. Insertion moves up.",
                "Removal moves down.",
                "Dijkstra uses a heap. It finds shortest paths? Only without "
                "negative edges. That is the rule.",
            ],
        ),
        (
            "standard_deviation",
            0.5,
            40,
            [
                "Merge sort splits the array. It sorts both halves!",
                "Then it merges them. Is that stable? Yes. Heaps are trees.",
                "The root is the minimum. Insertion moves up.",
                "Removal moves down. Dijkstra uses a heap. It finds shortest paths? "
                "Only without negative edges. That is the rule.",
            ],
        ),
        (
            "interquartile",
            0.2,
            None,
            [
                "Merge sort splits the array. It sorts both halves!",
                "Then it merges them.",
                "Is that stable?",
                "Yes. Heaps are trees.",
                "The root is the minimum. Insertion moves up.",
                "Removal moves down.",
                "Dijkstra uses a heap. It finds shortest paths? Only without "
                "negative edges. That is the rule.",
            ],
        ),
        (
            "interquartile",
            0.2,
            40,
            [
                "Merge sort splits the array. It sorts both halves!",
                "Then it merges them. Is that stable? Yes. Heaps are trees.",
                "The root is the minimum. Insertion moves up.",
                "Removal moves down. Dijkstra uses a heap. It finds shortest paths? "
                "Only without negative edges. That is the rule.",
            ],
        ),
        (
            "gradient",
            60.0,
            None,
            [
                "Merge sort splits the array.",
                "It sorts both halves!",
                "Then it merges them. Is that stable? Yes. Heaps are trees.",
                "The root is the minimum. Insertion moves up.",
                "Removal moves down. Dijkstra uses a heap. It finds shortest paths?",
                "Only without negative edges. That is the rule.",
            ],
        ),
        (
            "gradient",
            60.0,
            40,
            [
                "Merge sort splits the array. It sorts both halves!",
                "Then it merges them. Is that stable? Yes. Heaps are trees.",
                "The root is the minimum. Insertion moves up.",
                "Removal moves down. Dijkstra uses a heap. It finds shortest paths?",
                "Only without negative edges. That is the rule.",
            ],
        ),
    ],
)
def test_matches_langchain_semantic_chunker(kind, amount, min_chunk_size, expected):
    assert (
        split_semantically(
            TEXT,
            _embed_documents,
            breakpoint_threshold_type=kind,
            breakpoint_threshold_amount=amount,
            min_chunk_size=min_chunk_size,
        )
        == expected
    )


def test_single_sentence_is_one_chunk_without_embedding():
    def fail(texts):
        raise AssertionError(f"no embedding needed for {texts}")

    assert split_semantically("Only one sentence", fail) == ["Only one sentence"]


def test_two_sentences_with_gradient_are_returned_as_they_are():
    def fail(texts):
        raise AssertionError(f"no embedding needed for {texts}")

    assert split_semantically("One. Two.", fail, "gradient") == ["One.", "Two."]


def test_zero_vectors_count_as_unrelated():
    chunks = split_semantically(
        "A. B. C. D.",
        lambda texts: [[0.0, 0.0] for _ in texts],
        breakpoint_threshold_type="percentile",
        breakpoint_threshold_amount=50.0,
    )
    assert " ".join(chunks) == "A. B. C. D."
