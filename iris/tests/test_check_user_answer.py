import unittest

from .test_data import TASK_SORTING, CODE_SORTING


class TestCheckUserAnswer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.task = TASK_SORTING
        cls.code = CODE_SORTING
        cls.question = "How is the swap of two elements implemented in your implementation of the bubble sort algorithm?"



    def test_answer_sufficient_1(self):
        answer = "I swap the two elements using a temporary variable."
        # probably change assessment function signatures to input chat history instead question(s) and answer(s)
        # self.assertTrue(assess_user_answer(task, code, question, answer))

    def test_answer_sufficient_2(self):
        answer = "I store arr[j] in temp, then assign arr[j] = arr[j+1], and finally set arr[j+1] = temp."
        # self.assertTrue(assess_user_answer(task, code, question, answer))


    def test_answer_insufficient_1(self):
        answer = "The compiler handles the swap automatically."
        # self.assertFalse(assess_user_answer(task, code, question, answer))

    def test_answer_insufficient_2(self):
        answer = "I just loop through the array, so the swap happens on its own."
        # self.assertFalse(assess_user_answer(task, code, question, answer))


    def test_partial_answer_1(self):
        answer = "I swap the contents of 2 variables."
        # self.assertFalse(assess_user_answer(task, code, question, answer))

    def test_partial_answer_2(self):
        answer = "Do you want to know the code snippet where this happens?"
        # self.assertFalse(assess_user_answer(task, code, question, answer))


    def test_follow_up_answer_sufficient(self):
        first_answer = "I swap the contents of 2 variables."
        second_question = "Please go more into detail. How did you do it?"
        second_answer = "I swap the two elements using a temporary variable."
        # self.assertFalse(assess_user_follow_up_answer(task, code, first_question, first_answer, second_question, second_answer))

    def test_follow_up_answer_insufficient(self):
        first_answer = "I swap the contents of 2 variables."
        second_question = "Please go more into detail. How did you do it?"
        second_answer = "The compiler handles the swap automatically."
        # self.assertFalse(assess_user_follow_up_answer(task, code, first_question, first_answer, second_question, second_answer))


if __name__ == "__main__":
    unittest.main()