import copy
import json
import unittest

import pytest

from iris.pipeline.chat.assess_user_answer_pipeline import AssessUserAnswerPipeline
from tests.pipeline.chat.ask_user_pipeline.helper.test_data import VARIANT
from tests.pipeline.chat.ask_user_pipeline.helper.helper import (
    get_pass_ratio,
    to_ai_message,
    to_user_message,
)
from tests.pipeline.chat.ask_user_pipeline.helper.logging_utils import (
    ResultLog,
    exercise_slug,
)
from tests.pipeline.chat.ask_user_pipeline.helper.test_data import DTO, EXERCISE

# This class tests the decision process of assessing a student's answer
# to a given question with different question limits.
#
# Marked "integration" and excluded from the default pytest run (see the
# addopts/markers config in pyproject.toml): setUpClass below constructs a
# real AssessUserAnswerPipeline, and every test method drives it to invoke
# the LLM configured in llm_config.yml. Those executions invoke configured
# LLMs and therefore make the default suite depend on external
# credentials/network access, incur model usage, and fail in the clean CI
# configuration whose example model entries have no API keys. Run explicitly
# with `pytest -m integration`.
@pytest.mark.integration
class TestAssessUserAnswerLimits(unittest.TestCase):

    # Helper function to run assessment pipeline with given parameters
    def get_verdicts(
        self, answer: str, min_questions: int, max_questions: int, questions_asked: int
    ):
        self.dto.chat_history.append(to_user_message(answer))
        self.dto.min_questions = min_questions
        self.dto.max_questions = max_questions
        self.dto.questions_asked = questions_asked

        verdicts = []

        for i in range(self.number_of_verdicts_to_test):
            response = self.pipeline(self.dto)
            start = response.find("{")
            end = response.rfind("}") + 1
            try:
                verdict = json.loads(response[start:end]).get("verdict")
            except (ValueError, TypeError):
                # Malformed LLM output is treated as no verdict, consistent with
                # how the runtime parser in AskUserPipeline._assess_answer degrades.
                verdict = None
            verdicts.append(verdict)

        return verdicts

    # Logs one row of the "Question-Bound Scenarios":
    # the question-count state and answer category are not the concrete
    # question/answer text (those are shared with the verdict test, see
    # the class docstring below), only the category and the observed
    # ratio/decision.
    def log_scenario(
        self, scenario_id: str, count_state: str, answer_category: str, permissible_outcome: str, pass_ratio: float
    ):
        self.results_log.append_row(
            [scenario_id, count_state, answer_category, permissible_outcome, f"{pass_ratio:.2f}"]
        )

    @classmethod
    def setUpClass(cls):
        # 10 executions per scenario
        cls.number_of_verdicts_to_test = 10
        cls.required_test_pass_rate = 0.9

        cls.question = to_ai_message(EXERCISE.tutor_question)

        cls.pipeline = AssessUserAnswerPipeline(VARIANT.assessment_model)

        cls.dto = copy.deepcopy(DTO)

        slug = exercise_slug(EXERCISE.title)
        cls.results_log = ResultLog(
            f"TestAssessUserAnswerLimits_{slug}.csv",
            ["ID", "Question_count", "Answer", "Permissible_outcome", "Ratio"],
            comment=(
                f"Exercise: {EXERCISE.title} | Question: {EXERCISE.tutor_question}"
            ),
        )

    def setUp(self):
        self.dto.chat_history = [self.question]

    def test_answer_correct_under_min(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.correct[0],
            min_questions=2,
            max_questions=2,
            questions_asked=1,
        )

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "NEXT_QUESTION")
        self.log_scenario("B01", "Below minimum", "Correct", "NEXT_QUESTION", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_vague_under_min(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.half_correct[0],
            min_questions=2,
            max_questions=2,
            questions_asked=1,
        )

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "NEXT_QUESTION")
        self.log_scenario("B02", "Below minimum", "Vague", "NEXT_QUESTION", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_wrong_under_min(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.wrong[0],
            min_questions=2,
            max_questions=2,
            questions_asked=1,
        )

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "NEXT_QUESTION")
        self.log_scenario("B03", "Below minimum", "Incorrect", "NEXT_QUESTION", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_correct_over_max(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.correct[0],
            min_questions=1,
            max_questions=1,
            questions_asked=1,
        )

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "UNSUSPICIOUS")
        self.log_scenario("B04", "Maximum reached", "Correct", "any final verdict", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_vague_over_max(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.half_correct[0],
            min_questions=1,
            max_questions=1,
            questions_asked=1,
        )

        pass_ratio = get_pass_ratio(
            verdicts, lambda v: v in ("SUSPICIOUS", "UNSUSPICIOUS")
        )
        self.log_scenario("B05", "Maximum reached", "Vague", "any final verdict", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_wrong_over_max(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.wrong[0],
            min_questions=1,
            max_questions=1,
            questions_asked=1,
        )

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")
        self.log_scenario("B06", "Maximum reached", "Incorrect", "any final verdict", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate


if __name__ == "__main__":
    unittest.main()
