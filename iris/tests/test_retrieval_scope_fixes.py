"""Chat retrievers keep the request's local/cloud choice, and the transcription
presence check stays within the asking Artemis instance."""

# pylint: disable=protected-access

from types import SimpleNamespace

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.pipeline.chat import chat_pipeline
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval
from iris.tools import chat_tool_providers


class _RecordingRetriever:
    instances: list = []

    def __init__(self, client, local=False):
        self.client = client
        self.local = local
        _RecordingRetriever.instances.append(self)


def test_lecture_retriever_for_the_current_view_uses_the_local_choice(monkeypatch):
    monkeypatch.setattr(chat_pipeline, "LectureRetrieval", _RecordingRetriever)
    _RecordingRetriever.instances = []
    state = SimpleNamespace(db=SimpleNamespace(client="client"), local=True)

    retriever = chat_pipeline.ChatPipeline._get_lecture_retriever(None, state)

    assert retriever.local is True
    assert state.lecture_retriever is retriever


def test_faq_retriever_uses_the_local_choice(monkeypatch):
    monkeypatch.setattr(chat_tool_providers, "FaqRetrieval", _RecordingRetriever)
    monkeypatch.setattr(
        chat_tool_providers,
        "create_tool_faq_content_retrieval",
        lambda retriever, *args, **kwargs: retriever,
    )
    _RecordingRetriever.instances = []
    state = SimpleNamespace(
        db=SimpleNamespace(client="client"),
        local=True,
        allow_faq_tool=True,
        dto=SimpleNamespace(
            course=SimpleNamespace(id=1, name="Course"),
            settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
        ),
        callback=None,
        query_text="q",
        message_history=[],
        faq_storage={},
    )

    retriever = chat_tool_providers.provide_faq_retrieval(state)

    assert retriever.local is True


class _CapturingCollection:
    """Records the filter of the last fetch."""

    def __init__(self):
        self.filters = None

    class _Query:
        def __init__(self, outer):
            self.outer = outer

        def fetch_objects(self, filters=None, limit=None):
            del limit
            self.outer.filters = filters
            return SimpleNamespace(objects=[])

    @property
    def query(self):
        return _CapturingCollection._Query(self)


def _filter_targets(weaviate_filter) -> set[str]:
    targets = set()
    stack = [weaviate_filter]
    while stack:
        current = stack.pop()
        nested = getattr(current, "filters", None)
        if nested:
            stack.extend(nested)
            continue
        target = getattr(current, "target", None)
        if target is not None:
            targets.add(str(target))
    return targets


def test_transcription_presence_check_filters_by_artemis_instance():
    retrieval = LectureRetrieval.__new__(LectureRetrieval)
    retrieval._transcription_presence_cache = {}
    collection = _CapturingCollection()
    retrieval.lecture_transcription_collection = collection

    exists = retrieval.lecture_unit_has_transcriptions(
        1, 2, 3, "https://artemis.example"
    )

    assert exists is False
    assert "base_url" in _filter_targets(collection.filters)


def test_transcription_presence_is_cached_per_artemis_instance():
    retrieval = LectureRetrieval.__new__(LectureRetrieval)
    retrieval._transcription_presence_cache = {}
    collection = _CapturingCollection()
    retrieval.lecture_transcription_collection = collection

    retrieval.lecture_unit_has_transcriptions(1, 2, 3, "https://a.example")
    retrieval.lecture_unit_has_transcriptions(1, 2, 3, "https://b.example")

    assert set(retrieval._transcription_presence_cache) == {
        (1, 2, 3, "https://a.example"),
        (1, 2, 3, "https://b.example"),
    }
