from types import SimpleNamespace
from unittest.mock import MagicMock

from iris.retrieval.course_memory_retrieval import CourseMemoryRetrieval
from iris.vector_database.course_memory_schema import CourseMemorySchema


def _make_retriever():
    retriever = object.__new__(CourseMemoryRetrieval)
    retriever.llm_embedding = MagicMock()
    retriever.llm_embedding.embed.return_value = [0.1, 0.2, 0.3]
    retriever.collection = MagicMock()
    return retriever


def _obj(score, message_id="m1"):
    return SimpleNamespace(
        properties={
            CourseMemorySchema.QUESTION.value: "q",
            CourseMemorySchema.ANSWER.value: "a",
            CourseMemorySchema.MESSAGE_ID.value: message_id,
            CourseMemorySchema.CONVERSATION_ID.value: "c1",
        },
        metadata=SimpleNamespace(score=score),
    )


def test_threshold_filters_low_scoring_results():
    retriever = _make_retriever()
    retriever.collection.query.hybrid.return_value = SimpleNamespace(
        objects=[_obj(0.95, "keep"), _obj(0.5, "drop")]
    )

    results = retriever(
        chat_history=[], student_query="how?", course_id=42, rewrite=False
    )

    assert len(results) == 1
    assert results[0][CourseMemorySchema.MESSAGE_ID.value] == "keep"


def test_missing_course_id_returns_empty():
    retriever = _make_retriever()
    assert not retriever(chat_history=[], student_query="q", course_id=None)
    retriever.collection.query.hybrid.assert_not_called()


def test_graceful_degradation_when_embedding_fails():
    retriever = _make_retriever()
    retriever.llm_embedding.embed.side_effect = RuntimeError("Logos down")

    results = retriever(chat_history=[], student_query="q", course_id=42, rewrite=False)

    assert not results


def test_results_include_backlink_ids():
    retriever = _make_retriever()
    retriever.collection.query.hybrid.return_value = SimpleNamespace(
        objects=[_obj(0.99, "msg-7")]
    )

    results = retriever(chat_history=[], student_query="q", course_id=42, rewrite=False)

    assert results[0][CourseMemorySchema.MESSAGE_ID.value] == "msg-7"
    assert results[0][CourseMemorySchema.CONVERSATION_ID.value] == "c1"
