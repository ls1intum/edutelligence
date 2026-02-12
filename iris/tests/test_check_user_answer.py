"""
import unittest

from TestCallback import TestPromptUserStatusCallback
from rasutil import TestCallback

from .test_data import TASK_SORTING, CODE_SORTING, TEMPLATE_SORTING
from iris.pipeline.chat.assess_user_answer_pipeline import AssessUserAnswerPipeline


class TestCheckUserAnswer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.task = TASK_SORTING
        cls.template = TEMPLATE_SORTING
        cls.code = CODE_SORTING
        cls.question = "How is the swap of two elements implemented in your implementation of the bubble sort algorithm?"

        cls.callback = TestPromptUserStatusCallback()

        cls.pipeline = AssessUserAnswerPipeline(callback = cls.callback)



    def test_answer_sufficient_1(self):
        answer = "I swap the two elements using a temporary variable."
        # TODO: translate answer string(s) to chat_history with help function for every test case
        # TODO: set min_questions and max_questions appropriately for every test case (also adapt test names to hint whether e.g. answer is sufficient/insufficient/follow-up_needed because of question limit or answer itself)
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=, max_questions=)
        # self.assertTrue(assess_user_answer(task, code, question, answer))

    def test_answer_sufficient_2(self):
        answer = "I store arr[j] in temp, then assign arr[j] = arr[j+1], and finally set arr[j+1] = temp."
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=, max_questions=)

        # self.assertTrue(assess_user_answer(task, code, question, answer))


    def test_answer_insufficient_1(self):
        answer = "The compiler handles the swap automatically."
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=, max_questions=)

        # self.assertFalse(assess_user_answer(task, code, question, answer))

    def test_answer_insufficient_2(self):
        answer = "I just loop through the array, so the swap happens on its own."
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=, max_questions=)

        # self.assertFalse(assess_user_answer(task, code, question, answer))


    def test_partial_answer_1(self):
        answer = "I swap the contents of 2 variables."
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=, max_questions=)

        # self.assertFalse(assess_user_answer(task, code, question, answer))

    def test_partial_answer_2(self):
        answer = "Do you want to know the code snippet where this happens?"
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=, max_questions=)

        # self.assertFalse(assess_user_answer(task, code, question, answer))


    def test_follow_up_answer_sufficient(self):
        first_answer = "I swap the contents of 2 variables."
        second_question = "Please go more into detail. How did you do it?"
        second_answer = "I swap the two elements using a temporary variable."
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=, max_questions=)

        # self.assertFalse(assess_user_follow_up_answer(task, code, first_question, first_answer, second_question, second_answer))

    def test_follow_up_answer_insufficient(self):
        first_answer = "I swap the contents of 2 variables."
        second_question = "Please go more into detail. How did you do it?"
        second_answer = "The compiler handles the swap automatically."
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=, max_questions=)

        # self.assertFalse(assess_user_follow_up_answer(task, code, first_question, first_answer, second_question, second_answer))


if __name__ == "__main__":
    unittest.main()

"""