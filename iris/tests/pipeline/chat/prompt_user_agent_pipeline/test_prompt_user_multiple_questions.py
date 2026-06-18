import copy
import logging
import datetime
import unittest

from pipeline.chat.prompt_user_agent_pipeline.test_data import LLM_REPEATING_TOPICS_PROMPT
from tests.pipeline.chat.prompt_user_agent_pipeline.helper import extract_keywords, get_pass_ratio, llm_evaluate
from tests.pipeline.chat.prompt_user_agent_pipeline.test_data import CODE_SORTING, TASK_SORTING, TEMPLATE_SORTING, \
    LLM_GENERATION_EVALUATION_PROMPT, DTO, VARIANT
from tests.pipeline.chat.prompt_user_agent_pipeline.test_callback import PromptUserStatusCallbackMock

from iris.pipeline.chat.prompt_user_agent_pipeline import PromptUserAgentPipeline

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# This class tests the relation of multiple generated questions within one session.
class TestPromptUserMultipleQuestions(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        number_of_tests = 3 # TODO: use this in the end to run test multiple times
        number_of_questions_to_test = 5
        cls.required_test_pass_rate = 0.8


        cls.task = TASK_SORTING
        cls.template = TEMPLATE_SORTING
        cls.code = CODE_SORTING

        cls.template_concatenated = "\n".join(cls.template.values())
        cls.code_concatenated = "\n".join(cls.code.values())

        cls.keywords_code = extract_keywords(cls.template_concatenated, cls.code_concatenated)
        cls.keywords_task = extract_keywords(cls.template_concatenated, cls.task)

        pipeline = PromptUserAgentPipeline()

        cls.questions = []

        cls.dto = copy.deepcopy(DTO) # TODO: make DTO which also takes chat_history as parameter and append generated questions one by one
        # TODO: rewrite prompt so that it gives feedback for all questions at once

        callback = PromptUserStatusCallbackMock()
        pipeline(cls.dto, VARIANT, callback, event="FIRST_QUESTION")
        cls.questions.append(callback.final_result)

        for i in range(number_of_questions_to_test - 1):
            callback = PromptUserStatusCallbackMock() # TODO: append question to chat_history somewhere here
            pipeline(cls.dto, VARIANT, callback, event="NEXT_QUESTION")
            cls.questions.append(callback.final_result)

        logger.info("Pipeline results:")
        logger.info("\n".join(cls.questions))


    def test_LLM_repeating_topics(self):
        # required voting result for a question
        required_voting_result = 0.8
        # number of LLM instances to evaluate questions
        instances = 5

        # TODO: adapt this
        pass_ratio = get_pass_ratio(self.questions,
                                    lambda q: llm_evaluate(LLM_REPEATING_TOPICS_PROMPT, instances, q, self.task,
                                                           self.template_concatenated, self.code_concatenated) >= required_voting_result)

        assert pass_ratio >= self.required_test_pass_rate


if __name__ == "__main__":
    unittest.main()
