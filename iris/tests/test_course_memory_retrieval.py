from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import NAMESPACE_URL, uuid5

from weaviate.classes.query import HybridFusion

from iris.retrieval.course_memory_retrieval import CourseMemoryRetrieval
from iris.vector_database.course_memory_schema import CourseMemorySchema


def _make_retriever():
    retriever = object.__new__(CourseMemoryRetrieval)
    retriever.llm_embedding = MagicMock()
    retriever.llm_embedding.embed.return_value = [0.1, 0.2, 0.3]
    retriever.collection = MagicMock()
    return retriever


def _obj(key, message_id="m1", source="TUTOR_WRITTEN"):
    # Real UUIDs (deterministic per key): the gate filter is built with
    # Filter.by_id().contains_any, which rejects non-UUID strings.
    return SimpleNamespace(
        uuid=str(uuid5(NAMESPACE_URL, key)),
        properties={
            CourseMemorySchema.QUESTION.value: "q",
            CourseMemorySchema.ANSWER.value: "a",
            CourseMemorySchema.MESSAGE_ID.value: message_id,
            CourseMemorySchema.CONVERSATION_ID.value: "c1",
            CourseMemorySchema.SOURCE.value: source,
        },
    )


def _wire(retriever, ranked, gate):
    retriever.collection.query.hybrid.return_value = SimpleNamespace(objects=ranked)
    retriever.collection.query.near_vector.return_value = SimpleNamespace(objects=gate)


def test_cosine_gate_drops_results_below_the_floor():
    retriever = _make_retriever()
    # Hybrid ranks two candidates; only the first clears the cosine certainty gate.
    _wire(
        retriever,
        ranked=[_obj("u1", "keep"), _obj("u2", "drop")],
        gate=[_obj("u1", "keep")],
    )

    results = retriever(
        chat_history=[], student_query="how?", course_id=42, rewrite=False
    )

    assert len(results) == 1
    assert results[0][CourseMemorySchema.MESSAGE_ID.value] == "keep"


def test_hybrid_fusion_is_pinned_to_relative_score():
    retriever = _make_retriever()
    _wire(retriever, ranked=[_obj("u1")], gate=[_obj("u1")])

    retriever(chat_history=[], student_query="q", course_id=42, rewrite=False)

    kwargs = retriever.collection.query.hybrid.call_args.kwargs
    assert kwargs["fusion_type"] == HybridFusion.RELATIVE_SCORE


def test_ranked_order_preserved_over_gated_set():
    retriever = _make_retriever()
    _wire(
        retriever,
        ranked=[_obj("a", "a"), _obj("b", "b"), _obj("c", "c")],
        gate=[_obj("c", "c"), _obj("a", "a")],  # gate order must not matter
    )

    results = retriever(chat_history=[], student_query="q", course_id=42, rewrite=False)

    ids = [r[CourseMemorySchema.MESSAGE_ID.value] for r in results]
    assert ids == ["a", "c"]  # hybrid order kept, "b" dropped by the gate


def test_missing_course_id_returns_empty():
    retriever = _make_retriever()
    assert not retriever(chat_history=[], student_query="q", course_id=None)
    retriever.collection.query.hybrid.assert_not_called()
    retriever.collection.query.near_vector.assert_not_called()


def test_graceful_degradation_when_embedding_fails():
    retriever = _make_retriever()
    retriever.llm_embedding.embed.side_effect = RuntimeError("Logos down")

    results = retriever(chat_history=[], student_query="q", course_id=42, rewrite=False)

    assert not results


def test_results_include_backlink_ids():
    retriever = _make_retriever()
    _wire(retriever, ranked=[_obj("u7", "msg-7")], gate=[_obj("u7", "msg-7")])

    results = retriever(chat_history=[], student_query="q", course_id=42, rewrite=False)

    assert results[0][CourseMemorySchema.MESSAGE_ID.value] == "msg-7"
    assert results[0][CourseMemorySchema.CONVERSATION_ID.value] == "c1"


def test_rewrite_used_and_never_queries_missing_language_property():
    retriever = _make_retriever()
    _wire(retriever, ranked=[_obj("u1")], gate=[_obj("u1")])
    retriever.rewrite_student_query = MagicMock(return_value="self-contained query")
    # fetch_course_language must NOT be called (it would hit the missing
    # course_language property on the CourseMemory collection).
    retriever.fetch_course_language = MagicMock(
        side_effect=AssertionError("must not fetch course language")
    )

    retriever(chat_history=[], student_query="how do I?", course_id=42, rewrite=True)

    retriever.rewrite_student_query.assert_called_once()
    retriever.llm_embedding.embed.assert_called_once_with("self-contained query")


def test_rewrite_failure_falls_back_to_raw_query():
    retriever = _make_retriever()
    _wire(retriever, ranked=[_obj("u1")], gate=[_obj("u1")])
    retriever.rewrite_student_query = MagicMock(side_effect=RuntimeError("llm down"))

    retriever(chat_history=[], student_query="raw query", course_id=42, rewrite=True)

    retriever.llm_embedding.embed.assert_called_once_with("raw query")


def test_gate_is_restricted_to_ranked_candidates():
    """The certainty gate must be an exact floor over the hybrid candidates: a
    ranked hit clearing the threshold survives regardless of how it ranks by
    pure vector similarity (no top-N cutoff on a separate query)."""
    retriever = _make_retriever()
    _wire(retriever, ranked=[_obj("u1"), _obj("u2"), _obj("u3")], gate=[_obj("u2")])

    results = retriever(chat_history=[], student_query="q", course_id=42, rewrite=False)

    kwargs = retriever.collection.query.near_vector.call_args.kwargs
    assert kwargs["limit"] == 3  # exactly the ranked candidates, no wider pool
    assert len(results) == 1


def test_empty_hybrid_result_skips_the_gate_query():
    retriever = _make_retriever()
    _wire(retriever, ranked=[], gate=[])

    results = retriever(chat_history=[], student_query="q", course_id=42, rewrite=False)

    assert not results
    retriever.collection.query.near_vector.assert_not_called()
