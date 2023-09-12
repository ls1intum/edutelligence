from typing import Dict, List, Tuple
from athena.helpers.programming.feedback import format_feedback_title

from athena.logger import logger
from athena.programming import Feedback, Submission

from module_programming_themisml.extract_methods import MethodNode, extract_methods
from .code_similarity_computer import CodeSimilarityComputer

SIMILARITY_SCORE_THRESHOLD = 0.95  # has to be really high - otherwise, there would just be too many feedback suggestions


def make_feedback_suggestion_from(feedback: Feedback, submission: Submission, submission_method: MethodNode) -> Feedback:
    suggestion = feedback.copy(deep=True)
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


def create_feedback_suggestions(
    submissions: List[Submission],
    feedbacks: List[Feedback],
) -> List[Feedback]:
    """
    Get a list of all submissions that the given feedback could also apply to (similar code in same method).
    Then generate feedback suggestions for those submissions.
    """
    # group feedbacks by file path for faster access
    logger.debug("Grouping %d feedbacks by file path", len(feedbacks))
    feedbacks_by_file_path: Dict[str, List[Feedback]] = {}
    for feedback in feedbacks:
        if feedback.file_path not in feedbacks_by_file_path:
            feedbacks_by_file_path[str(feedback.file_path)] = []
        feedbacks_by_file_path[str(feedback.file_path)].append(feedback)

    # create suggestions that will be given if the similarity is high
    logger.debug("Reading code from %d submissions", len(submissions))
    code_comparisons_with_suggestions: Dict[Tuple[str, str], List[Feedback]] = {}  # key: (code1, code2), value: list of suggestions to give if the similarity is high
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
            submission_methods = extract_methods(code)
            # get all feedbacks that match methods in the submission
            for s_method in submission_methods:
                for feedback in file_feedbacks:
                    if feedback.submission_id == submission.id:
                        # don't compare feedback with itself
                        continue
                    if feedback.meta["method_name"] == s_method.name:
                        # compare code (later) and add feedback as a possible suggestion (also later)
                        suggestion = make_feedback_suggestion_from(feedback, submission, s_method)
                        comparison_key = (s_method.source_code, feedback.meta["method_code"])
                        if comparison_key not in code_comparisons_with_suggestions:
                            code_comparisons_with_suggestions[comparison_key] = []
                        code_comparisons_with_suggestions[comparison_key].append(suggestion)

    # compute similarity scores for all comparisons at once
    sim_computer = CodeSimilarityComputer()
    for code1, code2 in code_comparisons_with_suggestions:
        sim_computer.add_comparison(code1, code2)
    logger.debug("Computing similarity scores for %d code comparisons", len(code_comparisons_with_suggestions))
    sim_computer.compute_similarity_scores()  # compute all at once, enables vectorization

    # create suggestions
    suggestions: List[Feedback] = []
    for (code1, code2), suggestions_for_comparison in code_comparisons_with_suggestions.items():
        similarity = sim_computer.get_similarity_score(code1, code2)
        if similarity.f1 >= SIMILARITY_SCORE_THRESHOLD:
            # found similar code -> create feedback suggestion
            logger.info("Found similar code with similarity score %s: %s", similarity.f1, suggestions_for_comparison)
            for suggestion_to_give in suggestions_for_comparison:
                # add meta information for debugging
                suggestion_to_give.meta["precision_score"] = similarity.precision
                suggestion_to_give.meta["recall_score"] = similarity.recall
                suggestion_to_give.meta["similarity_score"] = similarity.f1
                suggestion_to_give.meta["similarity_score_f3"] = similarity.f3
                # add to suggestions
                suggestions.append(suggestion_to_give)

    return suggestions
