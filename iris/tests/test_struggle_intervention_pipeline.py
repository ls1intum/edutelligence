from iris.domain.struggle.episode_dto import EpisodeDTO, EpisodeHintDTO
from iris.pipeline.struggle_intervention_pipeline import (
    StruggleInterventionPipeline,
    parse_confirm_close_result,
    parse_gate_result,
    parse_stale_check_result,
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
    r = parse_confirm_close_result('{"resolved": false, "rationale": "empty-list case still trips"}')
    assert r.resolved is False
    assert r.closing_sentence is None
    assert r.episode_label is None
    assert r.rationale == "empty-list case still trips"


def test_parse_confirm_close_malformed_fails_closed_to_not_resolved():
    r = parse_confirm_close_result("not json")
    assert r.resolved is False


# ---------------------------------------------------------------------------
# parse_stale_check_result
# ---------------------------------------------------------------------------


def test_parse_stale_check_ask_true_with_question():
    r = parse_stale_check_result('{"ask": true, "question": "Did you get past the empty-list case?"}')
    assert r.ask is True
    assert r.question == "Did you get past the empty-list case?"


def test_parse_stale_check_ask_false_is_noop():
    r = parse_stale_check_result('{"ask": false}')
    assert r.ask is False
    assert r.question is None


def test_parse_stale_check_ask_true_without_question_fails_closed_to_noop():
    # ask=true but no usable question -> treat as noop so the client never posts an empty ask
    r = parse_stale_check_result('{"ask": true}')
    assert r.ask is False


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
        signal_summary="primary boundary: FM; severity v=0.82; path=armed; dominant components: typing=0.90; recent v-trajectory: (t=60,v=0.80); session 300s.",
        episode=episode,
    )
    assert "i < n" in rendered, "angle bracket in hint text was HTML-escaped"
    assert "List<String>" in rendered, "angle bracket in hint text was HTML-escaped"
    assert "& reset" in rendered, "ampersand in hint text was HTML-escaped"
    assert "&lt;" not in rendered, "HTML escape entity found in LLM prompt"
    assert "&amp;" not in rendered, "HTML escape entity found in LLM prompt"
