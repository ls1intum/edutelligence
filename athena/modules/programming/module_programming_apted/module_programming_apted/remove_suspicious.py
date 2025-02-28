""" Like in ThemisML, the following problems with the suggestions exist, thats why the filter_suspicious method is needed:
(1) Sometimes, there was a feedback on something banal like a getter, which was actually meant for another method.
    This caused suggestions for almost all the other submissions, which were not helpful.
    We therefore classify a suggestion as "suspicious" if it affects too many other submissions (> 10% and > 2).
(2) However, this would also sometimes classify a suggestion as suspicious if it is actually helpful.
    Therefore, we make a suggestion non-supicious if there are at least 3 other suggestions for the same method.
    This makes a mistake like described above unlikely.
(3) Suggestions are also non-suspicious if they include words that hint at other parts of the code, like
    "again", "consequential error", "previous", "later", "earlier", "above", "below" and German equivalents of these words.
"""

from typing import Dict, List, cast

from athena.programming import Feedback


def filter_suspicious(suggestions: List[Feedback], n_submissions: int) -> List[Feedback]:
    """
    Filters out suspicious suggestions we don't want to suggest to tutors.
    suggestions: List of suggestions to filter
    n_submissions: Number of submissions for the exercise
    """
    suspicious: Dict[int, bool] = {}  # feedback id: is suspicious
    # (1) classify suggestions as suspicious if they affect too many other submissions
    for suggestion in suggestions:
        n_feedback_suggestions = suggestion.meta.get("n_feedback_suggestions", 999999)
        if n_feedback_suggestions > 2 and n_feedback_suggestions > 0.1 * n_submissions:
            suspicious[cast(int, suggestion.id)] = True
        # find all other suggestions for the same method
        other_suggestions: List[Feedback] = []
        for other_suggestion in suggestions:
            if other_suggestion.id == suggestion.id:
                continue
            if other_suggestion.file_path == suggestion.file_path and other_suggestion.meta.get("method_name") == suggestion.meta.get("method_name"):
                other_suggestions.append(other_suggestion)
        # (2) make suggestion non-suspicious if there are at least 3 other suggestions for the same method
        if len(other_suggestions) >= 3:
            suspicious[cast(int, suggestion.id)] = False
    # (3) classify suggestions as suspicious if they include words that hint at other parts of the code
    suspicious_words = ["again", "consequential error", "previous", "later", "earlier", "above", "below"]
    for suggestion in suggestions:
        for word in suspicious_words:
            if word in str(suggestion.description):
                suspicious[cast(int, suggestion.id)] = True
    # filter out suspicious suggestions
    return list(filter(lambda s: not suspicious.get(cast(int, s.id), False), suggestions))
