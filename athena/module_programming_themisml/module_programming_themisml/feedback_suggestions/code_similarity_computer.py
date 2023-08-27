"""
This module computes the similarity between two code snippets using CodeBERT. It also caches
the similarity scores for faster computation and auto-assigns a similarity of 1.0 to identical
code snippets (ignoring whitespace).
"""

import os
from dataclasses import dataclass
from typing import Dict, Tuple, Union, cast

from code_bert_score import score
import torch

from athena.logger import logger


def get_model_params(lang: str) -> dict:
    if "ML_JAVA_MODEL" in os.environ:
        if os.path.exists(os.environ["ML_JAVA_MODEL"]):
            logger.debug("Using local model")
            return { "model_type": os.environ["ML_JAVA_MODEL"] }
        logger.debug("Local model not found, using default model")
    return { "lang": lang }


def get_optimal_torch_device():
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():  # type: ignore # MacOS devices with Metal programming framework
        return torch.device("mps")
    return torch.device("cpu")


def remove_whitespace(s: str) -> str:
    return "".join(s.split())


def cache_key(code1: str, code2: str) -> Tuple[str, str]:
    return remove_whitespace(code1), remove_whitespace(code2)


@dataclass
class UncomputedComparison:
    code1: str
    code2: str


@dataclass
class SimilarityScore:
    precision: float
    recall: float
    f1: float
    f3: float

    def __repr__(self):
        return f"SimilarityScore(precision={self.precision}, recall={self.recall}, f1={self.f1}, f3={self.f3})"

    def __str__(self):
        return f"precision={self.precision}, recall={self.recall}, f1={self.f1}, f3={self.f3}"


class CodeSimilarityComputer:
    """
    Takes multiple pairs of code snippets and computes their similarity scores using CodeBERT.
    It also caches the similarity scores for faster computation and auto-assigns a similarity
    of 1.0 to identical code snippets (ignoring whitespace).
    """
    # keys are with all whitespace removed
    cache: Dict[Tuple[str, str], Union[SimilarityScore, UncomputedComparison]] = {}

    def add_comparison(self, code1: str, code2: str):
        """Add a comparison to later compute."""
        key = cache_key(code1, code2)
        if key in self.cache:
            return
        if remove_whitespace(code1) == remove_whitespace(code2):
            # identical code snippets in almost all cases
            self.cache[key] = SimilarityScore(1.0, 1.0, 1.0, 1.0)  # perfect match
        else:
            self.cache[key] = UncomputedComparison(code1, code2)

    def compute_similarity_scores(self):
        """Compute the similarity scores for all comparisons."""
        wanted_comparisons = []

        for value in self.cache.values():
            if isinstance(value, UncomputedComparison):
                wanted_comparisons.append((value.code1, value.code2))

        if not wanted_comparisons:
            return

        # F1 is the similarity score, F3 is similar to F1 but with a higher weight for recall than precision
        precision, recall, f1, f3 = score(  # noqa
            cands=[c[0] for c in wanted_comparisons],
            refs=[c[1] for c in wanted_comparisons],
            device=get_optimal_torch_device(),
            **get_model_params("java")  # TODO: only works for java
        )
        for (code1, code2), precision, recall, f1, f3 in zip(
                wanted_comparisons,
                precision.tolist(),  # type: ignore
                recall.tolist(),  # type: ignore
                f1.tolist(),  # type: ignore
                f3.tolist()  # type: ignore
        ):
            self.cache[cache_key(code1, code2)] = SimilarityScore(precision, recall, f1, f3)

    def get_similarity_score(self, code1: str, code2: str) -> SimilarityScore:
        """Get the similarity score for a comparison."""
        key = cache_key(code1, code2)
        if key not in self.cache:
            raise ValueError("Similarity score not yet computed. Call compute_similarity_scores() first.")
        if isinstance(self.cache[key], UncomputedComparison):
            raise ValueError("Similarity score not yet computed. Call compute_similarity_scores() first.")
        return cast(SimilarityScore, self.cache[key])
