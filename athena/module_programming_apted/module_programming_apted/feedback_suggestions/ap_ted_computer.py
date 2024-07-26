from dataclasses import dataclass
from typing import Dict, Tuple, Union, cast

from apted import APTED, Config  # pylint: disable=import-error


class FeedbackFocusedConfig(Config):
    def rename(self, node1, node2):
        # Adjusting the renaming costs depending on the node type
        if 'Var' in node1.name and 'Var' in node2.name:
            return 0  # Ignore variable renaming
        if 'Literal' in node1.name and 'Literal' in node2.name:
            return 0.1  # Low costs for changes in literals
        if 'Comment' in node1.name and 'Comment' in node2.name:
            return 0  # Ignore commmets
        return 1 if node1.name != node2.name else 0  # Standardkosten für andere Typen

    def insert(self, node):
        # Higher costs for inserting new control structures
        if 'Control' in node.name:
            return 2
        return 1

    def delete(self, node):
        # Higher costs for deleting new control structures
        if 'Control' in node.name:
            return 2
        return 1


def remove_whitespace(s: str) -> str:
    return "".join(s.split())


def cache_key(code1: str, code2: str) -> Tuple[str, str]:
    return remove_whitespace(code1), remove_whitespace(code2)


@dataclass
class UncomputedComparison:
    code1: str
    tree1: str
    code2: str
    tree2: str


@dataclass
class SimilarityScore:
    distance: float

    def __repr__(self):
        return f"SimilarityScore(distance={self.distance})"

    def __str__(self):
        return f"distance={self.distance}"


class CodeSimilarityComputer:
    """
    Takes multiple pairs of code snippets and their corresponding tree representations,
    and computes their similarity scores using AP-TED. It also caches the similarity
    scores for faster computation and auto-assigns a similarity of 0.0 distance to
    identical code snippets (ignoring whitespace).
    """

    def __init__(self) -> None:
        # keys are with all whitespace removed
        self.cache: Dict[Tuple[str, str], Union[SimilarityScore, UncomputedComparison]] = {}

    def add_comparison(self, code1: str, tree1: str, code2: str, tree2: str):
        """Add a comparison to later compute."""
        key = cache_key(code1, code2)
        if key in self.cache:
            return
        if remove_whitespace(code1) == remove_whitespace(code2):
            # identical code snippets in almost all cases
            self.cache[key] = SimilarityScore(0.0)  # perfect match (distance is 0)
        else:
            self.cache[key] = UncomputedComparison(code1, tree1, code2, tree2)

    def compute_similarity_scores(self):
        """Compute the similarity scores for all comparisons."""
        wanted_comparisons = []

        for value in self.cache.values():
            if isinstance(value, UncomputedComparison):
                wanted_comparisons.append((value.code1, value.tree1, value.code2, value.tree2))

        if not wanted_comparisons:
            return

        for code1, tree1, code2, tree2 in wanted_comparisons:
            apted = APTED(tree1, tree2, FeedbackFocusedConfig())
            distance = apted.compute_edit_distance()
            mapping = apted.compute_edit_mapping()  # TODO: Not needed now, but maybe for the config
            self.cache[cache_key(code1, code2)] = SimilarityScore(distance)

    def get_similarity_score(self, code1: str, code2: str) -> SimilarityScore:
        """Get the similarity score for a comparison."""
        key = cache_key(code1, code2)
        if key not in self.cache:
            raise ValueError("Similarity score not yet computed. Call compute_similarity_scores() first.")
        if isinstance(self.cache[key], UncomputedComparison):
            raise ValueError("Similarity score not yet computed. Call compute_similarity_scores() first.")
        return cast(SimilarityScore, self.cache[key])