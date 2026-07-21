# pylint: disable=import-outside-toplevel,invalid-name,protected-access

import json
import os
import threading
from queue import Queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableLambda

from iris.domain.status.activity_dto import ActivityState
from iris.pipeline.chat.mcq_chat_mixin import (
    detect_mcq_intent,
    mcq_post_agent_hook,
    mcq_pre_agent_hook,
)
from iris.pipeline.shared.activity_tracker import ActivityTracker
from iris.pipeline.shared.mcq_generation_pipeline import (
    McqGenerationPipeline,
    _deterministic_mcq_subtopics,
    _question_count_from_command,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

VALID_SINGLE_MCQ = json.dumps(
    {
        "type": "mcq",
        "question": "What is 2+2?",
        "options": [
            {"text": "3", "correct": False},
            {"text": "4", "correct": True},
            {"text": "5", "correct": False},
            {"text": "6", "correct": False},
        ],
        "explanation": "The correct answer is 4 because 2 + 2 equals 4.",
    }
)

VALID_MCQ_SET = json.dumps(
    {
        "type": "mcq-set",
        "questions": [
            {
                "question": "Q1?",
                "options": [
                    {"text": "A", "correct": True},
                    {"text": "B", "correct": False},
                    {"text": "C", "correct": False},
                    {"text": "D", "correct": False},
                ],
                "explanation": "A is correct because it is the first answer.",
            },
            {
                "question": "Q2?",
                "options": [
                    {"text": "X", "correct": False},
                    {"text": "Y", "correct": True},
                    {"text": "Z", "correct": False},
                    {"text": "W", "correct": False},
                ],
                "explanation": "Y is correct because it is the second answer.",
            },
        ],
    }
)


def _make_pipeline(llm_return: str) -> McqGenerationPipeline:
    """Create an McqGenerationPipeline with a mocked LLM, bypassing __init__."""
    pipeline = McqGenerationPipeline.__new__(McqGenerationPipeline)
    pipeline.implementation_id = "mcq_generation_pipeline"
    pipeline.tokens = []
    pipeline.local = False

    template_dir = os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
        "iris",
        "pipeline",
        "prompts",
        "templates",
    )
    jinja_env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )
    pipeline.prompt_template = jinja_env.get_template("mcq_generation_prompt.j2")
    pipeline.llm = SimpleNamespace(
        tokens=SimpleNamespace(pipeline=None),
    )
    pipeline.pipeline = RunnableLambda(lambda _: llm_return)
    return pipeline


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_valid_single_mcq_json_returned():
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)
    result = pipeline(command="Generate a question about math")
    parsed = json.loads(result)
    assert parsed["type"] == "mcq"
    assert len(parsed["options"]) == 4


@pytest.mark.parametrize(
    ("prompt_text", "count"),
    [
        ("Generate three questions about recursion.", 3),
        ("Please create five MCQs on graph traversal.", 5),
        ("Could you ask me four quiz questions about databases?", 4),
        ("Prepare a set of six multiple-choice questions from this material.", 6),
        ("I'd like seven questions for exam practice.", 7),
        ("I need two multiple choice questions on heaps.", 2),
        ("Three questions about asymptotic complexity, please.", 3),
        ("That was useful. Two more questions, please.", 2),
        ("Give me twelve questions about operating systems.", 10),
        ("Create 250 MCQs on the lecture.", 10),
        ("Generate zero questions about queues.", 1),
        ("Erstelle drei Multiple-Choice-Fragen zu Suchbäumen.", 3),
        ("Generiere fünf MCQs über Rechnernetze.", 5),
        ("Gib mir vier Quizfragen zur Vorlesung.", 4),
        ("Bereite sechs Fragen zur Klausur vor.", 6),
        ("Ich möchte sieben Fragen zu Datenbanken.", 7),
        ("Ich brauche zwei Fragen zu Warteschlangen.", 2),
        ("Teste mich mit acht Fragen zu Algorithmen.", 8),
        ("Bitte drei Fragen zu Laufzeiten.", 3),
        ("Das war leicht. Zwei weitere Fragen, bitte.", 2),
        ("Stell mir zwölf Fragen zur Vorlesung.", 10),
        ("Erstelle null Fragen zu Listen.", 1),
    ],
)
def test_mcq_intent_extracts_numeric_and_written_counts(prompt_text, count):
    assert detect_mcq_intent(prompt_text) == (True, count)


@pytest.mark.parametrize(
    "message",
    [
        "When is the quiz?",
        "I answered three quiz questions yesterday.",
        "Our worksheet contains five multiple-choice questions.",
        "How do I create three quiz questions in Java?",
        "What does multiple choice mean?",
        "Wann findet das Quiz statt?",
        "Ich habe drei Quizfragen falsch beantwortet.",
        "Wie kann ich fünf Fragen in Moodle anlegen?",
    ],
)
def test_mcq_intent_ignores_mentions_and_meta_questions(message):
    assert detect_mcq_intent(message) == (False, 0)


@pytest.mark.parametrize(
    "prompt_text",
    [
        "Quiz me on sorting.",
        "Generate questions about transactions.",
        "Teste mein Wissen zu Graphen.",
        "Erstelle eine Frage zu Rekursion.",
    ],
)
def test_mcq_intent_defaults_clear_uncounted_requests_to_one(prompt_text):
    assert detect_mcq_intent(prompt_text) == (True, 1)


def test_valid_mcq_set_json_returned():
    pipeline = _make_pipeline(VALID_MCQ_SET)
    result = pipeline(command="Generate 2 questions")
    parsed = json.loads(result)
    assert parsed["type"] == "mcq-set"
    assert len(parsed["questions"]) == 2


def test_markdown_fences_stripped():
    fenced = "```json\n" + VALID_SINGLE_MCQ + "\n```"
    pipeline = _make_pipeline(fenced)
    result = pipeline(command="Generate a question")
    parsed = json.loads(result)
    assert parsed["type"] == "mcq"


def test_invalid_json_raises():
    pipeline = _make_pipeline("This is not JSON at all")
    with pytest.raises(json.JSONDecodeError):
        pipeline(command="Generate a question")


def test_wrong_option_count_raises():
    bad_mcq = json.dumps(
        {
            "type": "mcq",
            "question": "Q?",
            "options": [
                {"text": "A", "correct": True},
                {"text": "B", "correct": False},
                {"text": "C", "correct": False},
            ],
            "explanation": "Oops.",
        }
    )
    pipeline = _make_pipeline(bad_mcq)
    with pytest.raises(ValueError, match="exactly 4 options"):
        pipeline(command="Generate a question")


def test_multiple_correct_answers_raises():
    bad_mcq = json.dumps(
        {
            "type": "mcq",
            "question": "Q?",
            "options": [
                {"text": "A", "correct": True},
                {"text": "B", "correct": True},
                {"text": "C", "correct": False},
                {"text": "D", "correct": False},
            ],
            "explanation": "Two correct.",
        }
    )
    pipeline = _make_pipeline(bad_mcq)
    with pytest.raises(ValueError, match="exactly 1 correct"):
        pipeline(command="Generate a question")


def test_explanation_deterministically_repairs_inconsistent_answer_key():
    inconsistent = json.dumps(
        {
            "type": "mcq",
            "question": "What is the final state?",
            "options": [
                {"text": "[2, 3, 5, 3, 7]", "correct": True},
                {"text": "[3, 2, 5, 3, 7]", "correct": False},
                {"text": "[2, 3, 3, 5, 7]", "correct": False},
                {"text": "[3, 5, 3, 2, 7]", "correct": False},
            ],
            "explanation": (
                "Larger elements move right. The fully sorted array is " "[2,3,3,5,7]."
            ),
        }
    )
    pipeline = _make_pipeline(inconsistent)
    calls = 0

    def invoke(_messages):
        nonlocal calls
        calls += 1
        return inconsistent

    pipeline.pipeline = RunnableLambda(invoke)

    parsed = json.loads(pipeline(command="Generate a question"))

    assert calls == 2
    assert [option["correct"] for option in parsed["options"]] == [
        False,
        False,
        True,
        False,
    ]


@pytest.mark.parametrize(
    ("option", "explanation"),
    [
        ("O ( n ² )", "The correct answer is $O(n^2)$ because both loops run."),
        (
            r"$\Theta(n)$",
            "The correct answer is Θ ( n ) because each element is visited once.",
        ),
        (
            "breadth-first search",
            "The correct answer is breadth first search because it visits levels.",
        ),
        (
            "Breitensuche",
            "Die richtige Antwort ist *Breitensuche*, weil sie Ebenen besucht.",
        ),
        ("4", "Since 2 + 2 = 4, that is the result."),
    ],
)
def test_explanation_answer_matching_normalizes_text_math_and_whitespace(
    option, explanation
):
    payload = json.loads(VALID_SINGLE_MCQ)
    payload["options"][1]["text"] = option
    payload["explanation"] = explanation
    pipeline = _make_pipeline(json.dumps(payload))

    parsed = json.loads(pipeline(command="Generate a question"))

    assert parsed["options"][1]["correct"] is True


def test_exact_longer_option_wins_over_its_textual_prefix():
    payload = json.loads(VALID_SINGLE_MCQ)
    payload["options"] = [
        {"text": "2", "correct": True},
        {"text": "20", "correct": False},
        {"text": "200", "correct": False},
        {"text": "2000", "correct": False},
    ]
    payload["explanation"] = "The correct answer is 20 because 4 × 5 = 20."
    pipeline = _make_pipeline(json.dumps(payload))

    parsed = json.loads(pipeline(command="Generate a question"))

    assert [option["correct"] for option in parsed["options"]] == [
        False,
        True,
        False,
        False,
    ]


def test_unique_implicit_option_value_identifies_answer_without_fixed_phrase():
    payload = json.loads(VALID_SINGLE_MCQ)
    payload["options"] = [
        {"text": "[2, 3, 5, 3, 7]", "correct": True},
        {"text": "[3, 2, 5, 3, 7]", "correct": False},
        {"text": "[2, 3, 3, 5, 7]", "correct": False},
        {"text": "[3, 5, 3, 2, 7]", "correct": False},
    ]
    payload["explanation"] = (
        "After shifting the larger entries, the array becomes [2,3,3,5,7]."
    )
    pipeline = _make_pipeline(json.dumps(payload))

    parsed = json.loads(pipeline(command="Generate a question"))

    assert [option["correct"] for option in parsed["options"]] == [
        False,
        False,
        True,
        False,
    ]


def test_unique_implicit_math_result_ignores_unlisted_operands():
    payload = json.loads(VALID_SINGLE_MCQ)
    payload["options"] = [
        {"text": "8", "correct": True},
        {"text": "16", "correct": False},
        {"text": "24", "correct": False},
        {"text": "32", "correct": False},
    ]
    payload["explanation"] = "Doubling the quantity yields 16 after this step."
    pipeline = _make_pipeline(json.dumps(payload))

    parsed = json.loads(pipeline(command="Generate a question"))

    assert parsed["options"][1]["correct"] is True


def test_equation_premise_is_not_mistaken_for_a_second_declared_answer():
    payload = json.loads(VALID_SINGLE_MCQ)
    payload["question"] = "What is the solution of T(n)=2T(n/2)+Theta(n)?"
    payload["options"] = [
        {"text": "Theta(n)", "correct": False},
        {"text": "Theta(n log n)", "correct": True},
        {"text": "Theta(log n)", "correct": False},
        {"text": "Theta(n^2)", "correct": False},
    ]
    payload["explanation"] = (
        "The correct answer is Theta(n log n) because for a=2, b=2, and "
        "f(n)=Theta(n), Master Theorem case 2 applies."
    )
    pipeline = _make_pipeline(json.dumps(payload))

    parsed = json.loads(pipeline(command="Generate a question"))

    assert [option["correct"] for option in parsed["options"]] == [
        False,
        True,
        False,
        False,
    ]


def test_required_verifier_replaces_variant_dependent_count_question(monkeypatch):
    monkeypatch.setenv("IRIS_QA_DISABLE_PIPELINE_RETRIES", "1")
    ambiguous = {
        "type": "mcq",
        "question": (
            "When inserting into a sorted prefix of length k, what is the exact "
            "worst-case comparison count?"
        ),
        "options": [
            {"text": "Exactly k", "correct": False},
            {"text": "At most k", "correct": False},
            {"text": "Exactly k+1", "correct": False},
            {"text": "At most k+1", "correct": True},
        ],
        "explanation": (
            "The correct answer is At most k+1 because a final loop check is counted."
        ),
    }
    verified = {
        "type": "mcq",
        "question": "What is true after each insertion-sort outer iteration?",
        "options": [
            {"text": "The processed prefix is sorted", "correct": True},
            {"text": "The unprocessed suffix is sorted", "correct": False},
            {"text": "Every key is in final position", "correct": False},
            {"text": "No comparisons remain", "correct": False},
        ],
        "explanation": (
            "The correct answer is The processed prefix is sorted because each "
            "iteration inserts one key into that prefix."
        ),
    }
    responses = iter([json.dumps(ambiguous), json.dumps(verified)])
    prompts = []
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)

    def invoke(messages):
        prompts.append(messages[0].content)
        return next(responses)

    pipeline.pipeline = RunnableLambda(invoke)

    parsed = json.loads(pipeline(command="Generate a harder insertion-sort question"))

    assert parsed["question"] == verified["question"]
    assert len(prompts) == 2
    assert "implementation variant" in prompts[1]


def test_distractor_context_does_not_count_as_implicit_answer():
    payload = json.loads(VALID_SINGLE_MCQ)
    payload["options"] = [
        {"text": "quick sort", "correct": True},
        {"text": "merge sort", "correct": False},
        {"text": "heap sort", "correct": False},
        {"text": "selection sort", "correct": False},
    ]
    payload["explanation"] = (
        "Quick sort is a common distractor here; stability follows from merge sort."
    )
    pipeline = _make_pipeline(json.dumps(payload))

    parsed = json.loads(pipeline(command="Generate a question"))

    assert parsed["options"][1]["correct"] is True


def test_negated_option_does_not_count_as_implicit_answer():
    payload = json.loads(VALID_SINGLE_MCQ)
    payload["options"] = [
        {"text": "breadth-first search", "correct": True},
        {"text": "depth-first search", "correct": False},
        {"text": "binary search", "correct": False},
        {"text": "linear search", "correct": False},
    ]
    payload["explanation"] = (
        "Not breadth-first search: depth-first search uses the stack in this case."
    )
    pipeline = _make_pipeline(json.dumps(payload))

    parsed = json.loads(pipeline(command="Generate a question"))

    assert parsed["options"][1]["correct"] is True


def test_multiple_neutral_option_mentions_remain_ambiguous(monkeypatch):
    monkeypatch.setenv("IRIS_QA_DISABLE_PIPELINE_RETRIES", "1")
    payload = json.loads(VALID_SINGLE_MCQ)
    payload["options"] = [
        {"text": "breadth-first search", "correct": True},
        {"text": "depth-first search", "correct": False},
        {"text": "binary search", "correct": False},
        {"text": "linear search", "correct": False},
    ]
    payload["explanation"] = (
        "Breadth-first search and depth-first search both visit graph vertices."
    )
    pipeline = _make_pipeline(json.dumps(payload))

    with pytest.raises(ValueError, match="multiple existing options"):
        pipeline(command="Generate a question")


def test_conflicting_explanation_gets_one_bounded_repair():
    ambiguous = json.loads(VALID_SINGLE_MCQ)
    ambiguous["explanation"] = "3 is correct, but 4 is correct as well."
    responses = iter([json.dumps(ambiguous), VALID_SINGLE_MCQ, VALID_SINGLE_MCQ])
    prompts = []
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)

    def invoke(messages):
        prompts.append(messages[0].content)
        return next(responses)

    pipeline.pipeline = RunnableLambda(invoke)

    parsed = json.loads(pipeline(command="Generate a question"))

    assert parsed["options"][1]["correct"] is True
    assert len(prompts) == 3
    assert "identifies multiple existing options as correct" in prompts[1]
    assert "final correctness reviewer" in prompts[2]


def test_zero_match_explanation_preserves_single_valid_answer_key():
    payload = json.loads(VALID_SINGLE_MCQ)
    payload["explanation"] = (
        "This follows by applying the operation once and simplifying the result."
    )
    pipeline = _make_pipeline(json.dumps(payload))

    parsed = json.loads(pipeline(command="Generate a question"))

    assert parsed["explanation"] == payload["explanation"]
    assert [option["correct"] for option in parsed["options"]] == [
        False,
        True,
        False,
        False,
    ]


def test_zero_match_explanations_preserve_each_mcq_set_answer_key():
    payload = json.loads(VALID_MCQ_SET)
    payload["questions"][0]["explanation"] = "The definition directly applies."
    payload["questions"][1]["explanation"] = "The stated property determines it."
    pipeline = _make_pipeline(json.dumps(payload))

    parsed = json.loads(pipeline(command="Generate 2 questions"))

    assert [option["correct"] for option in parsed["questions"][0]["options"]] == [
        True,
        False,
        False,
        False,
    ]
    assert [option["correct"] for option in parsed["questions"][1]["options"]] == [
        False,
        True,
        False,
        False,
    ]


def test_zero_positive_match_rejects_explicit_negation_of_marked_answer(
    monkeypatch,
):
    monkeypatch.setenv("IRIS_QA_DISABLE_PIPELINE_RETRIES", "1")
    payload = json.loads(VALID_SINGLE_MCQ)
    payload["explanation"] = "The marked value 4 is incorrect here."
    pipeline = _make_pipeline(json.dumps(payload))

    with pytest.raises(ValueError, match="contradicts the marked correct option"):
        pipeline(command="Generate a question")


def test_ambiguous_explanation_fails_closed_when_repair_is_disabled(monkeypatch):
    monkeypatch.setenv("IRIS_QA_DISABLE_PIPELINE_RETRIES", "1")
    ambiguous = json.loads(VALID_SINGLE_MCQ)
    ambiguous["explanation"] = "Both 3 and 4 are discussed as possible answers."
    pipeline = _make_pipeline(json.dumps(ambiguous))

    with pytest.raises(ValueError, match="multiple existing options"):
        pipeline(command="Generate a question")


def test_conflicting_explicit_explanation_answers_fail_closed(monkeypatch):
    monkeypatch.setenv("IRIS_QA_DISABLE_PIPELINE_RETRIES", "1")
    ambiguous = json.loads(VALID_SINGLE_MCQ)
    ambiguous["explanation"] = "3 is correct, but 4 is correct as well."
    pipeline = _make_pipeline(json.dumps(ambiguous))

    with pytest.raises(ValueError, match="multiple existing options"):
        pipeline(command="Generate a question")


def test_mcq_set_repairs_each_explanation_key_consistently():
    payload = json.loads(VALID_MCQ_SET)
    payload["questions"][0]["options"][0]["correct"] = False
    payload["questions"][0]["options"][2]["correct"] = True
    payload["questions"][1]["options"][0]["correct"] = True
    payload["questions"][1]["options"][1]["correct"] = False
    pipeline = _make_pipeline(json.dumps(payload))

    parsed = json.loads(pipeline(command="Generate 2 questions"))

    assert [option["correct"] for option in parsed["questions"][0]["options"]] == [
        True,
        False,
        False,
        False,
    ]
    assert [option["correct"] for option in parsed["questions"][1]["options"]] == [
        False,
        True,
        False,
        False,
    ]


def test_normalized_duplicate_options_are_rejected():
    payload = json.loads(VALID_SINGLE_MCQ)
    payload["options"][2]["text"] = " $ 4 $ "
    pipeline = _make_pipeline(json.dumps(payload))

    with pytest.raises(ValueError, match="distinct after normalization"):
        pipeline(command="Generate a question")


def test_strict_schema_rejects_unknown_fields():
    bad_mcq = json.loads(VALID_SINGLE_MCQ)
    bad_mcq["answer"] = "4"
    pipeline = _make_pipeline(json.dumps(bad_mcq))

    with pytest.raises(ValueError, match="unknown or missing fields"):
        pipeline(command="Generate a question")


def test_validation_failure_gets_only_one_informed_repair():
    responses = iter(["not-json", VALID_SINGLE_MCQ, VALID_SINGLE_MCQ])
    prompts = []
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)

    def invoke(messages):
        prompts.append(messages[0].content)
        return next(responses)

    pipeline.pipeline = RunnableLambda(invoke)

    assert json.loads(pipeline(command="Generate a question"))["type"] == "mcq"
    assert len(prompts) == 3
    assert "failed validation" in prompts[1]
    assert "Previous invalid output" in prompts[1]
    assert "final correctness reviewer" in prompts[2]


def test_qa_validation_failure_never_launches_repair(monkeypatch):
    monkeypatch.setenv("IRIS_QA_DISABLE_PIPELINE_RETRIES", "1")
    calls = 0
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)

    def invoke(_messages):
        nonlocal calls
        calls += 1
        return "not-json"

    pipeline.pipeline = RunnableLambda(invoke)

    with pytest.raises(json.JSONDecodeError):
        pipeline(command="Generate a question")
    assert calls == 1


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("Generate three questions about loops", 3),
        ("Erstelle drei Fragen zu Schleifen", 3),
        ("Erstelle 4 Quizfragen", 4),
        ("Generate a question", 1),
    ],
)
def test_question_count_intent_is_language_robust(command, expected):
    assert _question_count_from_command(command) == expected


def test_subtopics_require_object_shape_and_exact_distinct_count():
    pipeline = _make_pipeline(
        json.dumps({"subtopics": ["loops", "conditionals", "functions"]})
    )

    assert pipeline._extract_subtopics("three questions", None, 3) == [
        "loops",
        "conditionals",
        "functions",
    ]


def test_lecture_grounded_mcq_canonicalizes_uniquely_inferable_source():
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)

    parsed = json.loads(
        pipeline(
            command="Generate a question",
            lecture_content="Lecture: Week 1, Unit: Foundations, Page 1",
        )
    )

    assert parsed["source"] == "Foundations"


def test_lecture_grounded_mcq_rejects_nonexistent_source():
    payload = json.loads(VALID_SINGLE_MCQ)
    payload["source"] = "Invented Unit"
    pipeline = _make_pipeline(json.dumps(payload))

    with pytest.raises(ValueError, match="exactly match a retrieved lecture unit"):
        pipeline(
            command="Generate a question",
            lecture_content="Lecture: Week 1, Unit: Foundations, Page 1",
        )


def test_single_question_unwraps_equivalent_one_item_mcq_set_without_retry(
    monkeypatch,
):
    monkeypatch.setenv("IRIS_QA_DISABLE_PIPELINE_RETRIES", "1")
    question = json.loads(VALID_SINGLE_MCQ)
    question.pop("type")
    pipeline = _make_pipeline(json.dumps({"type": "mcq-set", "questions": [question]}))

    parsed = json.loads(pipeline(command="Generate one question"))

    assert parsed["type"] == "mcq"
    assert parsed["question"] == question["question"]


def test_lecture_source_case_and_whitespace_are_canonicalized():
    payload = json.loads(VALID_SINGLE_MCQ)
    payload["source"] = "  foundations  "
    pipeline = _make_pipeline(json.dumps(payload))

    parsed = json.loads(
        pipeline(
            command="Generate a question",
            lecture_content="Lecture: Week 1, Unit: Foundations, Page 1",
        )
    )

    assert parsed["source"] == "Foundations"


def test_missing_source_remains_invalid_when_multiple_units_are_ambiguous():
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)
    lecture_content = (
        "Lecture: Week 1, Unit: Foundations, Page 1\n"
        "A general introduction.\n\n"
        "Lecture: Week 1, Unit: Applications, Page 2\n"
        "A general example."
    )

    with pytest.raises(ValueError, match="unknown or missing fields"):
        pipeline(command="Generate a question", lecture_content=lecture_content)


def test_deterministic_subtopics_are_distinct_and_use_exact_lecture_units():
    lecture_content = (
        "Lecture: Week 1, Unit: Merge Sort, Page 1\nDivide and merge.\n\n"
        "Lecture: Week 1, Unit: Master Theorem, Page 2\nAnalyze recurrences."
    )

    subtopics = _deterministic_mcq_subtopics(
        "Create three questions", 3, lecture_content=lecture_content
    )

    assert len(subtopics) == len(set(subtopics)) == 3
    assert "'Merge Sort'" in subtopics[0]
    assert "'Master Theorem'" in subtopics[1]


def test_subtopic_failure_uses_zero_call_deterministic_worker_plan():
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)
    pipeline._extract_subtopics = MagicMock(side_effect=ValueError("bad shape"))
    pipeline._generate_multiple_sequential = MagicMock()
    worker_commands = []

    class Worker:
        def __init__(self):
            self.tokens = []

        def __call__(self, *, command, **_kwargs):
            worker_commands.append(command)
            return VALID_SINGLE_MCQ

    queue = Queue()
    lecture_content = "Lecture: Week 1, Unit: Merge Sort, Page 1\nDivide and merge."
    with patch(
        "iris.pipeline.shared.mcq_generation_pipeline.McqGenerationPipeline",
        side_effect=lambda **_kwargs: Worker(),
    ):
        pipeline._generate_multiple(
            "Create three questions",
            None,
            "en",
            3,
            queue,
            lecture_content=lecture_content,
        )

    assert len(worker_commands) == 3
    assert all("lecture unit 'Merge Sort'" in item for item in worker_commands)
    assert pipeline._generate_multiple_sequential.call_count == 0
    assert queue.qsize() == 3


def test_parallel_mcqs_are_emitted_in_subtopic_order():
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)
    pipeline._extract_subtopics = MagicMock(return_value=["slow", "fast", "middle"])
    delays = {"slow": 0.03, "fast": 0.0, "middle": 0.01}

    class Worker:
        def __init__(self):
            self.tokens = []

        def __call__(self, *, command, **_kwargs):
            import time

            subtopic = next(item for item in delays if item in command)
            time.sleep(delays[subtopic])
            parsed = json.loads(VALID_SINGLE_MCQ)
            parsed["question"] = subtopic
            return json.dumps(parsed)

    queue = Queue()
    with patch(
        "iris.pipeline.shared.mcq_generation_pipeline.McqGenerationPipeline",
        side_effect=lambda **_kwargs: Worker(),
    ):
        pipeline._generate_multiple("topic", None, "en", 3, queue)

    assert [json.loads(queue.get()[1])["question"] for _ in range(3)] == [
        "slow",
        "fast",
        "middle",
    ]


def test_mcq_parallel_thread_reports_activity():
    emitted = []
    release_generation = threading.Event()
    generation_started = threading.Event()

    class FakeMcqPipeline:
        """Stub MCQ pipeline that signals generation start and blocks until released."""

        def __init__(self):
            self.tokens = []

        @staticmethod
        def run_in_thread(**kwargs):
            result_storage = kwargs["result_storage"]
            result_storage["queue"] = Queue()

            def generate():
                generation_started.set()
                release_generation.wait(2)
                result_storage["mcq_json"] = VALID_SINGLE_MCQ
                result_storage["queue"].put(("mcq", VALID_SINGLE_MCQ))
                result_storage["queue"].put(("done", None))

            thread = threading.Thread(target=generate)
            thread.start()
            return thread

    state = SimpleNamespace(
        mcq_parallel=True,
        mcq_count=1,
        dto=SimpleNamespace(user=SimpleNamespace(lang_key="en")),
        callback=MagicMock(),
        activity_tracker=ActivityTracker(
            lambda items, seq: emitted.append((seq, items))
        ),
        result="intro",
        allow_lecture_tool=False,
    )

    mcq_pre_agent_hook(
        state=state,
        mcq_pipeline=FakeMcqPipeline(),
        get_text_of_latest_user_message=lambda _state: "generate a question",
        db=MagicMock(),
        course_id=1,
        chat_history=[],
    )
    assert generation_started.wait(2)
    assert emitted[-1][1][0].name == "generate_mcq_questions"
    assert emitted[-1][1][0].state == ActivityState.RUNNING

    release_generation.set()
    mcq_post_agent_hook(
        state=state,
        mcq_pipeline=FakeMcqPipeline(),
        track_tokens=lambda _state, _token: None,
        timeout=2,
    )

    assert emitted[-1][1][0].state == ActivityState.FINISHED
    assert emitted[-1][1][0].duration_millis is not None
    assert VALID_SINGLE_MCQ in state.result


def test_prompt_curly_braces_not_parsed_as_variables():
    """Regression test: the rendered prompt contains {"type": "mcq"...} JSON examples.
    These must NOT be interpreted as LangChain template variables."""
    captured_input = {}

    def capturing_llm(messages):
        captured_input["messages"] = messages
        return VALID_SINGLE_MCQ

    pipeline = _make_pipeline(VALID_SINGLE_MCQ)
    pipeline.pipeline = RunnableLambda(capturing_llm)

    # This should NOT raise KeyError about template variables
    result = pipeline(command="Generate a question about {curly} braces")
    parsed = json.loads(result)
    assert parsed["type"] == "mcq"

    # Verify the prompt was passed as a SystemMessage containing the JSON examples
    messages = captured_input["messages"]
    assert len(messages) == 1
    assert isinstance(messages[0], SystemMessage)
    assert '"type":"mcq"' in messages[0].content


# ---------------------------------------------------------------------------
# run_in_thread tests
# ---------------------------------------------------------------------------


def test_run_in_thread_single_question():
    """run_in_thread with count=1 should store result and put it in queue."""
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)
    storage = {}
    thread = pipeline.run_in_thread(
        command="Generate a question about math",
        chat_history=None,
        user_language="en",
        result_storage=storage,
        count=1,
    )
    thread.join(timeout=10)

    # Should store in mcq_json for backward compat
    assert "mcq_json" in storage
    parsed = json.loads(storage["mcq_json"])
    assert parsed["type"] == "mcq"

    # Queue should have mcq + done
    q = storage["queue"]
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    assert any(t == "mcq" for t, _ in items)
    assert items[-1] == ("done", None)


def test_run_in_thread_error_on_failure():
    """run_in_thread should put error in queue on failure."""
    pipeline = _make_pipeline("not valid json")
    storage = {}
    thread = pipeline.run_in_thread(
        command="Generate a question",
        chat_history=None,
        user_language="en",
        result_storage=storage,
        count=1,
    )
    thread.join(timeout=10)

    assert "error" in storage
    q = storage["queue"]
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    assert any(t == "error" for t, _ in items)
    assert items[-1] == ("done", None)


def test_run_in_thread_multiple_questions():
    """run_in_thread with count>1 should generate multiple questions via queue."""
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)
    storage = {}

    class Worker:
        def __init__(self):
            self.tokens = []

        @staticmethod
        def __call__(**_kwargs):
            return VALID_SINGLE_MCQ

    with patch(
        "iris.pipeline.shared.mcq_generation_pipeline.McqGenerationPipeline",
        side_effect=lambda **_kwargs: Worker(),
    ):
        thread = pipeline.run_in_thread(
            command="Generate 3 questions about math",
            chat_history=None,
            user_language="en",
            result_storage=storage,
            count=3,
        )
        thread.join(timeout=30)

    q = storage["queue"]
    mcq_items = []
    while not q.empty():
        msg_type, data = q.get_nowait()
        if msg_type == "mcq":
            mcq_items.append(data)
        elif msg_type == "done":
            break
    assert len(mcq_items) == 3
    for item in mcq_items:
        parsed = json.loads(item)
        assert parsed["type"] == "mcq"
