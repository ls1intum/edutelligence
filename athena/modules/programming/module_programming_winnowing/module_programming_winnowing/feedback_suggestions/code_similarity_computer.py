from dataclasses import dataclass
from typing import Dict, Tuple, Union, cast
from module_programming_winnowing.feedback_suggestions.winnowing import calculate_similarity

from module_programming_winnowing.convert_code_to_ast.languages.python.PythonAstVisitor import analyze as analyze_python
from module_programming_winnowing.convert_code_to_ast.languages.java.JavaAstVisitor import analyze as analyze_java


def remove_whitespace(s: str) -> str:
    return "".join(s.split())


def cache_key(code1: str, code2: str) -> Tuple[str, str]:
    return remove_whitespace(code1), remove_whitespace(code2)


@dataclass
class UncomputedComparison:
    code1: str
    counts1: list[int]
    levels1: list[list]
    code2: str
    counts2: list[int]
    levels2: list[list]


@dataclass
class SimilarityScore:
    similarity_score: float

    def __repr__(self):
        return f"SimilarityScore(similarity_score={self.similarity_score})"

    def __str__(self):
        return f"similarity_score={self.similarity_score}"


def create_ast_level_and_counts(code: str, programming_language: str):
    if programming_language == "java":
        #  return analyze_java(code)
        return
    if programming_language == "python":
        return analyze_python(code)
    raise ValueError(f"Unsupported programming language: {programming_language}")


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

    def add_comparison(self, code1: str, code2: str, programming_language: str):
        """Add a comparison to later compute."""
        key = cache_key(code1, code2)
        if key in self.cache:
            return
        if remove_whitespace(code1) == remove_whitespace(code2):
            # identical code snippets in almost all cases
            self.cache[key] = SimilarityScore(100.0)  # perfect match (Similarity Score = 100)
        else:
            counts1, level1 = create_ast_level_and_counts(code1, programming_language)
            counts2, level2 = create_ast_level_and_counts(code2, programming_language)
            self.cache[key] = UncomputedComparison(code1, counts1, level1, code2, counts2, level2)

    def compute_similarity_scores(self):
        """Compute the similarity scores for all comparisons."""
        wanted_comparisons = []

        for value in self.cache.values():
            if isinstance(value, UncomputedComparison):
                wanted_comparisons.append((value.code1, value.counts1, value.levels1, value.code2, value.counts2,
                                           value.levels2))
        if not wanted_comparisons:
            return

        for code1, counts1, levels1, code2, counts2, levels2 in wanted_comparisons:
            similarity_score = calculate_similarity(counts1, levels1, counts2, levels2)
            self.cache[cache_key(code1, code2)] = SimilarityScore(similarity_score)

    def get_similarity_score(self, code1: str, code2: str) -> SimilarityScore:
        """Get the similarity score for a comparison."""
        key = cache_key(code1, code2)
        if key not in self.cache:
            raise ValueError("Similarity score not yet computed. Call compute_similarity_scores() first.")
        if isinstance(self.cache[key], UncomputedComparison):
            raise ValueError("Similarity score not yet computed. Call compute_similarity_scores() first.")
        return cast(SimilarityScore, self.cache[key])


# TODO: These are test functions; to be deleted when productive later
def test_code_similarity_computer():
    # Beispiel-Code-Snippets
    code1 = """
        public class HelloWorld {
        public static void main(String[] args) {
            System.out.println("Hello, wooorld!");
            int feld = 4;
            int test = 5;
        
    }"""
    code2 = """
    public class HelloWorld {
        public static void main(String[] args) {
            System.out.println("Hello, wooorld!");
            int test = 5;
            
    }"""

    # Initialisiere den CodeSimilarityComputer
    sim_computer = CodeSimilarityComputer()

    # Füge die Code-Vergleiche hinzu
    sim_computer.add_comparison(code1, code2, "java")

    # Berechne die Ähnlichkeitspunkte
    sim_computer.compute_similarity_scores()

    # Hole die Ähnlichkeitspunkte
    similarity = sim_computer.get_similarity_score(code1, code2)

    # Ausgabe der Ähnlichkeit
    print(f"Similarity score between code1 and code2: {similarity.similarity_score}")


if __name__ == "__main__":
    test_code_similarity_computer()
