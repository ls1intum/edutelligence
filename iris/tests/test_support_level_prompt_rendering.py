import os
import re

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "src",
    "iris",
    "pipeline",
    "prompts",
    "templates",
)

LOW_HEADING = "Pedagogical Approach: Minimal Direct Help"
HIGH_HEADING = "Pedagogical Approach: Comprehensive Guidance"

CHAT_MODES = [
    "PROGRAMMING_EXERCISE_CHAT",
    "LECTURE_CHAT",
    "COURSE_CHAT",
    "TEXT_EXERCISE_CHAT",
]


def _render_template(template_name: str, context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )
    template = env.get_template(template_name)
    return template.render(context)


def _system_prompt_context(chat_mode: str, support_level: str) -> dict:
    return {
        "current_date": "2026-03-11",
        "user_language": "en",
        "course_name": "Test Course",
        "chat_mode": chat_mode,
        "support_level": support_level,
        "allow_lecture_tool": False,
        "allow_faq_tool": False,
        "allow_memiris_tool": False,
        "has_chat_history": False,
        "has_competencies": False,
        "has_exercises": False,
        "metrics_enabled": False,
        "has_query": False,
        "event": None,
        "custom_instructions": "",
        "lecture_name": None,
        "exercise_id": None,
        "exercise_title": "",
        "problem_statement": "",
        "programming_language": "",
        "start_date": "",
        "end_date": "",
        "text_exercise_submission": "",
        "mcq_parallel": False,
        "official_logistics_intent": False,
        "current_view_blocks": [],
        "current_view_is_combined": False,
    }


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_system_prompt_low_support_level_injects_minimal_block(chat_mode):
    rendered = _render_template(
        "chat_system_prompt.j2", _system_prompt_context(chat_mode, "low")
    )
    assert LOW_HEADING in rendered
    assert HIGH_HEADING not in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_system_prompt_high_support_level_injects_comprehensive_block(chat_mode):
    rendered = _render_template(
        "chat_system_prompt.j2", _system_prompt_context(chat_mode, "high")
    )
    assert HIGH_HEADING in rendered
    assert LOW_HEADING not in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_system_prompt_moderate_support_level_injects_nothing(chat_mode):
    rendered = _render_template(
        "chat_system_prompt.j2", _system_prompt_context(chat_mode, "moderate")
    )
    assert LOW_HEADING not in rendered
    assert HIGH_HEADING not in rendered


@pytest.mark.parametrize(
    ("support_level", "word_budget"),
    [("low", 110), ("moderate", 220), ("high", 250)],
)
def test_system_prompt_sets_general_support_level_word_budget(
    support_level, word_budget
):
    rendered = _render_template(
        "chat_system_prompt.j2",
        _system_prompt_context("COURSE_CHAT", support_level),
    )

    assert f"at most {word_budget} words" in rendered
    assert "Structured tool artifacts" in rendered


@pytest.mark.parametrize("support_level", ["low", "moderate", "high"])
def test_system_prompt_includes_guide_replacement_safety_rules(support_level):
    rendered = _render_template(
        "chat_system_prompt.j2",
        _system_prompt_context("PROGRAMMING_EXERCISE_CHAT", support_level),
    )
    assert "Self-Check Before Sending" in rendered
    assert "Tool Output Is Reference-Only" in rendered


def test_system_prompt_high_support_reinforces_self_check_for_code():
    rendered = _render_template(
        "chat_system_prompt.j2",
        _system_prompt_context("PROGRAMMING_EXERCISE_CHAT", "high"),
    )
    assert "Even when walking through an approach step-by-step conceptually" in rendered
    assert "copy-pasteable code is not" in rendered


def _guide_context(support_level: str) -> dict:
    return {
        "problem_statement": "Implement a function that returns the sum of two ints.",
        "support_level": support_level,
        "chat_mode": "PROGRAMMING_EXERCISE_CHAT",
        "request_kind": "substantive",
        "compile_diagnostic": False,
        "has_supplied_text_draft": False,
        "has_submission_repository": False,
        "submission_visibility_intent": False,
        "validation_feedback": "",
    }


@pytest.mark.parametrize("support_level", ["low", "moderate", "high"])
def test_programming_system_prompt_requires_evidence_grounded_traces(support_level):
    context = _system_prompt_context("PROGRAMMING_EXERCISE_CHAT", support_level)
    context["programming_language"] = "Python"

    rendered = _render_template("chat_system_prompt.j2", context)

    assert "Final Programming Trace Correctness Contract" in rendered
    assert "as outputs, not as starting inputs" in rendered
    assert "input explicitly supplied as an input" in rendered
    assert "hypothetical diagnostic input" in rendered
    assert "Derive every state transition from the retrieved student code" in rendered
    assert (
        "claimed final state or output follows from the preceding transitions"
        in rendered
    )
    assert "rather than asserting that you reproduced it" in rendered


@pytest.mark.parametrize("support_level", ["low", "moderate", "high"])
def test_programming_guide_rewrites_inconsistent_traces(support_level):
    rendered = _render_template(
        "exercise_chat_guide_prompt.j2", _guide_context(support_level)
    )

    assert "Programming trace correctness is mandatory" in rendered
    assert "as outputs unless the evidence explicitly labels" in rendered
    assert "input explicitly supplied as an input" in rendered
    assert "hypothetical diagnostic input" in rendered
    assert (
        "every state transition to follow from the retrieved student code" in rendered
    )
    assert "do not return `!ok!`" in rendered
    assert "do not preserve the contradiction" in rendered
    assert "Do not invent a missing input or assert reproduction" in rendered


def test_high_support_requires_hypothetical_walkthrough_when_trace_input_is_unknown():
    context = _system_prompt_context("PROGRAMMING_EXERCISE_CHAT", "high")
    context["programming_language"] = "Python"

    rendered = _render_template("chat_system_prompt.j2", context)

    assert "High-support trace request with unknown input" in rendered
    assert "do not omit the walk-through" in rendered
    assert "one minimal hypothetical diagnostic input" in rendered
    assert "not the failing test input" in rendered
    assert "follow the retrieved student code step by step" in rendered
    assert "do not reveal or simulate a corrected implementation" in rendered


@pytest.mark.parametrize("support_level", ["low", "moderate"])
def test_lower_support_does_not_require_high_support_unknown_input_walkthrough(
    support_level,
):
    context = _system_prompt_context("PROGRAMMING_EXERCISE_CHAT", support_level)
    context["programming_language"] = "Python"

    rendered = _render_template("chat_system_prompt.j2", context)

    assert "High-support trace request with unknown input" not in rendered
    assert "do not omit the walk-through" not in rendered


def test_high_support_guide_adds_missing_hypothetical_walkthrough():
    rendered = _render_template("exercise_chat_guide_prompt.j2", _guide_context("high"))

    assert (
        "a compliant response must still include a step-by-step walk-through"
        in rendered
    )
    assert "one minimal hypothetical diagnostic input" in rendered
    assert "not the failing test input" in rendered
    assert "If the draft omits that walk-through, rewrite it to include one" in rendered
    assert "without revealing the fix" in rendered


@pytest.mark.parametrize("support_level", ["low", "moderate"])
def test_lower_support_guide_does_not_add_high_support_walkthrough(support_level):
    rendered = _render_template(
        "exercise_chat_guide_prompt.j2", _guide_context(support_level)
    )

    assert (
        "a compliant response must still include a step-by-step walk-through"
        not in rendered
    )
    assert (
        "If the draft omits that walk-through, rewrite it to include one"
        not in rendered
    )


@pytest.mark.parametrize(
    "template_name",
    ["chat_system_prompt.j2", "exercise_chat_guide_prompt.j2"],
)
@pytest.mark.parametrize("support_level", ["low", "moderate", "high"])
def test_programming_trace_rules_contain_no_concrete_test_fixture(
    template_name, support_level
):
    if template_name == "chat_system_prompt.j2":
        context = _system_prompt_context("PROGRAMMING_EXERCISE_CHAT", support_level)
        context["programming_language"] = "Python"
    else:
        context = _guide_context(support_level)
    rendered = _render_template(template_name, context)
    start_marker = (
        "Final Programming Trace Correctness Contract"
        if template_name == "chat_system_prompt.j2"
        else "Programming trace correctness is mandatory"
    )
    trace_rules = rendered[rendered.index(start_marker) :]

    assert re.search(r"\[\s*(?:-?\d+\s*,\s*)+-?\d+\s*\]", trace_rules) is None
    assert re.search(r"\b[A-Za-z_]\w*\([^)]*\)", trace_rules) is None


def test_guide_prompt_low_support_level_is_socratic():
    rendered = _render_template("exercise_chat_guide_prompt.j2", _guide_context("low"))
    assert "Socratic" in rendered
    assert "comprehensive help mode" not in rendered


def test_guide_prompt_high_support_level_announces_comprehensive_mode():
    rendered = _render_template("exercise_chat_guide_prompt.j2", _guide_context("high"))
    assert "comprehensive help mode" in rendered


def test_guide_prompt_moderate_support_level_injects_nothing():
    rendered = _render_template(
        "exercise_chat_guide_prompt.j2", _guide_context("moderate")
    )
    assert "Socratic" not in rendered
    assert "comprehensive help mode" not in rendered
    assert "minimal help mode" not in rendered


def test_low_support_final_contract_follows_custom_instructions():
    context = _system_prompt_context("COURSE_CHAT", "low")
    context["custom_instructions"] = "Always provide a declarative progress summary."

    rendered = _render_template("chat_system_prompt.j2", context)

    assert rendered.index(
        "Always provide a declarative progress summary."
    ) < rendered.index("Final Low-Support Output Contract")
    assert "output only concise guiding questions ending in `?`" in rendered


def test_low_support_dashboard_rules_keep_metrics_inside_questions():
    context = _system_prompt_context("COURSE_CHAT", "low")
    context["metrics_enabled"] = True

    rendered = _render_template("chat_system_prompt.j2", context)

    assert (
        "observed values only as factual premises inside 1–2 open questions" in rendered
    )
    assert "Start with 1–2 precise observations" not in rendered
    assert "On a pure greeting or social turn" in rendered


def test_competency_coaching_rules_are_relevance_scoped():
    context = _system_prompt_context("COURSE_CHAT", "high")
    context["has_competencies"] = True

    rendered = _render_template("chat_system_prompt.j2", context)

    assert "only when the student's request is" in rendered
    assert "about their competency, progress, performance, dashboard" in rendered
    assert "Do not surface private competency metrics or deadlines" in rendered
    assert "If the soft due date is 4 or fewer days away" in rendered


def test_low_support_guide_preserves_grounded_trace_evidence():
    rendered = _render_template("exercise_chat_guide_prompt.j2", _guide_context("low"))

    assert (
        "Preserve exact dates, numbers, percentages, metrics, trace states" in rendered
    )


def test_low_support_guide_keeps_compile_concepts_without_source_echoes():
    context = _guide_context("low")
    context["compile_diagnostic"] = True

    rendered = _render_template("exercise_chat_guide_prompt.j2", context)

    assert "preserve the compiler, punctuation, return-type" in rendered
    assert "do not repeat source statements, file paths, method signatures" in rendered
    assert "rather than naming a copyable edit" in rendered


def test_text_guide_knows_when_draft_is_already_supplied():
    context = _guide_context("low")
    context["chat_mode"] = "TEXT_EXERCISE_CHAT"
    context["has_supplied_text_draft"] = True

    rendered = _render_template("exercise_chat_guide_prompt.j2", context)

    assert "draft is already supplied" in rendered
    assert "Never ask the student to paste, share, send, upload" in rendered
    assert "which existing claim to revise" in rendered
    assert "Treat numeric traces, variable or condition names" in rendered
    assert (
        "Place any necessary grounded facts or conceptual context inside the questions"
        in rendered
    )


def test_programming_guide_knows_when_repository_is_already_supplied():
    context = _guide_context("low")
    context["has_submission_repository"] = True

    rendered = _render_template("exercise_chat_guide_prompt.j2", context)

    assert "programming submission repository is already supplied" in rendered
    assert "Never ask the student to paste, share, send, upload" in rendered
    assert "test, trace, or inspect their existing work" in rendered
    assert "end with a concrete learner verification question or action" in rendered


def test_programming_guide_limits_qualified_identifier_simplification():
    rendered = _render_template("exercise_chat_guide_prompt.j2", _guide_context("low"))

    assert "safe conceptual low-support question rewrite" in rendered
    assert "qualified dotted concept identifier" in rendered
    assert "Never apply this exception to compiler diagnostics" in rendered
    assert "always preserve numbers, dates, array values, citations" in rendered


def test_programming_guide_preserves_submission_visibility_boundary():
    context = _guide_context("moderate")
    context["has_submission_repository"] = True
    context["submission_visibility_intent"] = True

    rendered = _render_template("exercise_chat_guide_prompt.j2", context)

    assert "which version of their programming work Iris can see" in rendered
    assert "Preserve this access limitation as the central answer" in rendered
    assert "never has access to uncommitted changes" in rendered
    assert "latest submitted repository version" in rendered
    assert "never replace it with an unrelated code-debugging question" in rendered


def test_low_support_guide_has_private_data_safe_greeting_exception():
    context = _guide_context("low")
    context["request_kind"] = "greeting"

    rendered = _render_template("exercise_chat_guide_prompt.j2", context)

    assert "pure greeting" in rendered
    assert "Remove unrelated scores, progress, submissions, deadlines" in rendered


def test_low_support_official_logistics_is_a_direct_factual_exception():
    context = _system_prompt_context("COURSE_CHAT", "low")
    context["official_logistics_intent"] = True

    rendered = _render_template("chat_system_prompt.j2", context)

    assert "Official course logistics are factual access questions" in rendered
    assert "answer the requested factual policy or date directly" in rendered
    assert "For every substantive request in every chat mode" not in rendered


@pytest.mark.parametrize("support_level", ["low", "moderate", "high"])
def test_lecture_prompt_sets_strict_evidence_boundary(support_level):
    context = _system_prompt_context("LECTURE_CHAT", support_level)
    context["allow_lecture_tool"] = True

    rendered = _render_template("chat_system_prompt.j2", context)

    assert (
        "complete factual boundary for claims about what the lecture teaches"
        in rendered
    )
    assert "does not establish unstated recursion-tree depths" in rendered
    assert "Final Lecture Evidence Boundary" in rendered
    assert "do not use general subject knowledge to fill missing steps" in rendered
    assert "ask for the relevant material, slide, or section" in rendered


def test_low_support_lecture_prompt_requires_a_non_rephrasing_reasoning_step():
    rendered = _render_template(
        "chat_system_prompt.j2",
        _system_prompt_context("LECTURE_CHAT", "low"),
    )

    assert "perform one concrete reasoning operation" in rendered
    assert "Do not merely repeat the student's question" in rendered
    assert "do not place the sought answer inside the question" in rendered
    assert "withhold answer-bearing conclusions" in rendered
    assert "theorem-case number" in rendered
    assert "Make the student perform mappings and comparisons" in rendered


def test_high_support_lecture_prompt_does_not_license_outside_examples():
    rendered = _render_template(
        "chat_system_prompt.j2",
        _system_prompt_context("LECTURE_CHAT", "high"),
    )

    assert "every factual step is explicitly supported" in rendered
    assert "do not import outside textbook examples" in rendered


def test_lecture_guide_rewrite_cannot_expand_sparse_evidence():
    context = _guide_context("low")
    context["chat_mode"] = "LECTURE_CHAT"
    context["problem_statement"] = ""

    rendered = _render_template("exercise_chat_guide_prompt.j2", context)

    assert (
        "Treat a sparse recurrence, theorem name, or displayed expression" in rendered
    )
    assert "Do not expand it into intermediate steps" in rendered
    assert "concrete next reasoning operation" in rendered
    assert (
        "preservation rule does not apply to an answer-bearing conclusion" in rendered
    )
    assert "remove any final result, solution, theorem-case number" in rendered
    assert "Ask the learner to perform a mapping or comparison themselves" in rendered
    assert "Do not encode the mapping as paired presuppositions" in rendered
    assert "ask only for the relevant material, slide, or section" in rendered
