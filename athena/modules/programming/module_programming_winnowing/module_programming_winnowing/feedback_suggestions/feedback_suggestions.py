from typing import Dict, Iterable, List, Optional
import gc

from athena.helpers.programming.feedback import format_feedback_title
from athena.logger import logger
from athena.programming import Feedback, Submission
from module_programming_winnowing.convert_code_to_ast.extract_method_and_ast import parse
from module_programming_winnowing.convert_code_to_ast.method_node import MethodNode
from module_programming_winnowing.feedback_suggestions.batch import batched
from module_programming_winnowing.feedback_suggestions.code_similarity_computer import CodeSimilarityComputer

SIMILARITY_THRESHOLD = 95  # TODO Needs to be adapted


def make_feedback_suggestion_from(feedback: Feedback, submission: Submission,
                                  submission_method: MethodNode) -> Feedback:
    suggestion = feedback.model_copy(deep=True)
    # add meta information for debugging
    suggestion.meta["original_feedback_id"] = feedback.id
    suggestion.meta["original_method_code"] = suggestion.meta["method_code"]
    suggestion.meta["method_code"] = submission_method.source_code
    # adjust for submission
    suggestion.submission_id = submission.id
    suggestion.line_start = submission_method.line_start
    suggestion.line_end = submission_method.line_end
    # regenerate title from filename and line numbers
    suggestion.title = format_feedback_title(suggestion.file_path, suggestion.line_start, suggestion.line_end)
    # remove ID
    suggestion.id = None
    return suggestion

class CodeComparisonWithCorrespondingSuggestions:
    """A pair of code snippets with a corresponding suggestions if their similarity is high enough."""

    def __init__(self, code1: str, code2: str, suggestion: Feedback) -> None:
        self.code1 = code1
        self.code2 = code2
        self.suggestion = suggestion

    def has_same_code(self, other) -> bool:
        return self.code1 == other.code1 and self.code2 == other.code2


def group_feedbacks_by_file_path(feedbacks: List[Feedback]) -> Dict[str, List[Feedback]]:
    """Groups feedbacks by file path for faster access."""
    feedbacks_by_file_path: Dict[str, List[Feedback]] = {}
    for feedback in feedbacks:
        if feedback.file_path not in feedbacks_by_file_path:
            feedbacks_by_file_path[str(feedback.file_path)] = []
        feedbacks_by_file_path[str(feedback.file_path)].append(feedback)
    return feedbacks_by_file_path


def create_comparisons_with_suggestions(
        submissions: List[Submission],
        feedbacks: List[Feedback],
        programming_language: str,
) -> Iterable[CodeComparisonWithCorrespondingSuggestions]:
    """Creates code comparisons and corresponding feedback suggestions as a generator."""
    if len(feedbacks) == 0:
        return
    # group feedbacks by file path for faster access
    logger.debug("Grouping %d feedbacks by file path", len(feedbacks))
    feedbacks_by_file_path = group_feedbacks_by_file_path(feedbacks)
    for submission in submissions:
        for file_path, file_feedbacks in feedbacks_by_file_path.items():
            # read file from submission
            try:
                code = submission.get_code(file_path)
            except KeyError:  # KeyError is for when the file is not in the zip
                logger.debug("File %s not found in submission %d.", file_path, submission.id)
                continue
            except UnicodeDecodeError:
                logger.warning("File %s in submission %d is not UTF-8 encoded.", file_path, submission.id)
                continue
            # get all methods in the file of the submission
            submission_methods = parse(code, programming_language)
            # get all feedbacks that match methods in the submission
            for s_method in submission_methods:
                for feedback in file_feedbacks:
                    if feedback.submission_id == submission.id:
                        # don't compare feedback with itself
                        continue
                    if feedback.meta["method_name"] == s_method.name:
                        # compare code (later) and add feedback as a possible suggestion (also later)
                        suggestion = make_feedback_suggestion_from(feedback, submission, s_method)
                        yield CodeComparisonWithCorrespondingSuggestions(s_method.source_code,
                                                                         feedback.meta["method_code"], suggestion)


def create_feedback_suggestions(
        submissions: List[Submission],
        feedbacks: List[Feedback],
        programming_language: str,
) -> List[Feedback]:
    """
    Get a list of all submissions that the given feedback could also apply to (similar code in same method).
    Then generate feedback suggestions for those submissions.
    """
    if len(feedbacks) == 0:
        return []  # nothing to do

    suggestions: List[Feedback] = []

    # create code comparisons and corresponding feedback suggestions in batches for less memory usage
    for idx, comparisons_with_suggestions in enumerate(
            batched(create_comparisons_with_suggestions(submissions, feedbacks, programming_language), 128)):
        # compute similarity scores for all comparisons at once
        sim_computer = CodeSimilarityComputer()
        for s_comp in comparisons_with_suggestions:
            sim_computer.add_comparison(s_comp.code1, s_comp.code2, programming_language)
        logger.debug("Computing similarity scores for %d code comparisons (batch #%d)",
                     len(comparisons_with_suggestions), idx)
        sim_computer.compute_similarity_scores()  # compute all at once, enables vectorization

        # create suggestions
        for s_comp in comparisons_with_suggestions:
            similarity = sim_computer.get_similarity_score(s_comp.code1, s_comp.code2)
            if similarity.similarity_score <= SIMILARITY_THRESHOLD:
                # found similar code -> create feedback suggestion
                logger.info("Found similar code wih similarity of %d", similarity.similarity_score)
                # add meta information for debugging
                s_comp.suggestion.meta["similarity_score"] = similarity.similarity_score
                # add to suggestions
                suggestions.append(s_comp.suggestion)
        # clear memory to prevent being killed by OOM killer
        del sim_computer
        del comparisons_with_suggestions
        gc.collect()

    return suggestions


# TODO From here on these are just testing functions below:
def extract_methods_from_code(code, programming_language):
    # Parsing und AST-Erstellung
    methods = parse(code, programming_language)

    # Ausgabe der extrahierten Methoden
    print("Extrahierte Methoden:")
    for method in methods:
        print(f"Method Name: {method.name}")
        print(f"Method Source Code:\n{method.source_code}\n")
        print(f"Method Start Line: {method.line_start}, End Line: {method.line_end}\n")

    return methods


def compare_methods(methods1, methods2, programming_language):
    # Initialisiere den CodeSimilarityComputer
    sim_computer = CodeSimilarityComputer()

    # Füge die Code-Vergleiche hinzu
    for method1 in methods1:
        for method2 in methods2:
            sim_computer.add_comparison(method1.source_code, method2.source_code, programming_language)

    # Berechne die Ähnlichkeitspunkte
    sim_computer.compute_similarity_scores()

    # Ausgabe der Ähnlichkeitspunkte
    for method1 in methods1:
        for method2 in methods2:
            similarity = sim_computer.get_similarity_score(method1.source_code, method2.source_code)
            print(f"Similarity score between {method1.name} and {method2.name}: {similarity.similarity_score}")


def test_ast_creation_and_code_similarity():
    code1 = """
 def sum_first_ten():
     sum = 0
     return sum
 """

    code2 = """
 def sum_first_ten():
     sum = 0
     for i in range(11):
         sum += i
     return sum
 """

    programming_language = "python"

    print("Extracting methods from code1...")
    methods1 = extract_methods_from_code(code1, programming_language)

    print("Extracting methods from code2...")
    methods2 = extract_methods_from_code(code2, programming_language)

    print("Comparing methods from code1 and code2...")
    compare_methods(methods1, methods2, programming_language)


if __name__ == "__main__":
    test_ast_creation_and_code_similarity()
