import copy
import logging
import unittest
import pytest

from tests.pipeline.chat.prompt_user_agent_pipeline.assess_user_answer_pipeline_mock import AssessUserAnswerPipelineMock
from tests.pipeline.chat.prompt_user_agent_pipeline.test_data import LLM_REPEATING_TOPICS_PROMPT, FIRST_MESSAGE_TIME, \
    USER_ANSWER
from tests.pipeline.chat.prompt_user_agent_pipeline.helper import extract_keywords, get_pass_ratio, llm_evaluate, \
    get_pyris_message
from tests.pipeline.chat.prompt_user_agent_pipeline.test_data import CODE_SORTING, TASK_SORTING, TEMPLATE_SORTING, \
    DTO, VARIANT
from tests.pipeline.chat.prompt_user_agent_pipeline.test_callback import PromptUserStatusCallbackMock

from iris.pipeline.chat.prompt_user_agent_pipeline import PromptUserAgentPipeline

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# This class tests the relation of multiple generated questions within one session.
class TestPromptUserMultipleQuestions(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        number_of_tests = 1
        number_of_questions_per_test = 5
        cls.required_test_pass_rate = 0.8


        cls.task = TASK_SORTING
        cls.template = TEMPLATE_SORTING
        cls.code = CODE_SORTING

        # This monkeypatch replaces the AssessUserAnswerPipeline with a mock that always assesses the answer as too vague (next_question is returned)
        import iris.pipeline.chat.prompt_user_agent_pipeline as pipeline_module
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            pipeline_module,
            "AssessUserAnswerPipeline",
            AssessUserAnswerPipelineMock
        )

        cls._monkeypatch = monkeypatch

        cls.template_concatenated = "\n".join(cls.template.values())
        cls.code_concatenated = "\n".join(cls.code.values())

        cls.keywords_code = extract_keywords(cls.template_concatenated, cls.code_concatenated)
        cls.keywords_task = extract_keywords(cls.template_concatenated, cls.task)

        pipeline = PromptUserAgentPipeline()

        cls.dto = copy.deepcopy(DTO)
        cls.message_time = FIRST_MESSAGE_TIME

        cls.questions_all_tests = []
        messages = []

        for i in range(number_of_tests):

            callback = PromptUserStatusCallbackMock()
            pipeline(cls.dto, VARIANT, callback, event="FIRST_QUESTION")

            cls.dto.chat_history = [get_pyris_message(0, False, callback.final_result)]
            cls.dto.chat_history.append(get_pyris_message(1, True, USER_ANSWER))
            messages.append(callback.final_result)
            messages.append(USER_ANSWER)

            for j in range(1, number_of_questions_per_test):
                callback = PromptUserStatusCallbackMock()
                pipeline(cls.dto, VARIANT, callback, event=None)
                cls.dto.chat_history.append(get_pyris_message(j*2, False, callback.final_result))
                cls.dto.chat_history.append(get_pyris_message(j*2 + 1, True, USER_ANSWER))
                messages.append(callback.final_result)
                messages.append(USER_ANSWER)

            questions = "\n---\n".join(
                content.text_content
                for j, message in enumerate(cls.dto.chat_history)
                if j % 2 == 0
                for content in message.contents
            )

            cls.questions_all_tests.append(questions)

            logger.info("Pipeline results:")
            logger.info(questions)

    @classmethod
    def tearDownClass(cls):
        cls._monkeypatch.undo()


    def test_LLM_repeating_topics(self):
        # required voting result for a question
        required_voting_result = 0.8
        # number of LLM instances to evaluate questions
        instances = 1

        pass_ratio = get_pass_ratio(self.questions_all_tests,
                                    lambda q: llm_evaluate(LLM_REPEATING_TOPICS_PROMPT, instances, q, self.task,
                                                           self.template_concatenated, self.code_concatenated) >= required_voting_result)

        assert pass_ratio >= self.required_test_pass_rate


if __name__ == "__main__":
    unittest.main()
