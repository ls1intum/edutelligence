import copy
import json
import logging
import unittest

import pytest

from iris.pipeline.chat.assess_user_answer_pipeline import AssessUserAnswerPipeline
from tests.pipeline.chat.ask_user_pipeline.helper.helper import (
    get_pass_ratio,
    to_ai_message,
    to_user_message,
)
from tests.pipeline.chat.ask_user_pipeline.helper.test_callback import (
    AskUserStatusCallbackMock,
)
from tests.pipeline.chat.ask_user_pipeline.helper.test_data import DTO, EXERCISE

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# This class tests the decision process of assessing a student's answer to a given question with different question limits.
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

        logger.info("Pipeline results:")
        logger.info("\n".join(str(v) for v in verdicts))

        return verdicts

    @classmethod
    def setUpClass(cls):
        cls.number_of_verdicts_to_test = 5
        cls.required_test_pass_rate = 0.8

        cls.question = to_ai_message(EXERCISE.tutor_question)

        cls.callback = AskUserStatusCallbackMock()
        cls.pipeline = AssessUserAnswerPipeline(callback=cls.callback)

        cls.dto = copy.deepcopy(DTO)

    def setUp(self):
        self.dto.chat_history = [self.question]

    def test_answer_correct_between_min_max(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.correct,
            min_questions=1,
            max_questions=2,
            questions_asked=1,
        )

        print(verdicts)

        pass_ratio = get_pass_ratio(verdicts, lambda v: v in ("NEXT_QUESTION", "UNSUSPICIOUS"))

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_wrong_between_min_max(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.wrong[0],
            min_questions=1,
            max_questions=2,
            questions_asked=1,
        )

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_vague_between_min_max(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.half_correct[-1],
            min_questions=1,
            max_questions=2,
            questions_asked=1,
        )

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "NEXT_QUESTION")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_correct_over_max(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.correct,
            min_questions=1,
            max_questions=1,
            questions_asked=1,
        )

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "UNSUSPICIOUS")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_wrong_over_max(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.wrong[0],
            min_questions=1,
            max_questions=1,
            questions_asked=1,
        )

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_vague_over_max(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.half_correct[-1],
            min_questions=1,
            max_questions=1,
            questions_asked=1,
        )

        pass_ratio = get_pass_ratio(
            verdicts, lambda v: v in ("SUSPICIOUS", "UNSUSPICIOUS")
        )

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_correct_under_min(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.correct,
            min_questions=2,
            max_questions=2,
            questions_asked=1,
        )

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "NEXT_QUESTION")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_wrong_under_min(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.wrong[0],
            min_questions=2,
            max_questions=2,
            questions_asked=1,
        )

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "NEXT_QUESTION")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_vague_under_min(self):
        verdicts = self.get_verdicts(
            EXERCISE.answers.half_correct[-1],
            min_questions=2,
            max_questions=2,
            questions_asked=1,
        )

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "NEXT_QUESTION")

        assert pass_ratio >= self.required_test_pass_rate


if __name__ == "__main__":
    unittest.main()
