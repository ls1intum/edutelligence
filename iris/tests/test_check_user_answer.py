import datetime
import unittest

from TestCallback import TestPromptUserStatusCallback
from iris.common.pyris_message import PyrisMessage, IrisMessageRole, PyrisAIMessage
from typing import List

from iris.domain.data.message_content_dto import MessageContentDto

from .test_data import TASK_SORTING, CODE_SORTING, TEMPLATE_SORTING
from iris.pipeline.chat.assess_user_answer_pipeline import AssessUserAnswerPipeline


# Helper function to convert string into PyrisMessage object sent by USER
def to_user_message(message: str):
    return PyrisMessage(
        sender=IrisMessageRole.USER,
        sentAt=datetime.datetime(2026, 1, 10),
        contents=[
            MessageContentDto(text=message)
        ]
    )


class TestCheckUserAnswer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.task = TASK_SORTING
        cls.template = TEMPLATE_SORTING
        cls.code = CODE_SORTING
        cls.question = "How is the swap of two elements implemented in your implementation of the bubble sort algorithm?"


    def setUp(self):
        self.chat_history: List[PyrisMessage] = [
            PyrisAIMessage(
                sentAt=datetime.datetime(2026, 1, 10),
                contents=[MessageContentDto(text=self.question)],
                toolCalls=None
            )
        ]

        self.callback = TestPromptUserStatusCallback()
        self.pipeline = AssessUserAnswerPipeline(callback = self.callback)



    def test_answer_sufficient_between_min_max(self):
        self.chat_history.append(to_user_message("I swap the two elements using a temporary variable."))

        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=2, questions_asked=1)
        # self.assertTrue(assess_user_answer(task, code, question, answer))

    def test_answer_sufficient_over_max(self):
        answer = "I store arr[j] in temp, then assign arr[j] = arr[j+1], and finally set arr[j+1] = temp."
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        # self.assertTrue(assess_user_answer(task, code, question, answer))


    def test_answer_insufficient_between_min_max(self):
        answer = "The compiler handles the swap automatically."
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=1, max_questions=2, questions_asked=1)

        # self.assertFalse(assess_user_answer(task, code, question, answer))

    def test_answer_insufficient_under_min(self):
        answer = "I just loop through the array, so the swap happens on its own."
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        # self.assertFalse(assess_user_answer(task, code, question, answer))


    def test_partial_answer_vague(self):
        answer = "I swap the contents of 2 variables."
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        # self.assertFalse(assess_user_answer(task, code, question, answer))

    def test_partial_answer_question(self):
        answer = "Do you want to know the code snippet where this happens?"
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=1, max_questions=2, questions_asked=1)

        # self.assertFalse(assess_user_answer(task, code, question, answer))


    def test_follow_up_answer_sufficient(self):
        first_answer = "I swap the contents of 2 variables."
        second_question = "Please go more into detail. How did you do it?"
        second_answer = "I swap the two elements using a temporary variable."
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        # self.assertFalse(assess_user_follow_up_answer(task, code, first_question, first_answer, second_question, second_answer))

    def test_follow_up_answer_insufficient(self):
        first_answer = "I swap the contents of 2 variables."
        second_question = "Please go more into detail. How did you do it?"
        second_answer = "The compiler handles the swap automatically."
        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        # self.assertFalse(assess_user_follow_up_answer(task, code, first_question, first_answer, second_question, second_answer))


if __name__ == "__main__":
    unittest.main()
