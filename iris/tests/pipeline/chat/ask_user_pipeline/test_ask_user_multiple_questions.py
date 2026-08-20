import copy
import logging
import unittest

import pytest

from iris.pipeline.chat.ask_user_pipeline import AskUserPipeline
from tests.pipeline.chat.ask_user_pipeline.helper.assess_user_answer_pipeline_mock import (
    AssessUserAnswerPipelineMock,
)
from tests.pipeline.chat.ask_user_pipeline.helper.helper import (
    extract_keywords,
    get_pass_ratio,
    get_pyris_message,
    llm_evaluate,
)
from tests.pipeline.chat.ask_user_pipeline.helper.test_callback import (
    AskUserStatusCallbackMock,
)
from tests.pipeline.chat.ask_user_pipeline.helper.test_data import (
    DTO,
    EXERCISE,
    FIRST_MESSAGE_TIME,
    LLM_REPEATING_TOPICS_PROMPT,
    USER_ANSWER,
    VARIANT,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# This class tests the relation of multiple generated questions within one session.
#
# Marked "integration" and excluded from the default pytest run (see the
# addopts/markers config in pyproject.toml): setUpClass below drives the real
# AskUserPipeline, which invokes the LLMs configured in llm_config.yml, and
# test_LLM_repeating_topics invokes another LLM to judge the results. Those
# executions invoke configured LLMs and therefore make the default suite
# depend on external credentials/network access, incur model usage, and fail
# in the clean CI configuration whose example model entries have no API
# keys. Run explicitly with `pytest -m integration`.
@pytest.mark.integration
class TestAskUserMultipleQuestions(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        number_of_tests = 5
        number_of_questions_per_test = 3
        cls.required_test_pass_rate = 0.8

        cls.task = EXERCISE.task
        cls.template = EXERCISE.template
        cls.code = EXERCISE.code

        # This monkeypatch replaces the AssessUserAnswerPipeline with a mock that always assesses
        # the answer as too vague (NEXT_QUESTION is returned)
        import iris.pipeline.chat.ask_user_pipeline as pipeline_module

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            pipeline_module, "AssessUserAnswerPipeline", AssessUserAnswerPipelineMock
        )

        cls._monkeypatch = monkeypatch

        cls.template_concatenated = "\n".join(cls.template.values())
        cls.code_concatenated = "\n".join(cls.code.values())

        cls.keywords_code = extract_keywords(
            cls.template_concatenated, cls.code_concatenated
        )
        cls.keywords_task = extract_keywords(cls.template_concatenated, cls.task)

        pipeline = AskUserPipeline()

        cls.dto = copy.deepcopy(DTO)
        cls.message_time = FIRST_MESSAGE_TIME

        cls.questions_all_tests = []

        for _ in range(number_of_tests):

            callback = AskUserStatusCallbackMock()
            pipeline(cls.dto, VARIANT, callback, event="FIRST_QUESTION")

            cls.dto.chat_history = [get_pyris_message(0, False, callback.final_result)]
            cls.dto.chat_history.append(get_pyris_message(1, True, USER_ANSWER))

            for j in range(1, number_of_questions_per_test):
                callback = AskUserStatusCallbackMock()
                pipeline(cls.dto, VARIANT, callback, event=None)
                cls.dto.chat_history.append(
                    get_pyris_message(j * 2, False, callback.final_result)
                )
                cls.dto.chat_history.append(
                    get_pyris_message(j * 2 + 1, True, USER_ANSWER)
                )

            questions = "\n---\n".join(
                content.text_content
                for j, message in enumerate(cls.dto.chat_history)
                if j % 2 == 0
                for content in message.contents
            )

            cls.questions_all_tests.append(questions)

            print("Pipeline results:")
            print(questions)

    @classmethod
    def tearDownClass(cls):
        cls._monkeypatch.undo()

    def test_LLM_repeating_topics(self):
        # required voting result for a question
        required_voting_result = 0.8
        # number of LLM instances to evaluate questions
        instances = 1

        pass_ratio = get_pass_ratio(
            self.questions_all_tests,
            lambda q: llm_evaluate(
                LLM_REPEATING_TOPICS_PROMPT,
                instances,
                q,
                self.task,
                self.template_concatenated,
                self.code_concatenated,
            )
            >= required_voting_result,
        )

        assert pass_ratio >= self.required_test_pass_rate


if __name__ == "__main__":
    unittest.main()
