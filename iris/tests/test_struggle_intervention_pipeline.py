from types import SimpleNamespace
from unittest.mock import MagicMock

from iris.domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from iris.domain.struggle.episode_dto import EpisodeDTO, EpisodeHintDTO
from iris.domain.struggle.struggle_signal_dto import StruggleSignal
from iris.pipeline.struggle_intervention_pipeline import (
    INLINE_HINT_MAX_CHARS,
    StruggleInterventionPipeline,
    parse_confirm_close_result,
    parse_gate_result,
    summarize_signal,
)
from iris.web.routers.health.Pipelines.features import Features
from iris.web.routers.health.Pipelines.registery import PIPELINE_BY_FEATURE


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
    # json.loads accepts NaN/Infinity; the finite guard maps them to 0.0 so they
    # never reach the wire (a NaN/Infinity would break the JSON callback POST).
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
    g = parse_gate_result(raw)
    assert g.anchor == {"file": "Sort.java", "line": 42}
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
    """
    Regression for the autoescape=select_autoescape(["html","xml","j2"]) bug.

    When "j2" was in the enabled_extensions list Jinja treated every .j2 file
    as an HTML template and escaped {{ }} values, so a hint like
    "is the bound i < n or List<String> & reset" would reach the LLM as
    "is the bound i &lt; n or List&lt;String&gt; &amp; reset" -- corrupting the prompt.

    This test renders the confirm_close system-prompt template with a hint
    carrying angle brackets and a raw ampersand, then asserts the characters
    survive unchanged in the rendered prompt.
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
    """Fix A + B5: objective test results are decisive and the live-vs-submitted diff tool is explained."""
    pipeline = StruggleInterventionPipeline()
    rendered = pipeline.confirm_close_template.render(
        course_name="Algorithms",
        signal_summary="primary boundary: FM; severity sBase=0.82; path=armed.",
        episode=None,
    )
    # Fix A: weigh objective evidence first, do not default to doubt; passing tests are decisive.
    assert "do not default to doubt" in rendered
    assert "PASS" in rendered
    # B5: live-vs-submitted semantics + the diff tool, naming only callable tools.
    # (substrings kept within single wrapped lines so the assertions survive prompt re-wrapping)
    assert "local_vs_submitted_diff" in rendered
    assert "SUBMITTED build" in rendered
    assert "get_feedbacks" in rendered


def test_decide_prompt_renders_prior_episode_hints_with_silent_rule():
    """
    Episode dedup: the decide prompt must show the hints already delivered in this
    episode and carry the hard rule that a same-diagnosis nudge (reworded or not)
    means action "silent". Without this the model rewords the same hint every
    re-alert (observed live: 4x the same stub diagnosis at 0.88-0.95 confidence).
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
    """
    Cross-episode dedup: the hard same-diagnosis->silent rule must be present even for
    a fresh episode (no hints yet), because earlier episodes' hints reach the model only
    as "(proactive hint, ...)"-tagged chat-history messages. The recovery EXCEPTION keeps
    a genuinely returned problem hintable again.
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


def _tool_state(intent, submission):
    dto = SimpleNamespace(
        programming_exercise_submission=submission,
        programming_exercise=None,
        intent=intent,
    )
    return SimpleNamespace(dto=dto, callback=MagicMock())


def test_local_vs_submitted_diff_tool_registered_for_decide_and_confirm_close():
    """
    The diff tool is dual use: on confirm_close it verifies a fix, on decide it reveals the code
    region the student is actively editing (focus). It must be present for BOTH intents whenever a
    submission exists (previously it was gated to confirm_close only).
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
    """
    The decide prompt must carry the focus/redirect bias: use local_vs_submitted_diff (when
    available) to find the region the student is editing, prefer to help there when it is itself
    failing, redirect to another method only when the focus region looks correct AND explicitly
    frame the redirect, and fall back when there is no focus signal. The bias must be SOFT and
    subordinate to the existing no-repeat and current-code-confirmation rules.
    """
    pipeline = StruggleInterventionPipeline()
    rendered = pipeline.system_prompt_template.render(
        course_name="Algorithms",
        signal_summary="primary boundary: STATE; severity sBase=1.00; path=armed.",
        episode=None,
    )
    # uses the diff tool for focus
    assert "local_vs_submitted_diff" in rendered
    assert "focus region" in rendered
    # prefer help-where-they-are; do not redirect off a still-failing focus region
    assert "do NOT redirect to a different method" in rendered
    # a legitimate redirect must be framed as such
    assert "MUST frame it as a redirect" in rendered
    # explicit fallback when there is no focus signal
    assert "No focus signal" in rendered
    # subordinate to the existing rules, and soft
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
    # pull leans reticent, push is willing to reach out, and the two render different presence text
    assert "reticent" in pull
    assert 'reserve "active"' in pull
    assert "reach-out mode" in push
    assert pull != push
    # tone-only: neither mode relaxes the hard rules
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
# Regression for a live spoiler: after three escalating follow-ups the gate returned
# the implementation in prose ("scan 0..i-1, keep lo/hi, record mid when it fits...").
# The old help-request prompt asked for "one notch MORE concrete than the last" with no
# absolute ceiling, and none of the three struggle prompts defined what a spoiler is --
# the decide prompt only pointed at "the same no-solution rules as the normal exercise
# chat", which the struggle pipeline never loads.
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
    """
    decide and help_request may emit a hint, so both carry the contract and the ladder.
    confirm_close may not hint at all, so it carries the narrow no-new-help block
    instead -- giving it the hint contract would license exactly the rung-3 output it
    must never produce.
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


def test_contract_names_the_prose_spoiler_classes():
    """
    The observed spoiler carried no code fence: it was an algorithm plus its bounds and
    state variables, written as prose. A generic "never give the solution" does not catch
    that, so the contract has to name those classes explicitly.
    """
    pipeline = StruggleInterventionPipeline()
    rendered = _render(pipeline.help_request_template, _episode_with(1))

    assert "operator or condition replacement" in rendered
    # Reciting the required behaviour is rung 3, so the unconditional Allowed list must not
    # hand it out at every rung - that collapses the gap between rung 2 and rung 3.
    assert "Reciting what they say is rung 3" in rendered
    assert "The behaviour that spot must have, but only as far as" not in rendered
    assert "Index ranges or loop bounds" in rendered
    assert "algorithm or data structure to apply" in rendered
    assert "State-variable names together with their update rule" in rendered
    assert "ordered sequence of steps whose endpoint is working code" in rendered
    assert "Writing code the student could take over as the fix" in rendered
    # The blanket rule the old help-request guardrails carried, kept verbatim so it does not
    # depend on a reader stitching the individual classes above together.
    assert "NEVER give the full or near-full solution" in rendered
    assert "NEVER write the code for them" in rendered
    # The contract governs the inline gutter cue too, not just the chat message.
    assert "in `message` and `inlineHint`" in rendered


def test_help_request_ladder_rises_to_three_and_then_stops():
    """
    The ceiling is the whole point: concreteness rises to rung 3 and never past it,
    however often the student asks. The count is every delivered hint (an unsolicited
    ambient->active escalation appends one too, slotManager.escalate), so prior>=2
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
    """
    NEVER SILENT and the ceiling pull in opposite directions at rung 3. If the model has
    to resolve that tension itself it resolves it by spoiling, so the prompt has to hand
    it explicit non-spoiler exits.
    """
    pipeline = StruggleInterventionPipeline()
    rendered = _render(pipeline.help_request_template, _episode_with(2))

    assert "NEVER SILENT" in rendered
    assert "including at rung 3" in rendered
    assert "counter-example" in rendered
    assert "ask a human tutor" in rendered
    # The tutor referral is the one exit that is not itself a hint, so the prompt has to say
    # it counts as an answer -- otherwise NEVER SILENT pushes the model past the ceiling.
    assert "satisfies NEVER SILENT" in rendered
    # The retired unbounded-escalation instruction must not come back.
    assert "one notch MORE concrete than the last" not in rendered


def test_decide_is_capped_at_rung_two_and_drops_the_dead_chat_reference():
    """
    An unsolicited nudge stops at rung 2; rung 3 is reserved for a hint the student asked
    for. The old pointer at the exercise-chat rules was dead: the struggle pipeline builds
    its own system message and never loads chat_system_prompt.j2.
    """
    pipeline = StruggleInterventionPipeline()
    for prior, expected in ((0, 1), (1, 2), (2, 2), (5, 2)):
        rendered = _render(pipeline.system_prompt_template, _episode_with(prior))
        assert f"You are answering at rung {expected}." in rendered
        assert "Never use rung 3 for this unsolicited check" in rendered

    rendered = _render(pipeline.system_prompt_template, _episode_with(0))
    assert "Same no-solution rules as the normal exercise chat" not in rendered
    # decide may legitimately stay silent and help_request may never be silent, so the
    # shared contract must bind only the content of a hint, never whether one is emitted.
    assert "do emit a hint, you name WHERE the problem is" in rendered
    assert 'respond with action "silent"' in rendered

    # The same contract text must not push help_request toward silence, which is forbidden there.
    help_rendered = _render(pipeline.help_request_template, _episode_with(0))
    assert "do emit a hint, you name WHERE the problem is" in help_rendered
    assert "return `silent`" not in help_rendered


def test_confirm_close_constrains_both_student_visible_fields():
    """
    closingSentence is not the only text the student sees: episodeLabel is forwarded on a
    resolved close and rendered as the fold label (serverFrameHandler -> foldEpisode), so
    both need the same what-not-how limit. rationale, by contrast, never leaves Pyris --
    Artemis' StruggleInterventionEventDTO has no such field -- so the prompt must not
    describe it as student-facing.
    """
    pipeline = StruggleInterventionPipeline()
    rendered = _render(pipeline.confirm_close_template, _episode_with(1))

    assert "`closingSentence` and" in rendered
    assert "`episodeLabel` are the only student-visible fields" in rendered
    assert "never restate HOW it works or" in rendered
    assert "for logging only; it is NOT shown to the student" in rendered
    assert "shown to the student when NOT resolved" not in rendered


def test_length_budget_is_tighter_for_the_unsolicited_nudge():
    """
    An unsolicited nudge interrupts, so it gets the smaller budget; a hint the student asked
    for may take more room but still has a hard ceiling. Without a stated ceiling the model
    keeps explaining, and a long enough explanation of a defect is the fix.
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
    """
    Regression for a live miss: the first hint after the contract shipped contained no inline
    code at all. "Code in any form ... method-call chains" reads as a ban on the markup, so the
    model spelled `ProjectPlanner.findLatestCompatible` out as prose to comply. The ban is about
    composing a fix; naming something already in the student's code has to stay marked up, or
    the reference is unscannable and the chip styling never renders.
    """
    pipeline = StruggleInterventionPipeline()

    for template in (pipeline.system_prompt_template, pipeline.help_request_template):
        rendered = _render(template, _episode_with(1))
        assert (
            "FORMAT of `message`, and this is required rather than optional" in rendered
        )
        assert "every name you point at goes in backticks" in rendered
        # The ban has to name what it targets: composed code, not markup.
        assert "Writing code the student could take over as the fix" in rendered
        # The over-broad phrasing that caused the miss must not come back.
        assert "Code in any form" not in rendered


def test_inline_hint_is_specified_and_parsed_as_plain_text():
    """
    Regression: the gutter cue arrived as "Still returns `-1` unconditionally (stub)" and the
    student saw the backticks as characters. inlineHint is drawn into the editor unfiltered, with
    no markdown pass, so the FORMAT rule that makes `message` mark up every name is exactly wrong
    here. The prompt now says so, and the parser strips regardless, because this field reaches the
    editor without anything else in between.
    """
    pipeline = StruggleInterventionPipeline()
    rendered = _render(pipeline.system_prompt_template, _episode_with(0))
    assert "FORMAT of `inlineHint` is the opposite" in rendered
    assert "no markdown pass" in rendered

    gate = parse_gate_result(
        '{"action": "ambient", "message": "look at `foo`", "confidence": 0.8,'
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


def test_inline_hint_is_clamped_to_the_gutter_budget():
    """
    The cue is drawn inline after the anchored line of the student's own code and nothing
    downstream clamps it, so an overlong one pushes that line sideways. The prompt asks for 60
    characters; this makes it true.
    """
    long_cue = "Still returns minus one unconditionally and blocks both of the DP methods below"
    gate = parse_gate_result(
        '{"action": "ambient", "message": "m", "confidence": 0.5, "inlineHint": "%s"}'
        % long_cue
    )
    assert gate.inline_hint is not None
    assert len(gate.inline_hint) <= INLINE_HINT_MAX_CHARS
    assert gate.inline_hint.endswith("…")
    # Cut at a word boundary, never mid-word.
    assert long_cue.startswith(gate.inline_hint[:-1])
    assert not gate.inline_hint[:-1].endswith(" ")

    # Exactly at the budget is untouched.
    exact = "x" * INLINE_HINT_MAX_CHARS
    assert (
        parse_gate_result(
            '{"action": "ambient", "message": "m", "confidence": 0.5, "inlineHint": "%s"}'
            % exact
        ).inline_hint
        == exact
    )

    # One long unbreakable token has no honest way to be shortened, so it is dropped rather
    # than cut mid-word; the anchor still marks the line.
    assert (
        parse_gate_result(
            '{"action": "ambient", "message": "m", "confidence": 0.5, "inlineHint": "%s"}'
            % ("y" * 90)
        ).inline_hint
        is None
    )


def _hook_state(result, intent, tokens=None):
    """A minimal AgentPipelineExecutionState stand-in for post_agent_hook.

    The pipeline is built via __new__ so no LLM/config is touched (same approach as
    test_chat_latency_ordering.py); post_agent_hook only reads dto/result/tokens/callback.
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
        dto=SimpleNamespace(intent=intent),
        result=result,
        tokens=tokens if tokens is not None else ["tok"],
        callback=callback,
    )
    return StruggleInterventionPipeline.__new__(StruggleInterventionPipeline), state


def test_post_agent_hook_decide_maps_fields_and_carries_tokens():
    """
    post_agent_hook is the only place that maps a GateResult onto the status DTO and calls
    finish(). It was untested, which is exactly where the token bug of c26e4052 lived: a
    relapse to self.tokens drops the usage without raising, so nothing would turn red.
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
    """
    A help_request was explicitly asked for and its template forbids "silent". Collapsing an
    unparseable answer into the silent fail-safe reached Artemis as result==null and was
    delivered as silentDecide: the ask vanished with no hint and no error, indistinguishable
    from a silence the model chose. It must fail the run instead.
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


def test_post_agent_hook_help_request_honours_a_deliberate_silent():
    """The counter-case: valid JSON asking for silence is a decision, not a failure."""
    pipeline, state = _hook_state(
        '{"action":"silent","message":null,"confidence":0.4,"rationale":"already said"}',
        "help_request",
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
    out = parse_gate_result(
        '{"action":"ambient","message":"m","confidence":0.5,"inlineHint":"' + cue + '"}'
    ).inline_hint
    assert out == "x" * 59 + "…"
    assert len(out) == INLINE_HINT_MAX_CHARS


def test_struggle_pipeline_is_registered_for_health_checks():
    """
    The pipeline was in the variants endpoint but in neither Features nor PIPELINE_BY_FEATURE,
    so check_pipelines_health() never evaluated it: health kept reporting all pipelines valid
    while this one's LLM config could be missing or broken, surfacing only at request time.
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
    """
    get_tools registers the code/build/feedback tools only `if submission is not None`, and
    Artemis sends none before the first submission. Both prompts claimed those tools
    unconditionally and the decide prompt then made anchor+inlineHint REQUIRED, which is
    impossible without them.
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
