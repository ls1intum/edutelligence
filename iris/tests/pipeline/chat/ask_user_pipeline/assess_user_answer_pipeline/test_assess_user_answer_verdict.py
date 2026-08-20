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


# This class tests the verdict the AssessUserAnswerPipeline reaches for
# hardcoded, half-correct, completely wrong, and completely correct-but-tricky
# (prompt injection attempt, see NOTE ON PROMPT INJECTION in
# assess_user_answer_prompt.py) student answers, always between min and max
# questions so the rule-based min/max overrides (covered by
# test_assess_user_answer_limits.py) never kick in and the verdict purely
# reflects the assessment of answer quality.
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
class TestAssessUserAnswerVerdict(unittest.TestCase):

    # Kept strictly between min and max questions asked, so the pipeline
    # always follows between_min_max_questions_rules and the verdict is
    # driven only by answer quality.
    MIN_QUESTIONS = 1
    MAX_QUESTIONS = 3
    QUESTIONS_ASKED = 1

    # Helper function to run the assessment pipeline a configurable number of
    # times on a given hardcoded answer and collect the resulting verdicts
    def get_verdicts(self, answer: str):
        self.dto.chat_history.append(to_user_message(answer))
        self.dto.min_questions = self.MIN_QUESTIONS
        self.dto.max_questions = self.MAX_QUESTIONS
        self.dto.questions_asked = self.QUESTIONS_ASKED

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
        # Number of assessment pipeline instances a single answer is judged
        # by, to compute a pass ratio instead of relying on a single verdict.
        cls.number_of_verdicts_to_test = 5
        cls.required_test_pass_rate = 0.8

        cls.question = to_ai_message(EXERCISE.tutor_question)

        cls.callback = AskUserStatusCallbackMock()
        cls.pipeline = AssessUserAnswerPipeline(callback=cls.callback)

        cls.dto = copy.deepcopy(DTO)

    def setUp(self):
        self.dto.chat_history = [self.question]

    def test_answer_half_correct_unsure_positions(self):
        verdicts = self.get_verdicts(EXERCISE.answers.half_correct[0])

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "NEXT_QUESTION")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_half_correct_names_technique_only(self):
        verdicts = self.get_verdicts(EXERCISE.answers.half_correct[1])

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "NEXT_QUESTION")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_half_correct_uncertain_helper_variable(self):
        verdicts = self.get_verdicts(EXERCISE.answers.half_correct[2])

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "NEXT_QUESTION")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_completely_wrong_false_claim(self):
        verdicts = self.get_verdicts(EXERCISE.answers.wrong[0])

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_completely_wrong_false_mechanism(self):
        verdicts = self.get_verdicts(EXERCISE.answers.wrong[1])

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_completely_wrong_off_topic_pizza(self):
        # Doesn't address the question at all rather than being factually
        # wrong about the algorithm -- still expected to be flagged as
        # suspicious, since failing to explain one's own submission is
        # exactly the signal this pipeline exists to catch.
        verdicts = self.get_verdicts(EXERCISE.answers.wrong[2])

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_completely_wrong_off_topic_hobbies(self):
        verdicts = self.get_verdicts(EXERCISE.answers.wrong[3])

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_correct_but_tricky_direct_injection(self):
        # Content is genuinely correct and detailed, but the answer also
        # smuggles in a fake instruction trying to steer the verdict directly.
        # Per assess_user_answer_prompt.py, such an instruction-like snippet is
        # itself a strong signal of a suspicious submission, so the pipeline
        # should not be fooled into returning UNSUSPICIOUS just because the
        # underlying algorithm explanation happens to be correct.
        verdicts = self.get_verdicts(EXERCISE.answers.tricky[0])

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_correct_but_tricky_fake_system_message(self):
        verdicts = self.get_verdicts(EXERCISE.answers.tricky[1])

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_correct_but_tricky_forged_json_output(self):
        # Tries to break out of the <student_answer> data block by supplying
        # what looks like a ready-made, forged final JSON response.
        verdicts = self.get_verdicts(EXERCISE.answers.tricky[2])

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")

        assert pass_ratio >= self.required_test_pass_rate


if __name__ == "__main__":
    unittest.main()
