import copy
import unittest

import pytest

from iris.pipeline.chat.ask_user_pipeline import AskUserPipeline
from tests.pipeline.chat.ask_user_pipeline.helper.helper import (
    get_pass_ratio,
    llm_majority_vote,
)
from tests.pipeline.chat.ask_user_pipeline.helper.logging_utils import (
    ENABLE_MANUAL_ANNOTATION_LOGGING,
    ResultLog,
    exercise_slug,
)
from tests.pipeline.chat.ask_user_pipeline.helper.test_callback import (
    AskUserStatusCallbackMock,
)
from tests.pipeline.chat.ask_user_pipeline.helper.test_data import (
    DTO,
    EXERCISE,
    LLM_GENERATION_EVALUATION_PROMPT,
    VARIANT,
)

# This class tests the quality of the question generation.
# It assumes the case where the student just started the assessment mode and is asked the first question.
# Note: Feedback of submission is not part of test inputs, could be interesting to check if
# generated questions are only about correct parts of submission.
# For this to happen, ResultDTO literal in DTO would have to be extended with feedback and the
# test data with a test repository and evaluation prompt would have to check if questions are
# only about tested code.
#
# Marked "integration" and excluded from the default pytest run (see the
# addopts/markers config in pyproject.toml): setUpClass below drives the real
# AskUserPipeline, which invokes the LLMs configured in llm_config.yml, and
# also runs the LLM-as-a-judge evaluation of every generated question. Those
# executions invoke configured LLMs and therefore make the default suite
# depend on external credentials/network access, incur model usage, and fail
# in the clean CI configuration whose example model entries have no API
# keys. Run explicitly with `pytest -m integration`.
@pytest.mark.integration
class TestAskUserFirstQuestion(unittest.TestCase):

    # Deterministic (non-LLM) checks a generated question must pass
    @classmethod
    def _deterministic_checks(cls):
        return [
            ("not_too_easy", cls._is_not_too_easy),
            ("not_too_difficult_length", lambda q: len(q) < cls.max_length),
            ("requires_reasonable_answer", cls._requires_reasonable_answer),
            ("single_concept_focus", cls._is_single_concept_focus),
        ]

    @staticmethod
    def _is_not_too_easy(q: str) -> bool:
        min_length = 20
        difficulty_words = [
            "why",
            "how",
            "what",
            "explain",
            "describe",
            "elaborate",
            "tell",
        ]
        return len(q) > min_length and any(w in q.lower() for w in difficulty_words)

    @staticmethod
    def _requires_reasonable_answer(q: str) -> bool:
        forbidden_phrases = [
            "in detail",
            "every step",
            "all steps",
            "list all",
            "explain every",
            "thoroughly",
            "explain all",
            "explain fully",
            "full explanation",
        ]
        return not any(p in q.lower() for p in forbidden_phrases)

    @staticmethod
    def _is_single_concept_focus(q: str) -> bool:
        key_terms = [
            "swap",
            "loop",
            "runtime",
            "complexity",
            "array",
            "sorting",
            "comparison",
            "iteration",
            "index",
            "element",
            "order",
            "ascending",
            "descending",
            "efficiency",
            "pass",
            "algorithm",
            "step",
            "position",
            "largest",
            "smallest",
            "temporary",
            "variable",
            "condition",
            "function",
            "class",
            "object",
            "recursion",
            "base case",
            "edge case",
            "input",
            "output",
            "pointer",
            "memory",
            "data",
            "structure",
        ]
        max_allowed_terms = 4
        return sum(1 for k in key_terms if k in q.lower()) <= max_allowed_terms

    @classmethod
    def setUpClass(cls):
        # 20 questions per exercise
        number_of_questions_to_test = 20
        cls.required_test_pass_rate = 0.9
        # Judge instances per question -- majority vote of 3
        cls.judge_instances = 3
        cls.max_length = 200

        cls.task = EXERCISE.task
        cls.template = EXERCISE.template
        cls.code = EXERCISE.code

        cls.template_concatenated = "\n".join(cls.template.values())
        cls.code_concatenated = "\n".join(cls.code.values())

        pipeline = AskUserPipeline()

        cls.questions = []

        cls.dto = copy.deepcopy(DTO)

        for i in range(number_of_questions_to_test):
            callback = AskUserStatusCallbackMock()
            pipeline(cls.dto, VARIANT, callback, event="FIRST_QUESTION")
            cls.questions.append(callback.final_result)

        slug = exercise_slug(EXERCISE.title)

        # Containing only the question text, so manual annotation can happen
        # without seeing the verdicts and without being biased by them. Gated
        # by its own flag (default off) so a normal test run doesn't produce
        # a file meant for a dedicated manual-annotation pass.
        if ENABLE_MANUAL_ANNOTATION_LOGGING:
            annotation_log = ResultLog(
                f"TestAskUserFirstQuestion_{slug}_annotation.csv", ["ID", "Question"]
            )
            for i, question in enumerate(cls.questions, start=1):
                annotation_log.append_row([f"Q{i:02d}", question])

        checks = cls._deterministic_checks()

        # Precomputed once here (rather than inside the individual test_*
        # methods) so every question is judged exactly `judge_instances`
        # times regardless of test execution order, and so the full result
        # table can be written even if an individual assertion fails.
        cls.deterministic_results = []
        cls.judge_results = []

        results_log = ResultLog(
            f"TestAskUserFirstQuestion_{slug}.csv",
            ["ID", "Question", "C", "J", "Reason_J"],
        )

        for i, question in enumerate(cls.questions, start=1):
            failed_checks = [name for name, fn in checks if not fn(question)]
            deterministic_pass = len(failed_checks) == 0
            cls.deterministic_results.append(
                {"pass": deterministic_pass, "failed": failed_checks}
            )

            majority_pass, reason = llm_majority_vote(
                LLM_GENERATION_EVALUATION_PROMPT,
                cls.judge_instances,
                question,
                cls.task,
                cls.template_concatenated,
                cls.code_concatenated,
            )
            cls.judge_results.append({"pass": majority_pass, "reason": reason})

            c_cell = "pass" if deterministic_pass else f"fail: {', '.join(failed_checks)}"
            j_cell = "pass" if majority_pass else "fail"
            reason_j_cell = "" if majority_pass else reason

            results_log.append_row(
                [f"Q{i:02d}", question, c_cell, j_cell, reason_j_cell]
            )

    def test_question_not_too_easy(self):
        pass_ratio = get_pass_ratio(self.questions, self._is_not_too_easy)

        assert pass_ratio >= self.required_test_pass_rate

    def test_question_not_too_difficult_length(self):
        pass_ratio = get_pass_ratio(
            self.questions, lambda q: len(q) < self.max_length
        )

        assert pass_ratio >= self.required_test_pass_rate

    def test_question_requires_reasonable_answer(self):
        pass_ratio = get_pass_ratio(self.questions, self._requires_reasonable_answer)

        assert pass_ratio >= self.required_test_pass_rate

    def test_question_single_concept_focus(self):
        pass_ratio = get_pass_ratio(self.questions, self._is_single_concept_focus)

        assert pass_ratio >= self.required_test_pass_rate

    def test_LLM_evaluation(self):
        pass_ratio = get_pass_ratio(
            self.judge_results, lambda r: r["pass"]
        )

        assert pass_ratio >= self.required_test_pass_rate


if __name__ == "__main__":
    unittest.main()
