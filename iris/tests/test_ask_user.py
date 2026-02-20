import logging
import datetime
import unittest

from helper import extract_keywords, get_pass_ratio
from iris.domain.chat.prompt_user_chat.prompt_user_chat_pipeline_execution_dto import PromptUserChatPipelineExecutionDTO
from iris.domain.data.result_dto import ResultDTO
from iris.domain.data.user_dto import UserDTO
from iris.domain.variant.prompt_user_variant import PromptUserVariant
from iris.pipeline.chat.prompt_user_agent_pipeline import PromptUserAgentPipeline
from test_data import LLM_GENERATION_EVALUATION_PROMPT

from .test_data import CODE_SORTING, TASK_SORTING, TEMPLATE_SORTING
from .llm_evaluation import evaluate

from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from iris.domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from iris.domain.event.pyris_event_dto import PyrisEventDTO
from .TestCallback import TestPromptUserStatusCallback

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# This class only tests the quality of the question generation.
# It assumes the case where the student just started the assessment mode and is asked the first question.
class TestAskUser(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        number_of_questions_to_test = 3
        cls.required_test_pass_rate = 0.9


        cls.task = TASK_SORTING
        cls.template = TEMPLATE_SORTING
        cls.code = CODE_SORTING

        cls.template_concatenated = "\n".join(cls.template.values())
        cls.code_concatenated = "\n".join(cls.code.values())

        cls.keywords_code = extract_keywords(cls.template_concatenated, cls.code_concatenated)
        cls.keywords_task = extract_keywords(cls.template_concatenated, cls.task)

        # Note: Feedback of submission is not part of test inputs, could be interesting to check if generated questions are only about correct parts of submission
        # For this to happen, ResultDTO literal would have to be extended with feedback and the test data with a test repository

        dto = PromptUserChatPipelineExecutionDTO(
            submission=ProgrammingSubmissionDTO(id=1, date=datetime.datetime(2026, 1, 11), repository=cls.code, isPractice=False, buildFailed=False,
                                                latestResult=ResultDTO(completionDate=datetime.datetime(2026, 1, 10), successful=True)),
            exercise=ProgrammingExerciseDTO(id=1, name="Bubble Sort", programmingLanguage="JAVA", templateRepository=cls.template, problemStatement=cls.task),
            course=CourseDTO(id=1,name="Intro to Programming", description=None),
            eventPayload=PyrisEventDTO(eventType=None, event=None), settings=None,
            user=UserDTO(id=1, firstName="Random", lastName="User", memirisEnabled=False))

        variant = PromptUserVariant(
            variant_id="prompt_user_v1", name="Prompt User",
            description="Variant for assessing user understanding",
            agent_model="gpt-4o-mini")

        pipeline = PromptUserAgentPipeline()

        cls.questions = []

        for i in range(number_of_questions_to_test):
            callback = TestPromptUserStatusCallback()
            pipeline(dto, variant, callback, event="user_initiates_prompting")
            cls.questions.append(callback.final_result)

        logger.info("Pipeline results:")
        logger.info("\n".join(cls.questions))


    def test_question_is_thematically_relevant(self):
        # this tests if keywords of submission minus template or keywords of the problem statement minus template are part of the question

        pass_ratio = get_pass_ratio(self.questions,
                                    lambda q: any(k in q.lower() for k in self.keywords_code) or any(k in q.lower() for k in self.keywords_task))

        assert pass_ratio >= self.required_test_pass_rate


    def test_question_not_too_easy(self):
        min_length = 20
        difficulty_words = ["why", "how", "what", "explain", "describe", "elaborate", "tell"]

        pass_ratio = get_pass_ratio(self.questions,
                                    lambda q: len(q) > min_length and any(w in q.lower() for w in difficulty_words))

        assert pass_ratio >= self.required_test_pass_rate


    def test_question_not_too_difficult_length(self):
        max_length = 220

        pass_ratio = get_pass_ratio(self.questions, lambda q: len(q) < max_length)

        assert pass_ratio >= self.required_test_pass_rate


    def test_question_requires_reasonable_answer(self):
        forbidden_phrases = [
            "in detail",
            "every step",
            "all steps",
            "list all",
            "explain every",
            "thoroughly",
            "explain all",
            "explain fully",
            "full explanation"
        ]

        pass_ratio = get_pass_ratio(self.questions,
                                    lambda q: not any(p in q.lower() for p in forbidden_phrases))

        assert pass_ratio >= self.required_test_pass_rate


    def test_question_single_concept_focus(self):
        key_terms = [
            "swap", "loop", "runtime", "complexity", "array", "sorting", "comparison",
            "iteration", "index", "element", "order", "ascending", "descending",
            "efficiency", "pass", "algorithm", "step", "position", "largest", "smallest",
            "temporary", "variable", "condition", "function", "class", "object",
            "recursion", "base case", "edge case", "input", "output", "pointer",
            "memory", "data", "structure"
        ]
        max_allowed_terms = 4

        pass_ratio = get_pass_ratio(self.questions,
                                    lambda q: sum(1 for k in key_terms if k in q.lower()) <= max_allowed_terms)

        assert pass_ratio >= self.required_test_pass_rate




    def test_LLM_evaluation(self):
        # required voting result for a question
        required_voting_result = 0.9
        # number of LLM instances to evaluate a question
        instances = 5


        pass_ratio = get_pass_ratio(self.questions,
                                    lambda q: evaluate(LLM_GENERATION_EVALUATION_PROMPT, 5, q, self.task,
                                                       self.template_concatenated, self.code_concatenated) >= required_voting_result)

        assert pass_ratio >= self.required_test_pass_rate


if __name__ == "__main__":
    unittest.main()
