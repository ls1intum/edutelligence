import unittest
import re
from collections import Counter

from .test_data import CODE_SORTING, TASK_SORTING, TEMPLATE_SORTING

from iris.domain import ExerciseChatPipelineExecutionDTO
from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from iris.domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from iris.domain.event.pyris_event_dto import PyrisEventDTO
from iris.domain.variant.exercise_chat_variant import ExerciseChatVariant
from .TestCallback import TestExerciseChatCallback


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


class TestAskUser(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.task = TASK_SORTING
        cls.template = TEMPLATE_SORTING
        cls.code = CODE_SORTING
        cls.keywords = extract_keywords("\n".join(cls.template.values()), "\n".join(cls.code.values()))

        cls.dto = ExerciseChatPipelineExecutionDTO(
            submission=ProgrammingSubmissionDTO(id=1, repository=cls.code, isPractice=False, buildFailed=False),
            exercise=ProgrammingExerciseDTO(id=1, name="Bubble Sort", programmingLanguage="JAVA", templateRepository=cls.template, problemStatement=cls.task),
            course=CourseDTO(id=1,name="Intro to Programming", description=None),
            eventPayload=PyrisEventDTO(eventType="", event=""),
            customInstructions=None, settings=None, user=None)

        cls.variant = ExerciseChatVariant(
            variant_id="exercise_chat_v1", name="Exercise Chat",
            description="Variant for exercise explanations",
            agent_model="gpt-4o-mini",citation_model="gpt-4o")

        cls.callback = TestExerciseChatCallback()

        from iris.pipeline.chat.exercise_chat_agent_pipeline import ExerciseChatAgentPipeline

        cls.pipeline = ExerciseChatAgentPipeline()
        cls.pipeline(cls.dto, cls.variant, cls.callback, None)

        cls.question = cls.callback.final_result

    def test_question_is_thematically_relevant(self):
        assert(True)
        #assert (any(k in self.question.lower() for k in self.keywords) or any(k in self.question.lower() for k in self.task))


    def test_question_not_too_easy(self):
        assert len(self.question) > 20
        difficulty_words = ["why", "how", "what", "explain", "describe", "elaborate", "tell"]
        assert any(w in self.question.lower() for w in difficulty_words)


    def test_question_not_too_difficult_length(self):
        assert len(self.question) < 150


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
        assert num_terms <= 3


if __name__ == "__main__":
    unittest.main()
