import math
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Establish module import order (see note in other tests).
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import (  # noqa: E402
    IrisMessageRole,
    PyrisMessage,
)
from iris.common.token_logprob_dto import (  # noqa: E402
    TokenLogprobEntry,
    TopLogprobCandidate,
)
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.llm.request_handler.request_handler_interface import (  # noqa: E402
    RequestHandler,
)
from iris.pipeline.autonomous_tutor_pipeline import (  # noqa: E402
    AutonomousTutorPipeline,
)
from iris.pipeline.shared.self_eval_scoring import (  # noqa: E402
    SELF_EVAL_MAX_TOKENS,
    SELF_EVAL_PROMPT,
    self_eval_confidence,
    self_eval_details,
)
from iris.pipeline.shared.uncertainty_scoring import (  # noqa: E402
    DEFAULT_TOP_LOGPROBS,
)


def _entry(token, prob, candidates=()):
    return TokenLogprobEntry(
        token=token,
        logprob=math.log(prob),
        top_logprobs=[
            TopLogprobCandidate(token=t, logprob=math.log(p)) for t, p in candidates
        ],
    )


# ──────────────────────────────────────────────────────────────────────────
# Scoring: self_eval_details / self_eval_confidence
# ──────────────────────────────────────────────────────────────────────────
def test_none_and_empty_entries_return_none():
    assert self_eval_confidence(None) is None
    assert self_eval_confidence([]) is None
    assert self_eval_details(None) is None


def test_clean_yes_vs_no_is_normalized_ratio():
    entries = [_entry(" Yes", 0.9, [(" No", 0.05)])]
    assert self_eval_confidence(entries) == pytest.approx(0.9 / 0.95)


def test_variant_mass_is_summed_and_echo_not_double_counted():
    entries = [
        _entry(
            " Yes",
            0.5,
            [
                (" Yes", 0.5),  # raw echo of the chosen token — skipped
                ("Yes", 0.2),
                ("YES", 0.1),
                ("Yes.", 0.05),
                (" No", 0.1),
            ],
        )
    ]
    details = self_eval_details(entries)
    assert details.p_yes == pytest.approx(0.5 + 0.2 + 0.1 + 0.05)
    assert details.p_no == pytest.approx(0.1)
    assert details.confidence == pytest.approx(0.85 / 0.95)


def test_chosen_token_normalization_variants():
    for token in ("YES", "Yes.", " yes", "Ġyes"):
        entries = [_entry(token, 0.8, [(" No", 0.2)])]
        assert self_eval_confidence(entries) == pytest.approx(0.8)


def test_chosen_no_scores_low():
    entries = [_entry(" No", 0.85, [(" Yes", 0.1)])]
    assert self_eval_confidence(entries) == pytest.approx(0.1 / 0.95)


def test_leading_whitespace_token_is_skipped():
    entries = [
        _entry("\n\n", 0.9),
        _entry(" Yes", 0.8, [(" No", 0.1)]),
    ]
    details = self_eval_details(entries)
    assert details.decision_token == " Yes"
    assert details.confidence == pytest.approx(0.8 / 0.9)


def test_off_script_chosen_falls_back_to_candidate_mass():
    # The model sampled an off-script opener, but the Yes/No mass is visible
    # among its top-k candidates.
    entries = [_entry(" Sure", 0.4, [(" Yes", 0.3), (" No", 0.1)])]
    details = self_eval_details(entries)
    assert details.decision_token == " Sure"
    assert details.confidence == pytest.approx(0.3 / 0.4)


def test_yes_entry_preferred_over_earlier_off_script_entry():
    entries = [
        _entry("I", 0.5, [("'m", 0.3)]),
        _entry(" Yes", 0.9, [(" No", 0.05)]),
    ]
    assert self_eval_details(entries).decision_token == " Yes"


def test_no_yes_no_mass_anywhere_returns_none():
    entries = [_entry("I", 0.5, [("'m", 0.3), (" think", 0.1)])]
    assert self_eval_confidence(entries) is None


def test_only_non_content_tokens_returns_none():
    entries = [_entry("\n", 0.9), _entry("...", 0.8)]
    assert self_eval_confidence(entries) is None


def test_plain_logprob_fallback_without_candidates():
    assert self_eval_confidence([_entry(" Yes", 0.9)]) == pytest.approx(0.9)
    assert self_eval_confidence([_entry("No", 0.9)]) == pytest.approx(0.1)
    assert self_eval_confidence([_entry("Maybe", 0.9)]) is None


def test_details_expose_raw_quantities():
    details = self_eval_details([_entry("No", 0.7)])
    assert details.decision_token == "No"
    assert details.p_yes == pytest.approx(0.3)
    assert details.p_no == pytest.approx(0.7)


def test_confidence_stays_in_unit_interval():
    # Degenerate mass (probabilities summing past 1) must still clamp.
    entries = [_entry(" Yes", 0.99, [("Yes", 0.99), (" No", 0.0001)])]
    assert 0.0 <= self_eval_confidence(entries) <= 1.0


# ──────────────────────────────────────────────────────────────────────────
# Pipeline helper: AutonomousTutorPipeline._self_eval_confidence
# ──────────────────────────────────────────────────────────────────────────
class _RecordingHandler(RequestHandler):
    """RequestHandler stub that records the follow-up call it receives."""

    next_message: object = None
    calls: int = 0
    messages: object = None
    arguments: object = None
    tools: object = "unset"

    def complete(self, prompt, arguments, image=None):
        raise NotImplementedError

    def chat(self, messages, arguments, tools):
        self.calls += 1
        self.messages = messages
        self.arguments = arguments
        self.tools = tools
        return self.next_message

    def embed(self, text):
        raise NotImplementedError

    def bind_tools(self, tools):
        return self


def _eval_reply(entries):
    return PyrisMessage(
        sender=IrisMessageRole.ASSISTANT,
        contents=[TextMessageContentDTO(textContent="Yes")],
        token_logprob_entries=entries,
    )


def _fake_state(handler, result="The answer is 42."):
    answer_entries = [_entry(" answer", 0.9)]
    llm = SimpleNamespace(
        model_name="gpt-test",
        request_handler=handler,
        last_token_logprobs=[-0.1],
        last_token_logprob_entries=answer_entries,
    )
    return SimpleNamespace(llm=llm, result=result, use_logprob_confidence=True)


def _run_helper(state):
    pipeline = AutonomousTutorPipeline()
    with patch.object(
        AutonomousTutorPipeline, "build_system_message", return_value="SYSTEM PROMPT"
    ):
        return pipeline._self_eval_confidence(state)  # pylint: disable=protected-access


def test_helper_sends_system_assistant_user_conversation():
    handler = _RecordingHandler()
    handler.next_message = _eval_reply([_entry(" Yes", 0.9, [(" No", 0.05)])])
    state = _fake_state(handler)

    confidence = _run_helper(state)

    assert confidence == pytest.approx(0.9 / 0.95)
    assert handler.calls == 1
    assert handler.tools is None
    roles = [m.sender for m in handler.messages]
    assert roles == [
        IrisMessageRole.SYSTEM,
        IrisMessageRole.ASSISTANT,
        IrisMessageRole.USER,
    ]
    assert handler.messages[0].contents[0].text_content == "SYSTEM PROMPT"
    assert handler.messages[1].contents[0].text_content == state.result
    assert handler.messages[2].contents[0].text_content == SELF_EVAL_PROMPT


def test_helper_completion_arguments():
    handler = _RecordingHandler()
    handler.next_message = _eval_reply([_entry(" Yes", 0.9)])
    _run_helper(_fake_state(handler))

    args = handler.arguments
    assert args.temperature == 0.0
    assert args.logprobs is True
    assert args.top_logprobs == DEFAULT_TOP_LOGPROBS
    assert args.max_tokens == SELF_EVAL_MAX_TOKENS
    assert args.stream_handler is None


def test_helper_does_not_clobber_answer_logprobs():
    # The follow-up must bypass the langchain wrapper so the answer's captured
    # logprobs (read later by _estimate_confidence) survive the probe.
    handler = _RecordingHandler()
    handler.next_message = _eval_reply([_entry(" Yes", 0.9)])
    state = _fake_state(handler)
    answer_entries = state.llm.last_token_logprob_entries
    answer_floats = state.llm.last_token_logprobs

    _run_helper(state)

    assert state.llm.last_token_logprob_entries is answer_entries
    assert state.llm.last_token_logprobs is answer_floats


def test_helper_returns_none_without_result():
    handler = _RecordingHandler()
    state = _fake_state(handler, result="")
    assert _run_helper(state) is None
    assert handler.calls == 0


def test_helper_returns_none_outside_logprob_mode():
    handler = _RecordingHandler()
    state = _fake_state(handler)
    state.use_logprob_confidence = False
    assert _run_helper(state) is None
    assert handler.calls == 0


def test_helper_returns_none_without_llm():
    handler = _RecordingHandler()
    state = _fake_state(handler)
    state.llm = None
    assert _run_helper(state) is None
    assert handler.calls == 0


def test_helper_swallows_handler_errors():
    class _ExplodingHandler(_RecordingHandler):
        def chat(self, messages, arguments, tools):
            raise RuntimeError("boom")

    state = _fake_state(_ExplodingHandler())
    assert _run_helper(state) is None
