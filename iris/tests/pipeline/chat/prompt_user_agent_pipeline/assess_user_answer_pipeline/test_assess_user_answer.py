import logging
import unittest
from typing import List

from tests.pipeline.chat.prompt_user_agent_pipeline.test_callback import PromptUserStatusCallbackMock
from tests.pipeline.chat.prompt_user_agent_pipeline.helper import to_user_message, get_pass_ratio, to_ai_message
from tests.pipeline.chat.prompt_user_agent_pipeline.test_data import TASK_SORTING, CODE_SORTING, TEMPLATE_SORTING

from iris.common.pyris_message import PyrisMessage
from iris.pipeline.chat.assess_user_answer_pipeline import AssessUserAnswerPipeline

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# This class tests the decision process of assessing a student's answer to a given question.
class TestAssessUserAnswer(unittest.TestCase):

    # Helper function to run assessment pipeline with given parameters
    def get_verdicts(self, answer: str, min_questions: int, max_questions: int, questions_asked: int):
        self.chat_history.append(to_user_message(answer))

        verdicts = []

        for i in range(self.number_of_verdicts_to_test):
            verdicts.append(self.pipeline(self.template, self.code, self.chat_history, self.task,
                                          min_questions=min_questions, max_questions=max_questions, questions_asked=questions_asked))

        logger.info("Pipeline results:")
        logger.info("\n".join(verdicts))

        return verdicts


    @classmethod
    def setUpClass(cls):
        cls.number_of_verdicts_to_test = 5
        cls.required_test_pass_rate = 0.8

        cls.task = TASK_SORTING
        cls.template = TEMPLATE_SORTING
        cls.code = CODE_SORTING
        cls.question = to_ai_message("How is the swap of two elements implemented in your implementation of the bubble sort algorithm?")

        cls.callback = PromptUserStatusCallbackMock()
        cls.pipeline = AssessUserAnswerPipeline(callback = cls.callback)

    def setUp(self):
        self.chat_history: List[PyrisMessage] = [self.question]


    def test_answer_correct_between_min_max(self):
        verdicts = self.get_verdicts("I store arr[j] in temp, then assign arr[j] = arr[j+1], and finally set arr[j+1] = temp.",
                                    min_questions=1, max_questions=2, questions_asked=1)

        pass_ratio = get_pass_ratio(verdicts,
                                    lambda v: v.__contains__("\"verdict\": \"unsuspicious\""))

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_wrong_between_min_max(self):
        verdicts = self.get_verdicts("The compiler handles the swap automatically.",
                                     min_questions=1, max_questions=2, questions_asked=1)

        pass_ratio = get_pass_ratio(verdicts,
                                    lambda v: v.__contains__("\"verdict\": \"suspicious\""))

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_vague_between_min_max(self):
        verdicts = self.get_verdicts("I follow the definition of the bubble sort algorithm.",
                                     min_questions=1, max_questions=2, questions_asked=1)

        pass_ratio = get_pass_ratio(verdicts,
                                    lambda v: v.__contains__("\"verdict\": \"next_question\""))

        assert pass_ratio >= self.required_test_pass_rate



    def test_answer_correct_over_max(self):
        verdicts = self.get_verdicts("I store arr[j] in temp, then assign arr[j] = arr[j+1], and finally set arr[j+1] = temp.",
                                     min_questions=1, max_questions=1, questions_asked=1)

        pass_ratio = get_pass_ratio(verdicts,
                                    lambda v: v.__contains__("\"verdict\": \"unsuspicious\""))

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_wrong_over_max(self):
        verdicts = self.get_verdicts("The compiler handles the swap automatically.",
                                     min_questions=1, max_questions=1, questions_asked=1)

        pass_ratio = get_pass_ratio(verdicts,
                                    lambda v: v.__contains__("\"verdict\": \"suspicious\""))

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_vague_over_max(self):
        verdicts = self.get_verdicts("I follow the definition of the bubble sort algorithm.",
                                     min_questions=1, max_questions=1, questions_asked=1)

        pass_ratio = get_pass_ratio(verdicts,
                                    lambda v: v.__contains__("\"verdict\": \"suspicious\"") or v.__contains__("\"verdict\": \"unsuspicious\""))

        assert pass_ratio >= self.required_test_pass_rate



    def test_answer_correct_under_min(self):
        verdicts = self.get_verdicts("I store arr[j] in temp, then assign arr[j] = arr[j+1], and finally set arr[j+1] = temp.",
                                     min_questions=2, max_questions=2, questions_asked=1)

        pass_ratio = get_pass_ratio(verdicts,
                                    lambda v: v.__contains__("\"verdict\": \"next_question\""))

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_wrong_under_min(self):
        verdicts = self.get_verdicts("The compiler handles the swap automatically.",
                                     min_questions=2, max_questions=2, questions_asked=1)

        pass_ratio = get_pass_ratio(verdicts,
                                    lambda v: v.__contains__("\"verdict\": \"next_question\""))

        assert pass_ratio >= self.required_test_pass_rate

    def test_answer_vague_under_min(self):
        verdicts = self.get_verdicts("I follow the definition of the bubble sort algorithm.",
                                     min_questions=2, max_questions=2, questions_asked=1)

        pass_ratio = get_pass_ratio(verdicts,
                                    lambda v: v.__contains__("\"verdict\": \"next_question\""))

        assert pass_ratio >= self.required_test_pass_rate


if __name__ == "__main__":
    unittest.main()
