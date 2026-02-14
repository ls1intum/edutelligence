import datetime
import unittest
import re
from collections import Counter

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

# Helper function to extract keywords from code input, that are less often used in exercise template
def extract_keywords(task_template: str, code: str, top_n: int = 10):
    """
    Extract keywords that represent the conceptual difference between task and code.
    This focuses on tokens that appear significantly more often in the code than in the task text.
    """
    # Normalize text
    task_text = task_template.lower()
    code_text = code.lower()


    # Tokenization (simple words and identifiers)
    token_pattern = r"[a-zA-Z_][a-zA-Z0-9_]*"


    task_tokens = re.findall(token_pattern, task_text)
    code_tokens = re.findall(token_pattern, code_text)


    task_counts = Counter(task_tokens)
    code_counts = Counter(code_tokens)


    # Compute difference: code tokens that are more characteristic in code
    diff_scores = {}
    for token, count in code_counts.items():
        task_count = task_counts.get(token, 0)
        # Only consider tokens that appear more often in code
        if count > task_count:
            diff_scores[token] = count - task_count


    # Select most relevant tokens
    keywords = [token for token, _ in Counter(diff_scores).most_common(top_n)]


    return keywords

# This class only tests the quality of the question generation.
# It assumes the case where the student already answered an assessment question sufficiently and is asked another one (so no introductory text is generated).
class TestAskUser(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.task = TASK_SORTING
        cls.template = TEMPLATE_SORTING
        cls.code = CODE_SORTING

        cls.template_concatenated = "\n".join(cls.template.values())
        cls.code_concatenated = "\n".join(cls.code.values())

        cls.keywords_code = extract_keywords(cls.template_concatenated, cls.code_concatenated)
        cls.keywords_task = extract_keywords(cls.template_concatenated, cls.task)

        # Note: Feedback of submission is not part of test inputs, could be interesting to check if generated questions are only about correct parts of submission
        # For this to happen, ResultDTO would have to be extended with feedback and the test data with a test repository

        cls.dto = PromptUserChatPipelineExecutionDTO(
            submission=ProgrammingSubmissionDTO(id=1, date=datetime.datetime(2026, 1, 11), repository=cls.code, isPractice=False, buildFailed=False,
                                                latestResult=ResultDTO(completionDate=datetime.datetime(2026, 1, 10), successful=True)),
            exercise=ProgrammingExerciseDTO(id=1, name="Bubble Sort", programmingLanguage="JAVA", templateRepository=cls.template, problemStatement=cls.task),
            course=CourseDTO(id=1,name="Intro to Programming", description=None),
            eventPayload=PyrisEventDTO(eventType="", event="sufficient_answer"), settings=None,
            user=UserDTO(id=1, firstName="Random", lastName="User", memirisEnabled=False))

        cls.variant = PromptUserVariant(
            variant_id="prompt_user_v1", name="Prompt User",
            description="Variant for assessing user understanding",
            agent_model="gpt-4o-mini")

        cls.callback = TestPromptUserStatusCallback()

        cls.pipeline = PromptUserAgentPipeline()
        cls.pipeline(cls.dto, cls.variant, cls.callback, None)

        cls.question = cls.callback.final_result

        print(f"Pipeline result:\n{cls.question}")


    def test_question_is_thematically_relevant(self):
        # this tests if keywords of submission minus template or keywords of the problem statement minus template are part of the question
        assert (any(k in self.question.lower() for k in self.keywords_code) or any(k in self.question.lower() for k in self.keywords_task))


    def test_question_not_too_easy(self):
        assert len(self.question) > 20
        difficulty_words = ["why", "how", "what", "explain", "describe", "elaborate", "tell"]
        assert any(w in self.question.lower() for w in difficulty_words)


    def test_question_not_too_difficult_length(self):
        assert len(self.question) < 220


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
        assert not any(p in self.question.lower() for p in forbidden_phrases)


    def test_question_single_concept_focus(self):
        key_terms = [
            "swap", "loop", "runtime", "complexity", "array", "sorting", "comparison",
            "iteration", "index", "element", "order", "ascending", "descending",
            "efficiency", "pass", "algorithm", "step", "position", "largest", "smallest",
            "temporary", "variable", "condition", "function", "class", "object",
            "recursion", "base case", "edge case", "input", "output", "pointer",
            "memory", "data", "structure"
        ]
        num_terms = sum(1 for k in key_terms if k in self.question.lower())
        assert num_terms <= 4


    def test_LLM_evaluation(self):
        voting_result = evaluate(LLM_GENERATION_EVALUATION_PROMPT, 5, self.question, self.task, self.template_concatenated, self.code_concatenated)

        assert voting_result > 0.9


if __name__ == "__main__":
    unittest.main()
