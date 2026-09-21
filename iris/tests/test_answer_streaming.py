"""Unit tests for the streaming answer contract: the !none! sentinel, the
sentinel-gating stream handler, and the parameterized partial-result sender."""

# pylint: disable=protected-access

from types import SimpleNamespace

from iris.domain.search.global_search_dto import CourseInfo, EntitySourceDTO
from iris.domain.status.global_search_status_update_dto import (
    GlobalSearchStatusUpdateDTO,
)
from iris.domain.status.run_state_dto import RunStateEnum
from iris.pipeline.global_search_pipeline import (
    GlobalSearchPipeline,
    SearchIntent,
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

    def test_sentinel_appended_after_an_explanation_is_still_no_answer(self):
        # The prompt says write the sentinel ALONE ("Do NOT write any message explaining
        # why"), but the model sometimes violates that and appends it after prose instead —
        # observed live. The trailing sentinel still means the model judged the sources
        # insufficient; without this, the explanation was treated as a real answer and fell
        # through to the markerless "attach all sources" fallback, showing the model's own
        # explanation of why it COULDN'T answer as if it had, with the literal "!none!" text
        # left visible and unrelated sources attached.
        raw = (
            "The course materials discuss image classification and linear "
            "classification, but they do not define or cover sorting. !none!"
        )
        answer, used = parse_answer_response(raw, 3)
        assert answer is None
        assert used == set()

    def test_plain_text_with_markers_uses_marker_attribution(self):
        answer, used = parse_answer_response("The quiz is worth 4 points.[2]", 3)
        assert answer == "The quiz is worth 4 points.[2]"
        assert used == {1}

    def test_plain_text_without_markers_is_suppressed_as_ungrounded(self):
        # Rule 2 requires a marker after every real claim; plain text with none is either a
        # genuine answer that dropped the required markers, or a refusal explained in prose
        # instead of the bare !none! sentinel (observed live, in several different phrasings).
        # Defensively attaching every retrieved source used to paper over that distinction —
        # this instead lets the existing ungrounded guard suppress it like any other
        # unattributed answer, regardless of which of those two it actually was.
        answer, used = parse_answer_response("A markerless plain answer.", 3)
        assert answer is None
        assert used == set()


class TestUsedSourcesRangeCheck:
    """An out-of-range used_sources index must not slip an ungrounded answer
    past the "cites no real source" suppression guard."""

    def test_json_path_out_of_range_index_is_dropped_not_kept(self):
        answer, used = parse_answer_response(
            '{"answer": "Yes, that is correct.", "used_sources": [99]}', 3
        )
        # Suppressed: used_indices ends up empty once the bogus index is
        # dropped, so the ungrounded-answer guard fires as intended.
        assert answer is None
        assert used == set()

    def test_json_path_mixes_in_range_and_out_of_range_indices(self):
        answer, used = parse_answer_response(
            '{"answer": "Yes.", "used_sources": [2, 99]}', 3
        )
        assert answer == "Yes."
        assert used == {1}

    def test_trailing_schema_path_out_of_range_index_is_dropped(self):
        answer, used = parse_answer_response(
            "The exam is worth 30 points.\nUsed_sources: [99]", 3
        )
        assert answer is None
        assert used == set()

    def test_trailing_schema_path_in_range_index_still_works(self):
        answer, used = parse_answer_response(
            "The exam is worth 30 points.\nUsed_sources: [2]", 3
        )
        assert answer == "The exam is worth 30 points."
        assert used == {1}


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


class TestNavigateFallbackClearsTheStream:
    """The null-to-navigate fallback reruns the answer LLM without streaming.

    Without an explicit reset, whatever the first (discarded) call already
    streamed keeps sitting as the client's last-known draft for the entire
    fallback round-trip, markers and all, since nothing else calls
    stream_handler again until the terminal result replaces it.
    """

    def _pipeline_with(self, *raw_answers):
        # Bypasses __init__ (no real WeaviateClient/LLM needed): only the two
        # methods __call__ actually invokes are stubbed, both as plain instance
        # attributes so they run unbound (no implicit self is passed to them).
        pipeline = object.__new__(GlobalSearchPipeline)
        pipeline.tokens = []
        pipeline.answer_llm = SimpleNamespace(tokens=SimpleNamespace())
        entity_grounded_source = EntitySourceDTO(
            entity_type="exercise", snippet="Some exercise info", via_pointer_tier=False
        )
        pipeline._retrieve_sources = lambda *args, **kwargs: [entity_grounded_source]
        answers = iter(raw_answers)
        pipeline._generate_answer = lambda *args, **kwargs: next(answers)
        return pipeline

    def test_stream_handler_is_reset_before_the_fallback_call_runs(self):
        # Marker-less, non-sentinel text: null via the ungrounded guard, not a deliberate
        # !none! — the fallback must still fire for THIS kind of null (see
        # TestDeliberateRefusalSkipsTheFallback for the one kind it must not).
        pipeline = self._pipeline_with("No matching content.", "Yes, see the exercise.")
        deltas: list = []
        original_generate_answer = pipeline._generate_answer

        def assert_reset_already_sent_when_navigating(*args, **kwargs):
            # `assert None in deltas` alone only checks the final state — it would
            # still pass if a future change moved the reset to AFTER the fallback
            # call instead of before it, silently reintroducing the stale-draft bug.
            if kwargs.get("navigate"):
                assert deltas and deltas[-1] is None
            return original_generate_answer(*args, **kwargs)

        pipeline._generate_answer = assert_reset_already_sent_when_navigating

        pipeline(
            query="where is this covered",
            intent=SearchIntent.TRIGGER_AI,
            stream_handler=deltas.append,
        )

        assert None in deltas

    def test_no_reset_when_the_first_call_already_answers(self):
        pipeline = self._pipeline_with("The exam is worth 30 points.[1]")
        deltas: list = []

        pipeline(
            query="how many points is the exam worth",
            intent=SearchIntent.TRIGGER_AI,
            stream_handler=deltas.append,
        )

        # No fallback ran, so nothing was ever discarded — an unconditional reset
        # here would just flash the client back to a thinking state for no reason.
        assert None not in deltas

    def test_token_usage_from_both_calls_is_recorded_on_fallback(self):
        # self.answer_llm.tokens is reassigned to a NEW TokenUsageDTO instance by
        # every real invocation (see IrisLangchainChatModel._generate); a mock that
        # does the same distinguishes "recorded once, from whichever call happened
        # to run last" from "recorded from both calls".
        pipeline = self._pipeline_with("No matching content.", "Yes, see the exercise.")
        pipeline.answer_llm = SimpleNamespace(tokens=SimpleNamespace(call="none"))
        original_generate_answer = pipeline._generate_answer
        call_count = 0

        def generate_and_stamp_usage(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            pipeline.answer_llm.tokens = SimpleNamespace(call=call_count)
            return original_generate_answer(*args, **kwargs)

        pipeline._generate_answer = generate_and_stamp_usage

        pipeline(query="where is this covered", intent=SearchIntent.TRIGGER_AI)

        recorded_calls = [t.call for t in pipeline.tokens]
        assert recorded_calls == [1, 2], (
            "both the discarded first call and the fallback call must be "
            "recorded, not just whichever one happened to run last"
        )


class TestDeliberateRefusalSkipsTheFallback:
    """A bare !none! is the model directly exercising its documented way to decline — not
    a flaky or over-cautious null this pipeline's own guards produced. The navigate prompt
    is deliberately more lenient (its own rule: "a student prefers a pointer to silence"),
    so retrying a deliberate refusal through it relitigates a judgment the model already
    made on purpose. Observed live: an incomplete question ("explain the difference
    between", never naming what to compare) correctly got !none! from the grounded prompt
    every single time it was tried, then just as reliably got overridden by the navigate
    fallback pointing at the same course, in the wrong language for the question asked.
    """

    def _pipeline_with(self, *raw_answers):
        pipeline = object.__new__(GlobalSearchPipeline)
        pipeline.tokens = []
        pipeline.answer_llm = SimpleNamespace(tokens=SimpleNamespace())
        entity_grounded_source = EntitySourceDTO(
            entity_type="exercise", snippet="Some exercise info", via_pointer_tier=False
        )
        pipeline._retrieve_sources = lambda *args, **kwargs: [entity_grounded_source]
        answers = iter(raw_answers)
        pipeline._generate_answer = lambda *args, **kwargs: next(answers)
        return pipeline

    def test_a_deliberate_none_sentinel_does_not_trigger_the_fallback(self):
        # Only one raw answer is queued: if the fallback ran anyway, the second
        # _generate_answer call would raise StopIteration instead of quietly passing.
        pipeline = self._pipeline_with("!none!")
        call_count = 0
        original_generate_answer = pipeline._generate_answer

        def count_calls(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return original_generate_answer(*args, **kwargs)

        pipeline._generate_answer = count_calls

        result = pipeline(
            query="explain the difference between", intent=SearchIntent.TRIGGER_AI
        )

        assert call_count == 1
        assert result.answer is None

    def test_none_sentinel_with_trailing_punctuation_still_skips_the_fallback(self):
        pipeline = self._pipeline_with("!none!.")

        result = pipeline(
            query="explain the difference between", intent=SearchIntent.TRIGGER_AI
        )

        assert result.answer is None

    def test_none_sentinel_appended_after_an_explanation_still_skips_the_fallback(self):
        # The prompt says write the sentinel ALONE, but the model sometimes appends it
        # after prose instead — that trailing sentinel is still the model's own deliberate
        # decision, not a parsing accident, so the fallback must not override it either.
        pipeline = self._pipeline_with(
            "The materials touch on related ideas but do not cover this directly. !none!"
        )

        result = pipeline(
            query="explain the difference between", intent=SearchIntent.TRIGGER_AI
        )

        assert result.answer is None


class TestStageHandler:
    """stage_handler fires at the pipeline's real phase boundaries, so the client can show
    what is actually happening instead of one static message for the whole wait."""

    def _pipeline_with(self, raw_answer, sources=None):
        pipeline = object.__new__(GlobalSearchPipeline)
        pipeline.tokens = []
        pipeline.answer_llm = SimpleNamespace(tokens=SimpleNamespace())
        if sources is None:
            sources = [
                EntitySourceDTO(
                    entity_type="exercise",
                    snippet="Some exercise info",
                    via_pointer_tier=False,
                )
            ]
        pipeline._retrieve_sources = lambda *args, **kwargs: sources
        pipeline._generate_answer = lambda *args, **kwargs: raw_answer
        return pipeline

    def test_fires_searching_then_found_then_generating_in_order(self):
        pipeline = self._pipeline_with("Yes, see the exercise.[1]")
        calls: list = []

        pipeline(
            query="how many points is the exam worth",
            intent=SearchIntent.TRIGGER_AI,
            stage_handler=lambda stage, sources: calls.append((stage, sources)),
        )

        assert [stage for stage, _ in calls] == ["searching", "found", "generating"]

    def test_searching_fires_before_anything_is_found(self):
        pipeline = self._pipeline_with("Yes, see the exercise.[1]")
        calls: list = []

        pipeline(
            query="how many points is the exam worth",
            intent=SearchIntent.TRIGGER_AI,
            stage_handler=lambda stage, sources: calls.append((stage, sources)),
        )

        searching_sources = next(
            sources for stage, sources in calls if stage == "searching"
        )
        assert searching_sources == []

    def test_found_carries_distinct_course_names_in_ranked_order(self):
        # Two sources from "Advanced Algorithms" (ranked first and third) plus one from
        # "Software Engineering" (ranked second): the duplicate must collapse to one entry,
        # keeping each course's FIRST-seen (highest-ranked) position, not a later repeat.
        algorithms = CourseInfo(id=1, name="Advanced Algorithms")
        software_eng = CourseInfo(id=2, name="Software Engineering")
        sources = [
            EntitySourceDTO(entity_type="exercise", snippet="a", course=algorithms),
            EntitySourceDTO(entity_type="exercise", snippet="b", course=software_eng),
            EntitySourceDTO(entity_type="exercise", snippet="c", course=algorithms),
        ]
        pipeline = self._pipeline_with("Yes, see the exercise.[1]", sources=sources)
        calls: list = []

        pipeline(
            query="how many points is the exam worth",
            intent=SearchIntent.TRIGGER_AI,
            stage_handler=lambda stage, sources: calls.append((stage, sources)),
        )

        found_sources = next(sources for stage, sources in calls if stage == "found")
        assert found_sources == ["Advanced Algorithms", "Software Engineering"]

    def test_generating_carries_no_course_names_since_found_already_reported_them(
        self,
    ):
        algorithms = CourseInfo(id=1, name="Advanced Algorithms")
        sources = [
            EntitySourceDTO(entity_type="exercise", snippet="a", course=algorithms)
        ]
        pipeline = self._pipeline_with("Yes, see the exercise.[1]", sources=sources)
        calls: list = []

        pipeline(
            query="how many points is the exam worth",
            intent=SearchIntent.TRIGGER_AI,
            stage_handler=lambda stage, sources: calls.append((stage, sources)),
        )

        generating_sources = next(
            sources for stage, sources in calls if stage == "generating"
        )
        assert generating_sources == []

    def test_stage_handler_is_optional(self):
        # A caller that omits it (every caller before this parameter existed) must not
        # break — only a caller that opts in is affected.
        pipeline = self._pipeline_with("Yes, see the exercise.[1]")

        pipeline(
            query="how many points is the exam worth", intent=SearchIntent.TRIGGER_AI
        )


class TestRetrieveSourcesWiresStageHandlerIntoRetrieverOnPhase:
    """_retrieve_sources (unstubbed here, unlike TestStageHandler above) must translate its
    stage_handler into the on_phase callback the real retriever calls, so a "ranking" phase
    fired deep inside retrieval actually reaches the client as a stage update."""

    def _pipeline_with(self, on_phase_fires):
        pipeline = object.__new__(GlobalSearchPipeline)
        pipeline.tokens = []
        pipeline.answer_llm = SimpleNamespace(tokens=SimpleNamespace())
        source = EntitySourceDTO(
            entity_type="exercise", snippet="Some exercise info", via_pointer_tier=False
        )

        def fake_search(**kwargs):
            on_phase = kwargs.get("on_phase")
            if on_phase is not None and on_phase_fires:
                on_phase("ranking")
            return [source]

        pipeline.retriever = SimpleNamespace(search=fake_search)
        pipeline._generate_answer = lambda *args, **kwargs: "Yes, see the exercise.[1]"
        return pipeline

    def test_a_ranking_phase_from_the_retriever_reaches_stage_handler(self):
        pipeline = self._pipeline_with(on_phase_fires=True)
        calls: list = []

        pipeline(
            query="how many points is the exam worth",
            intent=SearchIntent.TRIGGER_AI,
            stage_handler=lambda stage, sources: calls.append((stage, sources)),
        )

        assert [stage for stage, _ in calls] == [
            "searching",
            "ranking",
            "found",
            "generating",
        ]
        ranking_sources = next(
            sources for stage, sources in calls if stage == "ranking"
        )
        assert ranking_sources == []

    def test_no_stage_handler_means_no_on_phase_is_passed_to_the_retriever(self):
        pipeline = object.__new__(GlobalSearchPipeline)
        pipeline.tokens = []
        pipeline.answer_llm = SimpleNamespace(tokens=SimpleNamespace())
        source = EntitySourceDTO(
            entity_type="exercise", snippet="Some exercise info", via_pointer_tier=False
        )
        captured = {}

        def fake_search(**kwargs):
            captured["on_phase"] = kwargs.get("on_phase")
            return [source]

        pipeline.retriever = SimpleNamespace(search=fake_search)
        pipeline._generate_answer = lambda *args, **kwargs: "Yes, see the exercise.[1]"

        pipeline(
            query="how many points is the exam worth", intent=SearchIntent.TRIGGER_AI
        )

        assert captured["on_phase"] is None
