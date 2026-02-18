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

# Helper function to convert string into PyrisMessage object sent by AI
def to_ai_message(message: str):
    return PyrisAIMessage(
        sentAt=datetime.datetime(2026, 1, 10),
        contents=[
            MessageContentDto(text=message)
        ],
        toolCalls=None
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
                contents=[MessageContentDto(text=self.question)], # TODO: fix type error
                toolCalls=None
            )
        ]

        self.callback = TestPromptUserStatusCallback()
        self.pipeline = AssessUserAnswerPipeline(callback = self.callback)


    # TODO: find test cases where between min max always returns follow_up_question (find a type of answer which forces follow-up question but not clarify)
    # TODO: find test cases where between min max always returns suspicious/unsuspicious (find a types of answers which forces this)
    # TODO: if both worked delete test cases where both results are correct (those are redundant now)


    def test_answer_correct_between_min_max(self):
        self.chat_history.append(to_user_message("I swap the two elements using a temporary variable."))

        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=2, questions_asked=1)

        self.assertTrue(self.callback.final_result.__contains__("\"verdict\": \"unsuspicious\"") or
                        self.callback.final_result.__contains__("\"verdict\": \"follow_up_question\""))

    def test_answer_wrong_between_min_max(self):
        self.chat_history.append(to_user_message("The compiler handles the swap automatically."))

        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=2, questions_asked=1)

        self.assertTrue(self.callback.final_result.__contains__("\"verdict\": \"suspicious\"") or
                        self.callback.final_result.__contains__("\"verdict\": \"follow_up_question\""))


    def test_answer_correct_over_max(self):
        self.chat_history.append(to_user_message("I store arr[j] in temp, then assign arr[j] = arr[j+1], and finally set arr[j+1] = temp."))

        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        self.assertTrue(self.callback.final_result.__contains__("\"verdict\": \"unsuspicious\""))

    def test_answer_wrong_over_max(self):
        self.chat_history.append(to_user_message("The compiler handles the swap automatically."))

        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        self.assertTrue(self.callback.final_result.__contains__("\"verdict\": \"suspicious\""))


    def test_answer_correct_under_min(self):
        self.chat_history.append(to_user_message("I store arr[j] in temp, then assign arr[j] = arr[j+1], and finally set arr[j+1] = temp."))

        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        self.assertTrue(self.callback.final_result.__contains__("\"verdict\": \"follow_up_question\""))

    def test_answer_wrong_under_min(self):
        self.chat_history.append(to_user_message("I just loop through the array, so the swap happens on its own."))

        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        self.assertTrue(self.callback.final_result.__contains__("\"verdict\": \"follow_up_question\""))



    def test_partial_answer_vague(self):
        self.chat_history.append(to_user_message("I swap the contents of 2 variables."))

        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        self.assertTrue(self.callback.final_result.__contains__("\"verdict\": \"clarify\""))

    def test_partial_answer_question(self):
        self.chat_history.append(to_user_message("Do you want to know the code snippet where this happens?"))

        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=2, questions_asked=1)

        self.assertTrue(self.callback.final_result.__contains__("\"verdict\": \"clarify\""))


    def test_clarify_answer_sufficient(self):
        self.chat_history.append(to_user_message("I swap the contents of 2 variables."))
        self.chat_history.append(to_ai_message("Please go more into detail. How did you do it?"))
        self.chat_history.append(to_user_message("I swap the two elements using a temporary variable."))

        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        self.assertTrue(self.callback.final_result.__contains__("\"verdict\": \"unsuspicious\""))

    def test_clarify_answer_insufficient(self):
        self.chat_history.append(to_user_message("I swap the contents of 2 variables."))
        self.chat_history.append(to_ai_message("Please go more into detail. How did you do it?"))
        self.chat_history.append(to_user_message("The compiler handles the swap automatically."))

        self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        self.assertTrue(self.callback.final_result.__contains__("\"verdict\": \"suspicious\""))


if __name__ == "__main__":
    unittest.main()
