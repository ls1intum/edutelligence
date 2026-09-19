"""Course exclusions for global search retrieval.

Artemis hides courses from a search by naming them, and it can only subtract them itself when the
caller has a course ceiling. An unrestricted (admin) caller has no list to subtract from, so the
exclusion has to reach the query. A request without the field has to behave exactly as before,
because older Artemis versions never send it.
"""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import Mock

from iris.domain.search.global_search_dto import (
    AccessContext,
    LectureSearchRequestDTO,
)
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    LectureGlobalSearchRetrieval,
    apply_course_exclusions,
)


def test_request_without_the_field_carries_no_exclusions():
    dto = LectureSearchRequestDTO.model_validate({"query": "backprop", "limit": 5})
    assert dto.exclude_course_ids is None


def test_request_reads_the_camel_case_alias():
    dto = LectureSearchRequestDTO.model_validate(
        {"query": "backprop", "limit": 5, "excludeCourseIds": [7, 9]}
    )
    assert dto.exclude_course_ids == [7, 9]


def test_exclusions_are_subtracted_from_a_bounded_scope():
    # A caller with a course ceiling needs no query filter: the scope itself shrinks.
    scope, remaining = apply_course_exclusions([1, 2, 3], [2])
    assert scope == [1, 3]
    assert not remaining


def test_exclusions_travel_on_when_there_is_no_scope_to_subtract_from():
    # An unrestricted caller has no ceiling, so the query has to apply the exclusion.
    scope, remaining = apply_course_exclusions(None, [2, 4])
    assert scope is None
    assert remaining == [2, 4]


def test_no_exclusions_leaves_the_scope_untouched():
    assert apply_course_exclusions([1, 2], None) == ([1, 2], [])
    assert apply_course_exclusions(None, None) == (None, [])


def _recording_retrieval():
    """A retrieval whose collections record the filters they are queried with."""
    calls = []

    def hybrid(**kwargs):
        calls.append(kwargs["filters"])
        return SimpleNamespace(objects=[])

    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    retrieval.llm_embedding = Mock(embed=Mock(return_value=[0.0]))
    retrieval.collection = SimpleNamespace(query=SimpleNamespace(hybrid=hybrid))
    retrieval.transcription_collection = SimpleNamespace(
        query=SimpleNamespace(hybrid=hybrid)
    )
    return retrieval, calls


def test_search_excludes_the_courses_of_an_unrestricted_caller():
    retrieval, calls = _recording_retrieval()

    retrieval.search(
        "backprop",
        limit=5,
        access_context=AccessContext(course_ids=[], unrestricted=True),
        exclude_course_ids=[42],
    )

    # Both collections are queried, and neither is queried without a filter.
    assert len(calls) == 2
    assert all(filters is not None for filters in calls)


def test_search_skips_entirely_when_the_exclusions_empty_the_scope():
    retrieval, calls = _recording_retrieval()

    results = retrieval.search(
        "backprop",
        limit=5,
        course_ids=[1],
        access_context=AccessContext(course_ids=[1]),
        exclude_course_ids=[1],
    )

    assert not results
    assert not calls
    retrieval.llm_embedding.embed.assert_not_called()


def test_search_without_exclusions_queries_as_before():
    retrieval, calls = _recording_retrieval()

    retrieval.search("backprop", limit=5)

    assert len(calls) == 2
    # The segment search carries no filter at all, exactly as it did before the field existed.
    assert calls[0] is None or calls[1] is None
