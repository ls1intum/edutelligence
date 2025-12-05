import unittest

from iris.tests.test_data import CODE_SORTING, TASK_SORTING


# Helper function to extract keywords from code input, every word with minimum length 3 is kept
def extract_keywords_from_code(code: str):
    return [w.lower() for w in code.replace("(", " ").replace(")", " ").split() if len(w) > 2]


class AskUserTest(unittest.TestCase):

    def setUp(self):
        self.task = TASK_SORTING
        self.code = CODE_SORTING
        self.question = "" # generate_verification_question(self.code, self.task)
        self.keywords = extract_keywords_from_code(self.code)



    def test_question_is_thematically_relevant(self):
        assert (any(k in self.question.lower() for k in self.keywords) or any(k in self.question.lower() for k in self.task))


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
