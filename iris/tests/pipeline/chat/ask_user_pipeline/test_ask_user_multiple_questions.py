import copy
import itertools
import unittest

import pytest

from iris.pipeline.chat.ask_user_pipeline import AskUserPipeline
from tests.pipeline.chat.ask_user_pipeline.helper.assess_user_answer_pipeline_mock import (
    AssessUserAnswerPipelineMock,
)
from tests.pipeline.chat.ask_user_pipeline.helper.helper import (
    get_pass_ratio,
    get_pyris_message,
    llm_majority_vote,
)
from tests.pipeline.chat.ask_user_pipeline.helper.logging_utils import (
    ResultLog,
    exercise_slug,
)
from tests.pipeline.chat.ask_user_pipeline.helper.test_callback import (
    AskUserStatusCallbackMock,
)
from tests.pipeline.chat.ask_user_pipeline.helper.test_data import (
    DTO,
    EXERCISE,
    FIRST_MESSAGE_TIME,
    LLM_PAIRWISE_DIVERSITY_PROMPT,
    USER_ANSWER,
    VARIANT,
)

# This class tests the relation of multiple generated questions within one session:
# first by logging the generated sequences themselves, then by pairwise-evaluating
# every pair of questions within a sequence for topical diversity
#
# Marked "integration" and excluded from the default pytest run (see the
# addopts/markers config in pyproject.toml): setUpClass below drives the real
# AskUserPipeline, which invokes the LLMs configured in llm_config.yml, and
# test_LLM_pairwise_diversity invokes another LLM to judge the results. Those
# executions invoke configured LLMs and therefore make the default suite
# depend on external credentials/network access, incur model usage, and fail
# in the clean CI configuration whose example model entries have no API
# keys. Run explicitly with `pytest -m integration`.
@pytest.mark.integration
class TestAskUserMultipleQuestions(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # 6 sequences per exercise, 5 questions each
        number_of_tests = 6
        number_of_questions_per_test = 5
        cls.required_test_pass_rate = 0.9
        # Judge instances per question pair -- majority vote of 3.
        cls.judge_instances = 3

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

        pipeline = AskUserPipeline()

        cls.dto = copy.deepcopy(DTO)
        cls.message_time = FIRST_MESSAGE_TIME

        # One list of question strings per generated sequence.
        cls.sequences: list[list[str]] = []

        for _ in range(number_of_tests):
            questions = []

            callback = AskUserStatusCallbackMock()
            pipeline(cls.dto, VARIANT, callback, event="FIRST_QUESTION")
            questions.append(callback.final_result)

            cls.dto.chat_history = [get_pyris_message(0, False, callback.final_result)]
            cls.dto.chat_history.append(get_pyris_message(1, True, USER_ANSWER))

            for j in range(1, number_of_questions_per_test):
                callback = AskUserStatusCallbackMock()
                pipeline(cls.dto, VARIANT, callback, event=None)
                questions.append(callback.final_result)
                cls.dto.chat_history.append(
                    get_pyris_message(j * 2, False, callback.final_result)
                )
                cls.dto.chat_history.append(
                    get_pyris_message(j * 2 + 1, True, USER_ANSWER)
                )

            cls.sequences.append(questions)

        slug = exercise_slug(EXERCISE.title)

        sequences_log = ResultLog(
            f"TestAskUserMultipleQuestions_{slug}_sequences.csv",
            ["Sequence", "Position", "Question"],
        )
        for seq_idx, questions in enumerate(cls.sequences, start=1):
            seq_id = f"S{seq_idx:02d}"
            for pos, question in enumerate(questions, start=1):
                sequences_log.append_row([seq_id, pos, question])

        # Every pair of questions within every sequence, majority-voted by
        # the judge model
        cls.pair_results = []

        pairs_log = ResultLog(
            f"TestAskUserMultipleQuestions_{slug}_pairs.csv",
            ["Sequence", "Q_i", "Q_j", "Verdict", "Reason"],
        )

        for seq_idx, questions in enumerate(cls.sequences, start=1):
            seq_id = f"S{seq_idx:02d}"
            for i, j in itertools.combinations(range(1, len(questions) + 1), 2):
                pair_text = f"Question A: {questions[i - 1]}\nQuestion B: {questions[j - 1]}"

                majority_pass, reason = llm_majority_vote(
                    LLM_PAIRWISE_DIVERSITY_PROMPT,
                    cls.judge_instances,
                    pair_text,
                    cls.task,
                    cls.template_concatenated,
                    cls.code_concatenated,
                )
                cls.pair_results.append(majority_pass)

                verdict_cell = "+" if majority_pass else "-"
                reason_cell = "" if majority_pass else reason

                pairs_log.append_row([seq_id, i, j, verdict_cell, reason_cell])

    @classmethod
    def tearDownClass(cls):
        cls._monkeypatch.undo()

    def test_LLM_pairwise_diversity(self):
        pass_ratio = get_pass_ratio(self.pair_results, lambda passed: passed)

        assert pass_ratio >= self.required_test_pass_rate


if __name__ == "__main__":
    unittest.main()
