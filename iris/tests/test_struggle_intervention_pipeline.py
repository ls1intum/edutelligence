import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from iris.domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from iris.domain.struggle.episode_dto import EpisodeDTO, EpisodeHintDTO
from iris.domain.struggle.struggle_signal_dto import StruggleSignal
from iris.pipeline.struggle_intervention_pipeline import (
    CONFIRM_CLOSE_FALLBACK_LABEL,
    CONFIRM_CLOSE_FALLBACK_SENTENCE,
    DEGRADED_CLOSE_RATIONALE,
    INLINE_HINT_MAX_CHARS,
    MIXED_SCHEMA_CLOSE_RATIONALE,
    StruggleInterventionPipeline,
    parse_confirm_close_result,
    parse_gate_result,
    summarize_signal,
)
from iris.web.routers.health.Pipelines.features import Features
from iris.web.routers.health.Pipelines.registery import PIPELINE_BY_FEATURE

# The snapshot the run was given; an anchor is only forwarded when it points into it.
ANCHOR_REPOSITORY = {
    "Sort.java": "\n".join(f"// line {i}" for i in range(1, 61)),
    "src/A.java": "\n".join(f"// line {i}" for i in range(1, 61)),
}


def _gate(raw: str):
    """parse_gate_result against a repository that contains the files these tests anchor into."""
    return parse_gate_result(raw, ANCHOR_REPOSITORY)


def test_parse_gate_result_active():
    raw = '{"action":"active","message":"Check the empty list.","confidence":0.81,"rationale":"FM"}'
    g = parse_gate_result(raw)
    assert g.action == "active"
    assert g.message == "Check the empty list."
    assert g.confidence == 0.81


def test_parse_gate_result_silent_when_unparseable_defaults_safe():
    g = parse_gate_result("the model rambled without json")
    assert g.action == "silent"
    assert g.message is None
    assert g.confidence == 0.0


def test_parse_gate_result_ambient():
    g = parse_gate_result(
        '{"action":"ambient","message":"re-read the spec","confidence":0.5}'
    )
    assert g.action == "ambient"
    assert g.message == "re-read the spec"
    assert g.confidence == 0.5


def test_parse_gate_result_invalid_action_defaults_silent():
    g = parse_gate_result('{"action":"shout","message":"x","confidence":0.9}')
    assert g.action == "silent"
    assert g.message is None
    assert g.confidence == 0.0


def test_parse_gate_result_coerces_string_confidence():
    g = parse_gate_result('{"action":"ambient","message":"hint","confidence":"0.9"}')
    assert g.confidence == 0.9


def test_parse_gate_result_non_silent_without_message_defaults_silent():
    g = parse_gate_result('{"action":"active","message":null,"confidence":0.8}')
    assert g.action == "silent"
    assert g.message is None
    assert g.confidence == 0.0


def test_parse_gate_result_rejects_non_finite_confidence():
    # json.loads accepts NaN/Infinity; both would break the JSON callback POST.
    nan = parse_gate_result('{"action":"ambient","message":"x","confidence":NaN}')
    inf = parse_gate_result('{"action":"ambient","message":"x","confidence":Infinity}')
    assert nan.confidence == 0.0
    assert inf.confidence == 0.0


def test_parse_gate_result_clamps_confidence_to_unit_range():
    high = parse_gate_result('{"action":"ambient","message":"x","confidence":5}')
    low = parse_gate_result('{"action":"ambient","message":"x","confidence":-2}')
    assert high.confidence == 1.0
    assert low.confidence == 0.0


def test_parse_gate_result_non_string_message_defaults_silent():
    g = parse_gate_result('{"action":"active","message":123,"confidence":0.8}')
    assert g.action == "silent"
    assert g.message is None


def test_parse_gate_result_drops_non_string_rationale():
    g = parse_gate_result(
        '{"action":"ambient","message":"x","confidence":0.5,"rationale":42}'
    )
    assert g.rationale is None


def test_parse_gate_result_extracts_anchor_and_inline_hint():
    raw = (
        '{"action":"ambient","message":"Look at the loop bound.","confidence":0.7,'
        '"anchor":{"file":"Sort.java","line":42},"inlineHint":"off-by-one at the last index?"}'
    )
    g = _gate(raw)
    assert g.anchor == ("Sort.java", 42)
    assert g.inline_hint == "off-by-one at the last index?"


def test_parse_gate_result_anchor_absent_is_none():
    g = parse_gate_result('{"action":"ambient","message":"x","confidence":0.6}')
    assert g.anchor is None
    assert g.inline_hint is None


def test_parse_gate_result_malformed_anchor_is_none():
    g = parse_gate_result(
        '{"action":"ambient","message":"x","confidence":0.6,"anchor":{"file":"a.java"},"inlineHint":7}'
    )
    assert g.anchor is None  # missing line -> dropped
    assert g.inline_hint is None  # non-string -> dropped


def test_parse_gate_result_boolean_line_is_none():
    # bool is an int subclass in Python; a boolean line must NOT masquerade as a line number.
    g = parse_gate_result(
        '{"action":"ambient","message":"x","confidence":0.6,"anchor":{"file":"a.java","line":true}}'
    )
    assert g.anchor is None


# ---------------------------------------------------------------------------
# parse_confirm_close_result
# ---------------------------------------------------------------------------


def test_parse_confirm_close_resolved_true():
    r = parse_confirm_close_result(
        '{"resolved": true, "closingSentence": "Nice \U0001f44d", "episodeLabel": "Wrong index"}'
    )
    assert r.resolved is True
    assert r.closing_sentence == "Nice \U0001f44d"
    assert r.episode_label == "Wrong index"


def test_parse_confirm_close_resolved_false_carries_offer_in_rationale():
    r = parse_confirm_close_result(
        '{"resolved": false, "rationale": "empty-list case still trips"}'
    )
    assert r.resolved is False
    assert r.closing_sentence is None
    assert r.episode_label is None
    assert r.rationale == "empty-list case still trips"


def test_parse_confirm_close_malformed_fails_closed_to_not_resolved():
    r = parse_confirm_close_result("not json")
    assert r.resolved is False


def _signal(boundary: str, path: str) -> StruggleSignal:
    return StruggleSignal.model_validate(
        {
            "alert": {
                "tSessionS": 540,
                "primaryBoundary": boundary,
                "boundaryTypes": [boundary],
                "severity": 0.72,
                "path": path,
                "inWarmup": False,
                "inGrace": False,
            },
            "trajectory": [{"t": 530, "s": 0.6}],
            "sessionSeconds": 540,
        }
    )


def _minimal_signal() -> StruggleSignal:
    return _signal("FM", "armed")


def test_summarize_signal_explains_tps_boundary():
    # The LLM cannot infer TPS semantics from code/build context, so the summary
    # must gloss the full firing surface: stalled, regressed, or failing builds.
    summary = summarize_signal(_signal("TPS", "discrete"))
    assert "primary boundary: TPS (test stagnation:" in summary
    assert "stalled, regressed, or failing outright" in summary
    assert "path=discrete" in summary


def test_summarize_signal_leaves_edit_boundaries_unglossed():
    summary = summarize_signal(_signal("FM", "armed"))
    assert "primary boundary: FM;" in summary
    assert "test stagnation" not in summary


# ---------------------------------------------------------------------------
# Autoescape regression: j2 templates must NOT HTML-escape LLM prompt values
# ---------------------------------------------------------------------------


def test_confirm_close_template_does_not_html_escape_hint_text():
    """Prompt templates must not HTML-escape their values: autoescaping .j2 turns a hint like
    `i < n or List<String> & reset` into the entities the LLM then reads as the hint.
    """
    pipeline = StruggleInterventionPipeline()
    episode = EpisodeDTO(
        episodeId="ep-1",
        isNew=False,
        hints=[
            EpisodeHintDTO(
                level="active",
                text="is the bound i < n or List<String> & reset?",
                atSessionS=120.0,
            )
        ],
    )
    rendered = pipeline.confirm_close_template.render(
        course_name="Algorithms & Data Structures",
        signal_summary=(
            "primary boundary: FM; severity sBase=0.82; path=armed; "
            "recent sBase trajectory: (t=60,sBase=0.80); session 300s."
        ),
        episode=episode,
    )
    assert "i < n" in rendered, "angle bracket in hint text was HTML-escaped"
    assert "List<String>" in rendered, "angle bracket in hint text was HTML-escaped"
    assert "& reset" in rendered, "ampersand in hint text was HTML-escaped"
    assert "&lt;" not in rendered, "HTML escape entity found in LLM prompt"
    assert "&amp;" not in rendered, "HTML escape entity found in LLM prompt"


def test_confirm_close_prompt_prioritizes_tests_and_explains_diff():
    """Objective test results are decisive, and the live-vs-submitted diff tool is explained."""
    pipeline = StruggleInterventionPipeline()
    rendered = pipeline.confirm_close_template.render(
        course_name="Algorithms",
        signal_summary="primary boundary: FM; severity sBase=0.82; path=armed.",
        episode=None,
    )
    assert "do not default to doubt" in rendered
    assert "PASS" in rendered
    # Substrings stay within one wrapped line so the assertions survive prompt re-wrapping.
    assert "local_vs_submitted_diff" in rendered
    assert "SUBMITTED build" in rendered
    assert "get_feedbacks" in rendered


def test_decide_prompt_renders_prior_episode_hints_with_silent_rule():
    """Episode dedup: the decide prompt shows the hints already delivered in this episode and
    carries the hard rule that a same-diagnosis nudge, reworded or not, means action "silent".
    """
    pipeline = StruggleInterventionPipeline()
    episode = EpisodeDTO(
        episodeId="ep-1",
        isNew=False,
        hints=[
            EpisodeHintDTO(
                level="active",
                text="Still returns -1 (stub); implement predecessor search",
                atSessionS=490.0,
            ),
            EpisodeHintDTO(
                level="ambient",
                text="Look at the loop bound",
                atSessionS=610.0,
            ),
        ],
    )
    rendered = pipeline.system_prompt_template.render(
        course_name="Algorithms",
        signal_summary="primary boundary: STATE; severity sBase=1.00; path=e6.",
        episode=episode,
    )
    assert "Still returns -1 (stub); implement predecessor search" in rendered
    assert "Look at the loop bound" in rendered
    assert "same diagnosis" in rendered
    assert "Rewording" in rendered


def test_decide_prompt_dedup_rule_is_standing_and_covers_history_tags():
    """Cross-episode dedup: the same-diagnosis rule holds for a fresh episode too, because earlier
    hints reach the model only as "(proactive hint, ...)"-tagged chat-history messages. The
    recovery EXCEPTION keeps a genuinely returned problem hintable again.
    """
    pipeline = StruggleInterventionPipeline()
    for episode in (None, EpisodeDTO(episodeId="ep-1", isNew=True, hints=[])):
        rendered = pipeline.system_prompt_template.render(
            course_name="Algorithms",
            signal_summary="primary boundary: FM; severity sBase=0.84; path=armed.",
            episode=episode,
        )
        assert "same diagnosis" in rendered
        assert "(proactive hint" in rendered
        assert "EXCEPTION" in rendered
        # The per-episode hint list itself renders only when there are hints.
        assert "in this intervention episode" not in rendered


def test_decide_prompt_splits_the_dedup_rule_by_episode_and_dismissal():
    """The chat history is the whole session and its proactive messages are never cleaned up, so a
    nudge from days ago reads like one from a minute ago. Artemis marks those and the rule splits
    three ways; a dismissal bars the diagnosis in every episode, not only the one it was given in.
    """
    pipeline = StruggleInterventionPipeline()
    rendered = pipeline.system_prompt_template.render(
        course_name="Algorithms",
        signal_summary="primary boundary: FM; severity sBase=0.84; path=armed.",
        episode=None,
    )
    # the marker is explained, including that its absence proves nothing
    assert "(proactive hint from an earlier episode" in rendered
    assert "treat an unmarked nudge as" in rendered
    # all three cases are stated
    assert "THIS EPISODE" in rendered
    assert "AN EARLIER EPISODE, DISMISSED" in rendered
    assert "AN EARLIER EPISODE, NOT DISMISSED" in rendered
    # and the obvious way to abuse the split is closed off
    assert "A change of episode by itself never makes a repeat new." in rendered
    # relaxing the earlier-episode case is conditional on the current code, not free
    assert "the CURRENT code confirms" in rendered


def _tool_state(intent, submission):
    dto = SimpleNamespace(
        programming_exercise_submission=submission,
        programming_exercise=None,
        intent=intent,
    )
    return SimpleNamespace(dto=dto, callback=MagicMock())


def test_local_vs_submitted_diff_tool_registered_for_decide_and_confirm_close():
    """The diff tool is dual use: it verifies a fix on confirm_close and reveals the region the
    student is actively editing on decide, so both intents get it whenever a submission exists.
    """
    pipeline = StruggleInterventionPipeline()
    submission = ProgrammingSubmissionDTO.model_validate(
        {"id": 1, "isPractice": False, "buildFailed": False}
    )
    cc_tools = [
        t.__name__ for t in pipeline.get_tools(_tool_state("confirm_close", submission))
    ]
    decide_tools = [
        t.__name__ for t in pipeline.get_tools(_tool_state("decide", submission))
    ]
    assert "local_vs_submitted_diff" in cc_tools
    assert "local_vs_submitted_diff" in decide_tools


def test_local_vs_submitted_diff_tool_absent_without_submission():
    """No submission -> no code tools at all, so no focus signal (the prompt falls back)."""
    pipeline = StruggleInterventionPipeline()
    decide_tools = [t.__name__ for t in pipeline.get_tools(_tool_state("decide", None))]
    assert "local_vs_submitted_diff" not in decide_tools


def test_decide_prompt_renders_focus_and_redirect_rule():
    """The focus/redirect bias: help where the student is editing, redirect only off a region that
    looks correct and say so, fall back when there is no focus signal. Soft, and subordinate to
    the no-repeat and current-code-confirmation rules.
    """
    pipeline = StruggleInterventionPipeline()
    rendered = pipeline.system_prompt_template.render(
        course_name="Algorithms",
        signal_summary="primary boundary: STATE; severity sBase=1.00; path=armed.",
        episode=None,
    )
    assert "local_vs_submitted_diff" in rendered
    assert "focus region" in rendered
    assert "do NOT redirect to a different method" in rendered
    assert "MUST frame it as a redirect" in rendered
    assert "No focus signal" in rendered
    assert "same-diagnosis HARD RULE" in rendered
    assert "SOFT bias" in rendered


def test_decide_prompt_renders_presence_tone_by_mode():
    """The presence clause modulates tone by the student's Off/Less/More choice: pull (Less) leans
    reticent, push (More) may reach out. It is tone-only and must not relax the hard rules.
    """
    pipeline = StruggleInterventionPipeline()
    pull = pipeline.system_prompt_template.render(
        course_name="Algorithms",
        signal_summary="primary boundary: STATE; severity sBase=1.00; path=armed.",
        episode=None,
        proactivity_mode="pull",
    )
    push = pipeline.system_prompt_template.render(
        course_name="Algorithms",
        signal_summary="primary boundary: STATE; severity sBase=1.00; path=armed.",
        episode=None,
        proactivity_mode="push",
    )
    assert "reticent" in pull
    assert 'reserve "active"' in pull
    assert "reach-out mode" in push
    assert pull != push
    assert "NEVER relaxes the same-diagnosis HARD RULE" in pull
    assert "NEVER relaxes the same-diagnosis HARD RULE" in push


def test_help_request_prompt_relaxes_repeat_but_keeps_hard_guardrails():
    pipeline = StruggleInterventionPipeline()
    episode = EpisodeDTO(
        episodeId="ep-1",
        isNew=False,
        hints=[
            EpisodeHintDTO(
                level="active", text="Look at the loop bound", atSessionS=490.0
            )
        ],
    )
    rendered = pipeline.help_request_template.render(
        course_name="Algorithms",
        signal_summary="primary boundary: STATE; severity sBase=1.00.",
        episode=episode,
    )
    assert "asked" in rendered.lower()
    assert "never" in rendered.lower() and "silent" in rendered.lower()
    assert "next" in rendered.lower() and "step" in rendered.lower()
    assert "solution" in rendered.lower()
    assert "reword" in rendered.lower()
    assert "Look at the loop bound" in rendered


def test_build_system_message_selects_help_request_template():
    pipeline = StruggleInterventionPipeline()
    state = SimpleNamespace(
        dto=SimpleNamespace(
            intent="help_request",
            course=SimpleNamespace(name="Algorithms"),
            struggle_signal=_minimal_signal(),
            episode=None,
            proactivity_mode="push",
        ),
        callback=MagicMock(),
    )
    msg = pipeline.build_system_message(state)
    assert "never" in msg.lower()
    assert msg != pipeline.system_prompt_template.render(
        course_name="Algorithms",
        signal_summary=summarize_signal(_minimal_signal()),
        episode=None,
        proactivity_mode="push",
    )


# ---------------------------------------------------------------------------
# Non-spoiler contract + hint ladder
#
# An escalation rule without an absolute ceiling ends in the implementation written out as
# prose, so every struggle prompt defines a spoiler itself and caps the ladder.
# ---------------------------------------------------------------------------


def _episode_with(n_hints: int) -> EpisodeDTO:
    """An episode carrying n already-delivered hints."""
    return EpisodeDTO(
        episodeId="ep-1",
        isNew=False,
        hints=[
            EpisodeHintDTO(level="ambient", text=f"hint {i}", atSessionS=float(i))
            for i in range(n_hints)
        ],
    )


def _render(template, episode=None):
    return template.render(
        course_name="Algorithms",
        signal_summary="primary boundary: STATE; severity sBase=0.90; path=e6.",
        episode=episode,
        proactivity_mode="push",
    )


def test_hint_contract_reaches_the_two_hinting_prompts_only():
    """decide and help_request may emit a hint, so both carry the contract and the ladder.
    confirm_close may not hint at all, so it carries the narrow no-new-help block instead: the
    contract would license exactly the rung-3 output it must never produce.
    """
    pipeline = StruggleInterventionPipeline()

    for template in (pipeline.system_prompt_template, pipeline.help_request_template):
        rendered = _render(template, _episode_with(0))
        assert "NON-SPOILER CONTRACT" in rendered
        assert "HINT LADDER" in rendered
        assert "NO NEW HELP" not in rendered

    close = _render(pipeline.confirm_close_template, _episode_with(0))
    assert "NO NEW HELP" in close
    assert "NON-SPOILER CONTRACT" not in close
    assert "HINT LADDER" not in close


def test_contract_allows_the_references_it_also_requires():
    """The Forbidden and Allowed lists have to be satisfiable at once: banning everything that came
    out of a tool would ban the file, the line, the method name and the failing test the Allowed
    list requires, and a model resolving that either way gets it wrong.
    """
    pipeline = StruggleInterventionPipeline()
    rendered = _render(pipeline.help_request_template, _episode_with(1))

    assert (
        "Solution-bearing content quoted or reproduced from repository files"
        in rendered
    )
    assert "Allowed list names -- file and line" in rendered
    assert "stay permitted; it is the material" in rendered
    assert (
        "Anything lifted from tool output beyond a file/line reference" not in rendered
    )


def test_decide_prompt_keeps_a_silent_decision_free_of_an_anchor():
    """A repeated diagnosis goes `silent` and can still have one concrete line, so requiring an
    anchor whenever a line is the locus would make the silence disclose what it exists to
    withhold. Artemis drops it, but the model must not be told two incompatible things.
    """
    pipeline = StruggleInterventionPipeline()
    rendered = _render(pipeline.system_prompt_template, _episode_with(1))

    assert (
        "For an `ambient` or `active` decision, set `anchor`+`inlineHint`" in rendered
    )
    assert "A `silent` decision carries no hint at all" in rendered
    assert (
        "Outside `silent`, set both to null ONLY for genuinely diffuse struggle"
        in rendered
    )


def test_contract_names_the_prose_spoiler_classes():
    """A spoiler needs no code fence: an algorithm with its bounds and state variables in prose is
    one, and a generic "never give the solution" does not catch it, so the classes are named.
    """
    pipeline = StruggleInterventionPipeline()
    rendered = _render(pipeline.help_request_template, _episode_with(1))

    assert "operator or condition replacement" in rendered
    # Reciting the required behaviour is rung 3, so the Allowed list must not hand it out at rung 2.
    assert "Reciting what they say is rung 3" in rendered
    assert "The behaviour that spot must have, but only as far as" not in rendered
    assert "Index ranges or loop bounds" in rendered
    assert "algorithm or data structure to apply" in rendered
    assert "State-variable names together with their update rule" in rendered
    assert "ordered sequence of steps whose endpoint is working code" in rendered
    assert "Writing code the student could take over as the fix" in rendered
    # The blanket rule, kept verbatim so it does not depend on stitching the classes together.
    assert "NEVER give the full or near-full solution" in rendered
    assert "NEVER write the code for them" in rendered
    # The contract governs the inline gutter cue too, not just the chat message.
    assert "in `message` and `inlineHint`" in rendered


def test_help_request_ladder_rises_to_three_and_then_stops():
    """Concreteness rises to rung 3 and never past it, however often the student asks. The count
    is every delivered hint, an unsolicited ambient->active escalation included, so prior>=2
    clamps rather than continuing to climb.
    """
    pipeline = StruggleInterventionPipeline()
    for prior, expected in ((0, 1), (1, 2), (2, 3), (5, 3)):
        rendered = _render(pipeline.help_request_template, _episode_with(prior))
        assert f"You are answering at rung {expected}." in rendered
        assert "There is no rung 4." in rendered

    # No episode at all still renders a valid rung rather than blowing up.
    assert "You are answering at rung 1." in _render(pipeline.help_request_template)


def test_help_request_keeps_never_silent_with_a_way_out_at_the_ceiling():
    """NEVER SILENT and the ceiling pull against each other at rung 3, and a model left to resolve
    that itself resolves it by spoiling, so the prompt hands it explicit non-spoiler exits.
    """
    pipeline = StruggleInterventionPipeline()
    rendered = _render(pipeline.help_request_template, _episode_with(2))

    assert "NEVER SILENT" in rendered
    assert "including at rung 3" in rendered
    assert "counter-example" in rendered
    assert "ask a human tutor" in rendered
    # The tutor referral is the one exit that is not itself a hint, so it has to count as an answer.
    assert "satisfies NEVER SILENT" in rendered
    # Unbounded escalation must not come back.
    assert "one notch MORE concrete than the last" not in rendered


def test_decide_is_capped_at_rung_two_and_drops_the_dead_chat_reference():
    """An unsolicited nudge stops at rung 2; rung 3 is reserved for a hint the student asked for.
    Pointing at the exercise-chat rules is dead too: this pipeline builds its own system message
    and never loads chat_system_prompt.j2.
    """
    pipeline = StruggleInterventionPipeline()
    for prior, expected in ((0, 1), (1, 2), (2, 2), (5, 2)):
        rendered = _render(pipeline.system_prompt_template, _episode_with(prior))
        assert f"You are answering at rung {expected}." in rendered
        assert "Never use rung 3 for this unsolicited check" in rendered

    rendered = _render(pipeline.system_prompt_template, _episode_with(0))
    assert "Same no-solution rules as the normal exercise chat" not in rendered
    # decide may stay silent and help_request may not, so the shared contract binds only content.
    assert "do emit a hint, you name WHERE the problem is" in rendered
    assert 'respond with action "silent"' in rendered

    # The same contract text must not push help_request toward silence, which is forbidden there.
    help_rendered = _render(pipeline.help_request_template, _episode_with(0))
    assert "do emit a hint, you name WHERE the problem is" in help_rendered
    assert "return `silent`" not in help_rendered


def test_confirm_close_constrains_both_student_visible_fields():
    """episodeLabel is student-visible too, forwarded on a resolved close and rendered as the fold
    label, so it takes the same what-not-how limit as closingSentence. rationale never leaves
    Pyris, so the prompt must not describe it as student-facing.
    """
    pipeline = StruggleInterventionPipeline()
    rendered = _render(pipeline.confirm_close_template, _episode_with(1))

    assert "`closingSentence` and" in rendered
    assert "`episodeLabel` are the only student-visible fields" in rendered
    assert "never restate HOW it works or" in rendered
    assert "for logging only; it is NOT shown to the student" in rendered
    assert "shown to the student when NOT resolved" not in rendered


def test_length_budget_is_tighter_for_the_unsolicited_nudge():
    """An unsolicited nudge interrupts, so it gets the smaller budget. Both need a stated ceiling:
    the model keeps explaining otherwise, and a long enough explanation of a defect is the fix.
    """
    pipeline = StruggleInterventionPipeline()

    decide = _render(pipeline.system_prompt_template, _episode_with(0))
    assert "at most 2 sentences and" in decide
    assert "under 250 characters" in decide

    help_request = _render(pipeline.help_request_template, _episode_with(1))
    assert "up to 4 sentences and under 350 characters" in help_request
    # The larger budget must read as a ceiling, not as something to fill.
    assert "That is a ceiling," in help_request

    # confirm_close emits no hint at all, so it carries neither budget.
    close = _render(pipeline.confirm_close_template, _episode_with(1))
    assert "under 250 characters" not in close
    assert "under 350 characters" not in close


def test_contract_requires_backticks_and_does_not_ban_them():
    """The ban is about composing a fix, not about markup: phrasing it as "code in any form" reads
    as a ban on the backticks and the model spells the name out as prose to comply. A name
    already in the student's code stays marked up, or the chip styling never renders.
    """
    pipeline = StruggleInterventionPipeline()

    for template in (pipeline.system_prompt_template, pipeline.help_request_template):
        rendered = _render(template, _episode_with(1))
        assert (
            "FORMAT of `message`, and this is required rather than optional" in rendered
        )
        assert "every name you point at goes in backticks" in rendered
        assert "Writing code the student could take over as the fix" in rendered
        assert "Code in any form" not in rendered


def test_inline_hint_is_specified_and_parsed_as_plain_text():
    """inlineHint is drawn into the editor unfiltered, with no markdown pass, so the FORMAT rule
    that makes `message` mark up every name is exactly wrong here: backticks would reach the
    student as characters. The prompt says so, and the parser strips regardless.
    """
    pipeline = StruggleInterventionPipeline()
    rendered = _render(pipeline.system_prompt_template, _episode_with(0))
    assert "FORMAT of `inlineHint` is the opposite" in rendered
    assert "no markdown pass" in rendered

    gate = _gate(
        '{"action": "ambient", "message": "look at `foo`", "confidence": 0.8,'
        ' "anchor": {"file": "Sort.java", "line": 42},'
        ' "inlineHint": "Still returns `-1` unconditionally"}'
    )
    assert gate.inline_hint == "Still returns -1 unconditionally"
    # message keeps its markup: that one IS rendered as markdown.
    assert gate.message == "look at `foo`"

    # A cue that was nothing but markup is not a cue.
    assert (
        parse_gate_result(
            '{"action": "ambient", "message": "m", "confidence": 0.5, "inlineHint": "``"}'
        ).inline_hint
        is None
    )


def test_inline_hint_is_drawn_as_one_line():
    """The gutter draws a single line after the anchored statement, so a cue is collapsed onto one
    line before the budget is measured; anything after a newline would otherwise be lost.
    """
    gate = _gate(
        '{"action": "ambient", "message": "m", "confidence": 0.5,'
        ' "anchor": {"file": "Sort.java", "line": 42},'
        ' "inlineHint": "Check the loop bound\\nand the return"}'
    )
    assert gate.inline_hint == "Check the loop bound and the return"


def test_inline_hint_is_clamped_to_the_gutter_budget():
    """Nothing downstream clamps the cue, so an overlong one pushes the student's own code
    sideways. The prompt asks for 60 characters; this makes it true.
    """
    long_cue = "Still returns minus one unconditionally and blocks both of the DP methods below"
    anchored = (
        '{"action": "ambient", "message": "m", "confidence": 0.5,'
        ' "anchor": {"file": "Sort.java", "line": 42}, "inlineHint": "%s"}'
    )
    gate = _gate(anchored % long_cue)
    assert gate.inline_hint is not None
    assert len(gate.inline_hint) <= INLINE_HINT_MAX_CHARS
    assert gate.inline_hint.endswith("…")
    # Cut at a word boundary, never mid-word.
    assert long_cue.startswith(gate.inline_hint[:-1])
    assert not gate.inline_hint[:-1].endswith(" ")

    # Exactly at the budget is untouched.
    exact = "x" * INLINE_HINT_MAX_CHARS
    assert _gate(anchored % exact).inline_hint == exact

    # One long unbreakable token has no honest way to be shortened, so it is dropped rather than
    # cut mid-word, and the anchor goes with it: a marker without its cue renders nowhere.
    dropped = _gate(anchored % ("y" * 90))
    assert dropped.inline_hint is None
    assert dropped.anchor is None


def _hook_state(result, intent, tokens=None):
    """A minimal AgentPipelineExecutionState stand-in: the pipeline is built via __new__ so no LLM
    or config is touched, and post_agent_hook only reads dto/result/tokens/callback.
    """
    callback = MagicMock()
    callback.status = SimpleNamespace(
        action=None,
        rationale=None,
        anchor_file=None,
        anchor_line=None,
        inline_hint=None,
        resolved=None,
        closing_sentence=None,
        episode_label=None,
    )
    state = SimpleNamespace(
        dto=SimpleNamespace(
            intent=intent,
            # The hook hands the snapshot to the parser, which checks the anchor against it.
            programming_exercise_submission=SimpleNamespace(
                repository=ANCHOR_REPOSITORY
            ),
        ),
        result=result,
        tokens=tokens if tokens is not None else ["tok"],
        callback=callback,
    )
    return StruggleInterventionPipeline.__new__(StruggleInterventionPipeline), state


def test_post_agent_hook_decide_maps_fields_and_carries_tokens():
    """post_agent_hook is the only place that maps a GateResult onto the status DTO and calls
    finish(). Reading self.tokens instead of the state's drops the usage without raising.
    """
    pipeline, state = _hook_state(
        '{"action":"active","message":"Look at line 50.","confidence":0.9,'
        '"anchor":{"file":"src/A.java","line":50},"inlineHint":"still returns -1",'
        '"rationale":"stub"}',
        "decide",
        tokens=["usage-1"],
    )
    out = pipeline.post_agent_hook(state)

    assert out == "Look at line 50."
    assert state.callback.status.action == "active"
    assert state.callback.status.anchor_file == "src/A.java"
    assert state.callback.status.anchor_line == 50
    assert state.callback.status.inline_hint == "still returns -1"
    assert state.callback.status.rationale == "stub"
    _, kwargs = state.callback.finish.call_args
    assert kwargs["result"] == "Look at line 50."
    assert kwargs["confidence"] == 0.9
    # finish() is terminal, so it must carry the accumulated usage from the state.
    assert kwargs["tokens"] == ["usage-1"]


def test_post_agent_hook_confirm_close_maps_fields_and_carries_tokens():
    pipeline, state = _hook_state(
        '{"resolved":true,"closingSentence":"Nice, the helper is gone.",'
        '"episodeLabel":"missing helper method"}',
        "confirm_close",
        tokens=["usage-2"],
    )
    out = pipeline.post_agent_hook(state)

    assert out == "Nice, the helper is gone."
    assert state.callback.status.resolved is True
    assert state.callback.status.closing_sentence == "Nice, the helper is gone."
    assert state.callback.status.episode_label == "missing helper method"
    _, kwargs = state.callback.finish.call_args
    assert kwargs["tokens"] == ["usage-2"]


def test_post_agent_hook_help_request_fails_run_on_unusable_output():
    """The help_request template forbids "silent", so collapsing an unparseable answer into the
    silent fail-safe reaches Artemis as result==null and is delivered as silentDecide: the ask
    vanishes with no hint and no error. It must fail the run instead.
    """
    pipeline, state = _hook_state("the model rambled without json", "help_request")
    out = pipeline.post_agent_hook(state)

    assert out == ""
    state.callback.finish.assert_not_called()
    args, kwargs = state.callback.fail.call_args
    assert "unusable model output" in args[0]
    # fail() is terminal, so it carries the accumulated usage itself.
    assert kwargs["tokens"] == ["tok"]
    assert state.callback.status.rationale == "unparseable model output"


def test_post_agent_hook_help_request_rejects_a_contract_violating_silent():
    """Well-formed JSON does not make "silent" admissible here: the help_request template answers
    only in ambient/active, and honouring it delivers the same empty completion the parse-failure
    guard above exists to prevent, on the one path where the student explicitly asked. Artemis
    tolerating an incoming silent is a defensive net there, not a licence to emit one here.
    """
    pipeline, state = _hook_state(
        '{"action":"silent","message":null,"confidence":0.4,"rationale":"already said",'
        '"anchor":{"file":"src/A.java","line":50},"inlineHint":"still returns -1"}',
        "help_request",
    )
    out = pipeline.post_agent_hook(state)

    assert out == ""
    state.callback.finish.assert_not_called()
    # The filled anchor and hint reach nothing: this intent refuses before the status mapping.
    assert state.callback.status.anchor_file is None
    assert state.callback.status.inline_hint is None
    args, kwargs = state.callback.fail.call_args
    assert "this intent forbids" in args[0]
    assert kwargs["tokens"] == ["tok"]
    # the model's own reason still reaches the log
    assert state.callback.status.rationale == "already said"


def test_post_agent_hook_decide_still_honours_a_deliberate_silent():
    """The counter-case: on the unsolicited intent, silence is a legitimate decision."""
    pipeline, state = _hook_state(
        '{"action":"silent","message":null,"confidence":0.4,"rationale":"already said"}',
        "decide",
    )
    pipeline.post_agent_hook(state)

    state.callback.fail.assert_not_called()
    state.callback.finish.assert_called_once()
    assert state.callback.status.action == "silent"


def test_parse_gate_result_marks_only_fail_safes_as_parse_failures():
    assert parse_gate_result("no json here").parse_failed is True
    assert parse_gate_result('{"action":"nope"}').parse_failed is True
    assert parse_gate_result('{"action":"active","message":""}').parse_failed is True
    assert parse_gate_result(None).parse_failed is True
    assert (
        parse_gate_result('{"action":"silent","confidence":0.3}').parse_failed is False
    )


def test_inline_hint_keeps_a_cue_whose_word_boundary_sits_at_the_limit():
    """
    A cue of 59 characters plus a space plus another word has a valid 60-char truncation.
    Searching only the first 59 characters found no space and dropped the cue entirely.
    """
    cue = "x" * 59 + " next"
    out = _gate(
        '{"action":"ambient","message":"m","confidence":0.5,'
        '"anchor":{"file":"Sort.java","line":42},"inlineHint":"' + cue + '"}'
    ).inline_hint
    assert out == "x" * 59 + "…"
    assert len(out) == INLINE_HINT_MAX_CHARS


def test_struggle_pipeline_is_registered_for_health_checks():
    """Without an entry in Features and PIPELINE_BY_FEATURE, check_pipelines_health() never
    evaluates the pipeline: health reports every pipeline valid while a missing or broken LLM
    config surfaces only at request time.
    """
    assert Features.STRUGGLE_INTERVENTION in PIPELINE_BY_FEATURE
    assert (
        PIPELINE_BY_FEATURE[Features.STRUGGLE_INTERVENTION]
        is StruggleInterventionPipeline
    )
    # evaluate_feature() reads these off the class; without them the entry is inert.
    assert StruggleInterventionPipeline.PIPELINE_ID == "struggle_intervention_pipeline"
    assert StruggleInterventionPipeline.VARIANT_DEFS


def test_prompts_do_not_promise_code_tools_without_a_submission():
    """get_tools registers the code/build/feedback tools only `if submission is not None`, and
    Artemis sends no submission before the first one, so a prompt that promises them regardless
    makes the REQUIRED anchor+inlineHint impossible.
    """
    pipeline = StruggleInterventionPipeline()
    for template in (pipeline.system_prompt_template, pipeline.help_request_template):
        rendered = template.render(
            course_name="Algorithms",
            signal_summary="primary boundary: FM; severity sBase=0.80; path=armed.",
            episode=None,
        )
        assert "WHEN the student has already" in rendered
        assert "those code and build tools are simply absent" in rendered
    decide = pipeline.system_prompt_template.render(
        course_name="Algorithms",
        signal_summary="primary boundary: FM; severity sBase=0.80; path=armed.",
        episode=None,
    )
    assert "Without those tools you cannot name a line" in decide


def test_confirm_close_supplies_its_own_fallback_and_marks_the_close_degraded():
    """A resolved close owes the student a sentence and a fold label. Artemis substitutes its own
    text when they are missing, but that is a separate repo on its own deployment schedule and no
    part of this contract. Refusing the close would turn a formatting failure into a
    substantively unresolved episode, so it stands and is marked degraded instead of entering the
    evaluation data as an ordinary RECOVERED.
    """
    for raw in (
        '{"resolved":true}',
        '{"resolved":true,"closingSentence":"   ","episodeLabel":""}',
    ):
        r = parse_confirm_close_result(raw)
        assert r.resolved is True
        assert r.degraded is True
        assert r.closing_sentence == CONFIRM_CLOSE_FALLBACK_SENTENCE
        assert r.episode_label == CONFIRM_CLOSE_FALLBACK_LABEL
        assert r.rationale == DEGRADED_CLOSE_RATIONALE


def test_confirm_close_degraded_marker_keeps_a_model_rationale():
    r = parse_confirm_close_result('{"resolved":true,"rationale":"tests are green"}')
    assert r.degraded is True
    assert DEGRADED_CLOSE_RATIONALE in r.rationale
    assert "tests are green" in r.rationale


def test_confirm_close_complete_response_is_not_degraded():
    r = parse_confirm_close_result(
        '{"resolved":true,"closingSentence":"The helper is gone.","episodeLabel":"missing helper"}'
    )
    assert r.degraded is False
    assert r.closing_sentence == "The helper is gone."
    assert r.episode_label == "missing helper"
    assert r.rationale is None


def test_help_request_prompt_offers_no_silent_escape_without_tools():
    """The no-submission fallback must not hand back the escape the NEVER SILENT contract closes
    further down in the same template.
    """
    pipeline = StruggleInterventionPipeline()
    rendered = pipeline.help_request_template.render(
        course_name="Algorithms",
        signal_summary="primary boundary: STATE; severity sBase=0.90; path=e6.",
        episode=None,
    )
    assert "Missing tools never buy you a way out of answering" in rendered
    assert "send them to a human tutor" in rendered
    assert "chat history alone or stay `silent`" not in rendered
    assert "NEVER SILENT" in rendered


def test_parse_gate_result_rejects_boolean_confidence():
    """bool is a subclass of int, so float(True) is 1.0 and `"confidence": true` would reach
    Artemis as maximum certainty, clearing its threshold for an unsolicited intervention.
    """
    for raw in (
        '{"action":"active","message":"m","confidence":true}',
        '{"action":"active","message":"m","confidence":false}',
    ):
        assert parse_gate_result(raw).confidence == 0.0
    # a real number still passes through untouched
    assert (
        parse_gate_result(
            '{"action":"active","message":"m","confidence":0.87}'
        ).confidence
        == 0.87
    )


def test_a_crashing_run_still_reports_the_usage_it_accrued():
    """The outer catch in __call__ is the one failure path that runs outside the agent's execution
    state, so it can only reach self.tokens. Without that binding a crashed run reports an empty
    list and the spend of every LLM call it made disappears from the accounting.
    """
    pipeline = StruggleInterventionPipeline.__new__(StruggleInterventionPipeline)
    pipeline.tokens = []
    spent = SimpleNamespace(num_input_tokens=120, num_output_tokens=40)

    def crash_after_spending(state):
        state.tokens.append(spent)
        raise RuntimeError("model call blew up mid-run")

    # Everything before the agent loop is stubbed out, as in test_chat_latency_ordering.py.
    pipeline.prepare_state = lambda state: None
    pipeline.build_system_message = lambda state: "system prompt"
    pipeline.get_tools = lambda state: []
    pipeline.create_tracing_context = lambda dto, variant: None
    pipeline.should_stream_agent_response = lambda state: False
    pipeline.execute_agent = crash_after_spending

    callback = MagicMock()
    variant = MagicMock()
    variant.id = "default"
    variant.model.return_value = "some-model-id"
    dto = SimpleNamespace(chat_history=[], settings=None, intent="decide")

    with (
        patch("iris.pipeline.abstract_agent_pipeline.VectorDatabase"),
        patch("iris.pipeline.abstract_agent_pipeline.MemirisWrapper"),
        patch("iris.pipeline.abstract_agent_pipeline.LlmRequestHandler"),
        patch("iris.pipeline.abstract_agent_pipeline.IrisLangchainChatModel"),
    ):
        pipeline(dto, variant, callback)

    assert callback.fail.call_args.kwargs["tokens"] == [spent]


def test_a_silent_decision_carries_no_gutter_payload():
    """The anchor and the inline hint reach the student without a chat message, drawn in the gutter
    of the file they are editing, so a model that answers `silent` and fills them anyway
    contradicts itself and the decision has to win.
    """
    g = parse_gate_result(
        '{"action":"silent","confidence":0.4,"rationale":"too early",'
        '"anchor":{"file":"src/A.java","line":50},"inlineHint":"still returns -1"}'
    )
    assert g.action == "silent"
    assert g.anchor is None
    assert g.inline_hint is None
    # The rest of the decision survives; only the student-visible payload is dropped.
    assert g.confidence == 0.4
    assert g.rationale == "too early"


def test_a_silent_decision_maps_no_gutter_payload_onto_the_status():
    """post_agent_hook is what copies these onto the status DTO, so the guard has to hold there too."""
    pipeline, state = _hook_state(
        '{"action":"silent","confidence":0.4,'
        '"anchor":{"file":"src/A.java","line":50},"inlineHint":"still returns -1"}',
        "decide",
    )
    pipeline.post_agent_hook(state)

    assert state.callback.status.action == "silent"
    assert state.callback.status.anchor_file is None
    assert state.callback.status.anchor_line is None
    assert state.callback.status.inline_hint is None


def test_a_close_that_names_a_gate_action_is_refused():
    """An answer claiming a surface level and a finished episode at once answered the wrong
    contract and says nothing trustworthy about either. Refusing costs one more round with the
    episode open; honouring it would file the episode as recovered.
    """
    cc = parse_confirm_close_result(
        '{"resolved":true,"action":"silent","closingSentence":"Nice work.",'
        '"episodeLabel":"Loop fixed","rationale":"tests pass"}'
    )

    assert cc.resolved is False
    assert cc.closing_sentence is None
    assert cc.episode_label is None
    # The marker and the model's own reason both reach the evaluation log.
    assert MIXED_SCHEMA_CLOSE_RATIONALE in cc.rationale
    assert "tests pass" in cc.rationale


def test_an_invented_extra_field_still_closes():
    """The fingerprint is deliberately narrow: only the gate's own three action values."""
    cc = parse_confirm_close_result(
        '{"resolved":true,"action":"close","closingSentence":"Nice work.",'
        '"episodeLabel":"Loop fixed"}'
    )

    assert cc.resolved is True
    assert cc.closing_sentence == "Nice work."


def _anchored(file: str, line, hint: str = "off-by-one?") -> str:
    return (
        '{"action":"ambient","message":"m","confidence":0.5,'
        f'"anchor":{{"file":{json.dumps(file)},"line":{json.dumps(line)}}},'
        f'"inlineHint":{json.dumps(hint)}}}'
    )


def test_an_anchor_that_points_nowhere_is_dropped_with_its_cue():
    """The client draws the cue at the anchor, so a location it cannot resolve turns the pair into
    payload nothing renders, and a line the model never saw is one it cannot have verified. Each
    of these is checked against the snapshot the run was given.
    """
    for path, line, why in [
        ("", 5, "empty path"),
        ("   ", 5, "blank path"),
        ("/etc/passwd", 5, "absolute path"),
        ("../secrets.txt", 5, "escapes the repository"),
        ("src/./A.java", 5, "dot segment"),
        ("src//A.java", 5, "empty segment"),
        ("Sort.java/", 5, "trailing separator"),
        ("Missing.java", 5, "file the run never saw"),
        ("Sort.java", 0, "line before the first"),
        ("Sort.java", -3, "negative line"),
        ("Sort.java", 61, "line past the end of the file"),
        ("Sort.java", True, "boolean masquerading as a line"),
    ]:
        gate = _gate(_anchored(path, line))
        assert gate.anchor is None, why
        assert gate.inline_hint is None, why
        # Only the gutter pair is refused; the decision itself stands.
        assert gate.action == "ambient", why
        assert gate.message == "m", why


def test_the_last_line_of_a_file_is_a_valid_anchor():
    gate = _gate(_anchored("Sort.java", 60))
    assert gate.anchor == ("Sort.java", 60)
    assert gate.inline_hint == "off-by-one?"


def test_an_empty_file_has_no_line_to_anchor():
    """`splitlines()` of an empty file is empty, so even line 1 is a line the run never saw."""
    gate = parse_gate_result(_anchored("Empty.java", 1), {"Empty.java": ""})
    assert gate.anchor is None
    assert gate.inline_hint is None


def test_outer_whitespace_around_the_path_is_forgiven():
    """Forgiven, not rewritten: a path is never turned into a different one that happens to fit."""
    gate = _gate(_anchored("  Sort.java  ", 42))
    assert gate.anchor == ("Sort.java", 42)


def test_without_a_repository_no_anchor_is_forwarded():
    """No submission means the run had no code tools either, so a location it names is one it could
    not have confirmed; the prompt asks for both fields to be null in exactly that case.
    """
    gate = parse_gate_result(_anchored("Sort.java", 42))
    assert gate.anchor is None
    assert gate.inline_hint is None
    assert gate.action == "ambient"


def test_a_cue_without_an_anchor_is_dropped():
    """Half a pair: the text has no place to be drawn."""
    gate = _gate(
        '{"action":"ambient","message":"m","confidence":0.5,"inlineHint":"off-by-one?"}'
    )
    assert gate.inline_hint is None


def test_an_anchor_without_a_cue_is_dropped():
    """The other half: a marker that points somewhere without saying why."""
    for raw in (
        '{"action":"ambient","message":"m","confidence":0.5,'
        '"anchor":{"file":"Sort.java","line":42}}',
        '{"action":"ambient","message":"m","confidence":0.5,'
        '"anchor":{"file":"Sort.java","line":42},"inlineHint":7}',
    ):
        assert _gate(raw).anchor is None


def test_the_hook_checks_the_anchor_against_the_runs_own_snapshot():
    """The hook is what hands the snapshot to the parser; without that argument every anchor passes
    unchecked and nothing else on this path notices.
    """
    pipeline, state = _hook_state(
        '{"action":"ambient","message":"m","confidence":0.5,'
        '"anchor":{"file":"NeverSeen.java","line":5},"inlineHint":"off-by-one?"}',
        "decide",
    )
    pipeline.post_agent_hook(state)

    assert state.callback.status.anchor_file is None
    assert state.callback.status.anchor_line is None
    assert state.callback.status.inline_hint is None
    # A refused anchor costs the gutter cue, not the hint itself.
    assert state.callback.status.action == "ambient"
    assert state.callback.finish.call_args.kwargs["result"] == "m"
