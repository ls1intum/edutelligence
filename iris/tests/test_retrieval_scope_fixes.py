"""The transcription presence check stays within the asking Artemis instance."""

# pylint: disable=protected-access

from types import SimpleNamespace

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval


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
