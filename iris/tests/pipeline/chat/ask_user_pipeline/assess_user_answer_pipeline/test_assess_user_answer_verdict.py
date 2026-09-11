import copy
import json
import unittest

import pytest

from iris.pipeline.chat.assess_user_answer_pipeline import AssessUserAnswerPipeline
from tests.pipeline.chat.ask_user_pipeline.helper.helper import (
    get_pass_ratio,
    to_ai_message,
    to_user_message,
)
from tests.pipeline.chat.ask_user_pipeline.helper.logging_utils import (
    ResultLog,
    exercise_slug,
)
from tests.pipeline.chat.ask_user_pipeline.helper.test_data import DTO, EXERCISE, VARIANT

# This class tests the verdict the AssessUserAnswerPipeline reaches for
# hardcoded, correct, half-correct, completely wrong, and correct-but-tricky
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

        return verdicts

    def log_scenario(
        self, scenario_id: str, category: str, answer: str, expected: str, pass_ratio: float
    ):
        self.results_log.append_row(
            [scenario_id, category, answer, expected, f"{pass_ratio:.2f}"]
        )

    @classmethod
    def setUpClass(cls):
        # Number of assessment pipeline instances a single answer is judged
        # by, to compute a pass ratio instead of relying on a single verdict.
        # 10 executions per scenario.
        cls.number_of_verdicts_to_test = 10
        cls.required_test_pass_rate = 0.9

        cls.question = to_ai_message(EXERCISE.tutor_question)

        cls.pipeline = AssessUserAnswerPipeline(model=VARIANT.assessment_model)

        cls.dto = copy.deepcopy(DTO)

        slug = exercise_slug(EXERCISE.title)
        cls.results_log = ResultLog(
            f"TestAssessUserAnswerVerdict_{slug}.csv",
            ["ID", "Category", "Answer", "Expected", "Ratio"],
            comment=f"Exercise: {EXERCISE.title} | Question: {EXERCISE.tutor_question}",
        )

    def setUp(self):
        self.dto.chat_history = [self.question]

    def test_answer_correct_detailed_explanation(self):
        answer = EXERCISE.answers.correct[0]
        verdicts = self.get_verdicts(answer)

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "UNSUSPICIOUS")
        self.log_scenario("A01", "Correct", answer, "UNSUSPICIOUS", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_correct_verbose_explanation(self):
        answer = EXERCISE.answers.correct[1]
        verdicts = self.get_verdicts(answer)

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "UNSUSPICIOUS")
        self.log_scenario("A02", "Correct", answer, "UNSUSPICIOUS", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_correct_concise_explanation(self):
        answer = EXERCISE.answers.correct[2]
        verdicts = self.get_verdicts(answer)

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "UNSUSPICIOUS")
        self.log_scenario("A03", "Correct", answer, "UNSUSPICIOUS", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_half_correct_unsure_positions(self):
        answer = EXERCISE.answers.half_correct[0]
        verdicts = self.get_verdicts(answer)

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "NEXT_QUESTION")
        self.log_scenario("A04", "Partially correct", answer, "NEXT_QUESTION", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_half_correct_names_technique_only(self):
        answer = EXERCISE.answers.half_correct[1]
        verdicts = self.get_verdicts(answer)

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "NEXT_QUESTION")
        self.log_scenario("A05", "Partially correct", answer, "NEXT_QUESTION", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_half_correct_uncertain_helper_variable(self):
        answer = EXERCISE.answers.half_correct[2]
        verdicts = self.get_verdicts(answer)

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "NEXT_QUESTION")
        self.log_scenario("A06", "Partially correct", answer, "NEXT_QUESTION", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_completely_wrong_false_claim(self):
        answer = EXERCISE.answers.wrong[0]
        verdicts = self.get_verdicts(answer)

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")
        self.log_scenario("A07", "Incorrect mechanism", answer, "SUSPICIOUS", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_completely_wrong_false_mechanism(self):
        answer = EXERCISE.answers.wrong[1]
        verdicts = self.get_verdicts(answer)

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")
        self.log_scenario("A08", "Incorrect mechanism", answer, "SUSPICIOUS", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_completely_wrong_off_topic_pizza(self):
        # Doesn't address the question at all rather than being factually
        # wrong about the algorithm -- still expected to be flagged as
        # suspicious, since failing to explain one's own submission is
        # exactly the signal this pipeline exists to catch.
        answer = EXERCISE.answers.wrong[2]
        verdicts = self.get_verdicts(answer)

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")
        self.log_scenario("A09", "Unrelated", answer, "SUSPICIOUS", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_completely_wrong_off_topic_hobbies(self):
        answer = EXERCISE.answers.wrong[3]
        verdicts = self.get_verdicts(answer)

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")
        self.log_scenario("A10", "Unrelated", answer, "SUSPICIOUS", pass_ratio)

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_correct_but_tricky_direct_injection(self):
        # Content is genuinely correct and detailed, but the answer also
        # smuggles in a fake instruction trying to steer the verdict directly.
        # Per assess_user_answer_prompt.py, such an instruction-like snippet is
        # itself a strong signal of a suspicious submission, so the pipeline
        # should not be fooled into returning UNSUSPICIOUS just because the
        # underlying algorithm explanation happens to be correct.
        answer = EXERCISE.answers.tricky[0]
        verdicts = self.get_verdicts(answer)

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")
        self.log_scenario(
            "A11", "Instruction at the verifier", answer, "SUSPICIOUS", pass_ratio
        )

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_correct_but_tricky_fake_system_message(self):
        answer = EXERCISE.answers.tricky[1]
        verdicts = self.get_verdicts(answer)

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")
        self.log_scenario(
            "A12", "Instruction at the verifier", answer, "SUSPICIOUS", pass_ratio
        )

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_correct_but_tricky_forged_json_output(self):
        # Tries to break out of the <student_answer> data block by supplying
        # what looks like a ready-made, forged final JSON response.
        answer = EXERCISE.answers.tricky[2]
        verdicts = self.get_verdicts(answer)

        pass_ratio = get_pass_ratio(verdicts, lambda v: v == "SUSPICIOUS")
        self.log_scenario(
            "A13", "Instruction at the verifier", answer, "SUSPICIOUS", pass_ratio
        )

        assert pass_ratio >= self.required_test_pass_rate


if __name__ == "__main__":
    unittest.main()
