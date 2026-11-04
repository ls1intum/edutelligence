"""Split text where the topic changes, measured with embeddings.

This is the algorithm of LangChain's ``SemanticChunker`` (from
``langchain-experimental``, which is no longer maintained), reduced to what Iris
uses and kept output-compatible, so transcriptions ingested before and after the
switch are chunked the same way:

1. Split the text into sentences after ``.``, ``?`` or ``!``.
2. Embed each sentence together with its neighbours (``buffer_size`` on each side).
3. Compute the cosine distance between each window and the next one.
4. Break after every sentence whose distance (or, for ``gradient``, the gradient
   of the distances) is above the chosen threshold, merging pieces shorter than
   ``min_chunk_size`` into the next one.
"""

import re
from typing import Callable, Literal, Optional

import numpy as np

BreakpointThresholdType = Literal[
    "percentile", "standard_deviation", "interquartile", "gradient"
]

BREAKPOINT_DEFAULTS: dict[str, float] = {
    "percentile": 95,
    "standard_deviation": 3,
    "interquartile": 1.5,
    "gradient": 95,
}

SENTENCE_SPLIT_PATTERN = r"(?<=[.?!])\s+"


def _windows(sentences: list[str], buffer_size: int) -> list[str]:
    """Each sentence joined with up to ``buffer_size`` neighbours on each side."""
    windows = []
    for index in range(len(sentences)):
        start = max(0, index - buffer_size)
        end = min(len(sentences), index + 1 + buffer_size)
        windows.append(" ".join(sentences[start:end]))
    return windows


def _cosine_similarity(first: list[float], second: list[float]) -> float:
    a = np.asarray(first, dtype=float)
    b = np.asarray(second, dtype=float)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    similarity = float(np.dot(a, b) / norm)
    return 0.0 if np.isnan(similarity) or np.isinf(similarity) else similarity


def _cosine_distances(embeddings: list[list[float]]) -> list[float]:
    return [
        1 - _cosine_similarity(embeddings[index], embeddings[index + 1])
        for index in range(len(embeddings) - 1)
    ]


def _threshold(
    distances: list[float], kind: str, amount: float
) -> tuple[float, list[float]]:
    """The breakpoint threshold and the values to compare with it."""
    if kind == "percentile":
        return float(np.percentile(distances, amount)), distances
    if kind == "standard_deviation":
        return float(np.mean(distances) + amount * np.std(distances)), distances
    if kind == "interquartile":
        first_quartile, third_quartile = np.percentile(distances, [25, 75])
        spread = third_quartile - first_quartile
        return float(np.mean(distances) + amount * spread), distances
    if kind == "gradient":
        gradient = np.gradient(distances, range(0, len(distances)))
        return float(np.percentile(gradient, amount)), list(gradient)
    raise ValueError(f"Unknown breakpoint threshold type: {kind}")


def split_semantically(
    text: str,
    embed_documents: Callable[[list[str]], list[list[float]]],
    breakpoint_threshold_type: BreakpointThresholdType = "percentile",
    breakpoint_threshold_amount: Optional[float] = None,
    min_chunk_size: Optional[int] = None,
    buffer_size: int = 1,
) -> list[str]:
    """Split ``text`` into chunks at the largest changes of meaning."""
    sentences = re.split(SENTENCE_SPLIT_PATTERN, text)
    # Percentiles need at least one distance, gradients at least two.
    if len(sentences) == 1:
        return sentences
    if breakpoint_threshold_type == "gradient" and len(sentences) == 2:
        return sentences

    amount = (
        BREAKPOINT_DEFAULTS[breakpoint_threshold_type]
        if breakpoint_threshold_amount is None
        else breakpoint_threshold_amount
    )
    distances = _cosine_distances(embed_documents(_windows(sentences, buffer_size)))
    threshold, values = _threshold(distances, breakpoint_threshold_type, amount)

    chunks: list[str] = []
    start = 0
    for index, value in enumerate(values):
        if value <= threshold:
            continue
        chunk = " ".join(sentences[start : index + 1])  # noqa: E203
        if min_chunk_size is not None and len(chunk) < min_chunk_size:
            continue
        chunks.append(chunk)
        start = index + 1
    if start < len(sentences):
        chunks.append(" ".join(sentences[start:]))
    return chunks
