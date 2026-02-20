import datetime
import unittest

from TestCallback import TestPromptUserStatusCallback
from iris.common.pyris_message import PyrisMessage, IrisMessageRole, PyrisAIMessage
from typing import List

from iris.domain.data.text_message_content_dto import TextMessageContentDTO

from .test_data import TASK_SORTING, CODE_SORTING, TEMPLATE_SORTING
from iris.pipeline.chat.assess_user_answer_pipeline import AssessUserAnswerPipeline


# Helper function to convert string into PyrisMessage object sent by USER
def to_user_message(message: str):
    return PyrisMessage(
        sender=IrisMessageRole.USER,
        sentAt=datetime.datetime(2026, 1, 10),
        contents=[
            TextMessageContentDTO(textContent=message)
        ]
    )

# Helper function to convert string into PyrisMessage object sent by AI
def to_ai_message(message: str):
    return PyrisAIMessage(
        sentAt=datetime.datetime(2026, 1, 10),
        contents=[
            TextMessageContentDTO(textContent=message)
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
                contents=[TextMessageContentDTO(textContent=self.question)],
                toolCalls=None
            )
        ]

        self.callback = TestPromptUserStatusCallback()
        self.pipeline = AssessUserAnswerPipeline(callback = self.callback)

        

    def test_answer_correct_between_min_max(self):
        self.chat_history.append(to_user_message("I store arr[j] in temp, then assign arr[j] = arr[j+1], and finally set arr[j+1] = temp."))

        result = self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=2, questions_asked=1)

        assert result.__contains__("\"verdict\": \"unsuspicious\"")

    def test_answer_wrong_between_min_max(self):
        self.chat_history.append(to_user_message("The compiler handles the swap automatically."))

        result = self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=2, questions_asked=1)

        assert result.__contains__("\"verdict\": \"suspicious\"")

    def test_answer_vague_between_min_max(self):
        self.chat_history.append(to_user_message("I follow the definition of the bubble sort algorithm."))

        result = self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=2, questions_asked=1)

        assert result.__contains__("\"verdict\": \"next_question\"")



    def test_answer_correct_over_max(self):
        self.chat_history.append(to_user_message("I store arr[j] in temp, then assign arr[j] = arr[j+1], and finally set arr[j+1] = temp."))

        result = self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        assert result.__contains__("\"verdict\": \"unsuspicious\"")

    def test_answer_wrong_over_max(self):
        self.chat_history.append(to_user_message("The compiler handles the swap automatically."))

        result = self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        assert result.__contains__("\"verdict\": \"suspicious\"")

    def test_answer_vague_over_max(self):
        self.chat_history.append(to_user_message("I follow the definition of the bubble sort algorithm."))

        result = self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=1, max_questions=1, questions_asked=1)

        assert (result.__contains__("\"verdict\": \"suspicious\"") or result.__contains__("\"verdict\": \"unsuspicious\""))



    def test_answer_correct_under_min(self):
        self.chat_history.append(to_user_message("I store arr[j] in temp, then assign arr[j] = arr[j+1], and finally set arr[j+1] = temp."))

        result = self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=2, max_questions=2, questions_asked=1)

        assert result.__contains__("\"verdict\": \"next_question\"")

    def test_answer_wrong_under_min(self):
        self.chat_history.append(to_user_message("The compiler handles the swap automatically."))

        result = self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=2, max_questions=2, questions_asked=1)

        assert result.__contains__("\"verdict\": \"next_question\"")

    def test_answer_vague_under_min(self):
        self.chat_history.append(to_user_message("I follow the definition of the bubble sort algorithm."))

        result = self.pipeline(template_repository=self.template, submission_repository=self.code, chat_history=self.chat_history, problem_statement=self.task, min_questions=2, max_questions=2, questions_asked=1)

        assert result.__contains__("\"verdict\": \"next_question\"")


if __name__ == "__main__":
    unittest.main()
