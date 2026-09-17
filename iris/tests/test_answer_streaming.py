"""Unit tests for the streaming answer contract: the !none! sentinel, the
sentinel-gating stream handler, and the parameterized partial-result sender."""

from iris.domain.status.global_search_status_update_dto import (
    GlobalSearchStatusUpdateDTO,
)
from iris.domain.status.run_state_dto import RunStateEnum
from iris.pipeline.global_search_pipeline import (
    _SentinelGateStreamHandler,
    parse_answer_response,
)
from iris.web.status.partial_result_sender import PartialResultSender


class TestSentinelParsing:
    """The plain-text no-answer sentinel maps to the null answer state."""

    def test_exact_sentinel_is_no_answer(self):
        answer, used = parse_answer_response("!none!", 3)
        assert answer is None
        assert used == set()

    def test_sentinel_with_whitespace_and_period_is_no_answer(self):
        answer, used = parse_answer_response("  !none!.\n", 3)
        assert answer is None
        assert used == set()

    def test_plain_text_with_markers_uses_marker_attribution(self):
        answer, used = parse_answer_response("The quiz is worth 4 points.[2]", 3)
        assert answer == "The quiz is worth 4 points.[2]"
        assert used == {1}

    def test_plain_text_without_markers_attaches_all_sources(self):
        answer, used = parse_answer_response("A markerless plain answer.", 3)
        assert answer == "A markerless plain answer."
        assert used == {0, 1, 2}


class TestSentinelGateStreamHandler:
    """Deltas are held until the output can no longer be the sentinel."""

    def collect(self):
        chunks: list = []
        return chunks, _SentinelGateStreamHandler(chunks.append)

    def test_normal_answer_streams_through(self):
        chunks, gate = self.collect()
        gate("The **RNN")
        gate(" quiz** is due")
        assert chunks == ["The **RNN", " quiz** is due"]

    def test_sentinel_is_never_streamed(self):
        chunks, gate = self.collect()
        gate("!no")
        gate("ne!")
        assert not chunks

    def test_sentinel_prefix_releases_once_it_diverges(self):
        chunks, gate = self.collect()
        gate("!n")  # could still become !none!
        assert not chunks
        gate("ice work is rewarded")  # diverged — buffered text flushes
        assert chunks == ["!nice work is rewarded"]
        gate(" indeed")
        assert chunks == ["!nice work is rewarded", " indeed"]

    def test_reset_delta_propagates_only_after_streaming_started(self):
        chunks, gate = self.collect()
        gate(None)
        assert not chunks  # nothing streamed yet — nothing to reset
        gate("An answer")
        gate(None)
        assert chunks == ["An answer", None]


class TestPartialResultSenderFactory:
    """Payload construction with and without an injected status DTO."""

    def test_global_search_payload_uses_the_injected_dto(self):
        sender = PartialResultSender(
            "http://unused",
            "run",
            status_dto_factory=lambda text, seq: GlobalSearchStatusUpdateDTO(
                run_state=RunStateEnum.RUNNING,
                partial_result=text,
                partial_seq=seq,
            ),
        )
        sender.on_delta("Partial answer.[1]")
        payload_info = sender._next_payload()  # pylint: disable=protected-access
        assert payload_info is not None
        payload, text, *_ = payload_info
        assert text == "Partial answer.[1]"
        assert payload["partialResult"] == "Partial answer.[1]"
        assert payload["partialSeq"] == 1
        assert payload["runState"] == "RUNNING"
        assert "answer" not in payload  # exclude_none keeps the draft minimal

    def test_default_factory_still_produces_the_chat_payload(self):
        sender = PartialResultSender("http://unused", "run")
        sender.on_delta("token")
        payload_info = sender._next_payload()  # pylint: disable=protected-access
        assert payload_info is not None
        payload, *_ = payload_info
        assert payload["partialResult"] == "token"
