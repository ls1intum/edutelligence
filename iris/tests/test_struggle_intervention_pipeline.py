from types import SimpleNamespace
from unittest.mock import MagicMock

from iris.domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from iris.domain.struggle.episode_dto import EpisodeDTO, EpisodeHintDTO
from iris.domain.struggle.struggle_signal_dto import StruggleSignal
from iris.pipeline.struggle_intervention_pipeline import (
    StruggleInterventionPipeline,
    parse_confirm_close_result,
    parse_gate_result,
    summarize_signal,
)


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
