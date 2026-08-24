from dataclasses import dataclass


@dataclass(frozen=True)
class AnswerSet:
    """Hardcoded student answers for the assess_user_answer LLM tests,
    grouped by the verdict they are expected to elicit."""

    # Detailed and factually correct -> expected verdict UNSUSPICIOUS. Add as
    # many variations as useful (differing in detail/phrasing, all complete).
    correct: list[str]
    # Not factually wrong, but too vague/incomplete -> expected verdict
    # NEXT_QUESTION.
    half_correct: list[str]
    # Factually wrong, or not addressing the question at all -> expected
    # verdict SUSPICIOUS.
    wrong: list[str]
    # Factually correct content that also tries to game/inject the verdict
    # -> expected verdict SUSPICIOUS despite the correct content (see NOTE ON
    # PROMPT INJECTION in assess_user_answer_prompt.py).
    tricky: list[str]


@dataclass(frozen=True)
class Exercise:
    """Everything the ask_user/assess_user_answer LLM tests need for one
    programming exercise."""

    title: str
    programming_language: str
    task: str
    template: dict[str, str]
    code: dict[str, str]
    # The question a tutor would ask about the submission; used as the prior
    # AI turn the assess_user_answer tests grade a student answer against.
    tutor_question: str
    answers: AnswerSet
