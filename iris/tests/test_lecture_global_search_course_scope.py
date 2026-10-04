"""Course-scope resolution for global search retrieval.

The client-supplied ``course_ids`` filter is intersected with the courses the access
context permits (it never overrides them), an unrestricted (admin) context has no
course ceiling, and an empty effective scope short-circuits before the embedding call.
"""

# pylint: disable=protected-access

from unittest.mock import Mock

from iris.domain.search.global_search_dto import AccessContext
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    LectureGlobalSearchRetrieval,
    resolve_effective_course_ids,
)


def test_resolve_effective_course_ids_both_none_has_no_ceiling():
    assert resolve_effective_course_ids(None, None) is None


def test_resolve_effective_course_ids_context_only_returns_permitted_courses():
    ctx = AccessContext(course_ids=[1, 2])
    assert resolve_effective_course_ids(None, ctx) == [1, 2]


def test_resolve_effective_course_ids_client_filter_only_is_unchanged():
    assert resolve_effective_course_ids([3, 4], None) == [3, 4]


def test_resolve_effective_course_ids_intersects_and_drops_foreign_courses():
    # Security: the client filter is intersected with the permitted courses, never allowed to override them.
    ctx = AccessContext(course_ids=[2, 3, 4])
    assert resolve_effective_course_ids([1, 2, 3], ctx) == [2, 3]


def test_resolve_effective_course_ids_empty_intersection_returns_empty_list():
    ctx = AccessContext(course_ids=[2])
    assert resolve_effective_course_ids([1], ctx) == []


def test_resolve_effective_course_ids_unrestricted_context_bypasses_the_ceiling():
    # Admins carry an unrestricted context: their client filter is returned unchanged, with no permission ceiling.
    ctx = AccessContext(course_ids=[2], unrestricted=True)
    assert resolve_effective_course_ids([1, 99], ctx) == [1, 99]


def test_search_short_circuits_empty_scope_before_embedding():
    # A client filter disjoint from the permitted courses yields an empty scope, so no embedding is computed.
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    retrieval.llm_embedding = Mock()
    retrieval._run_hybrid_search = Mock()

    result = retrieval.search(
        "query",
        limit=5,
        course_ids=[99],
        access_context=AccessContext(course_ids=[1, 2]),
    )

    assert result == []
    retrieval.llm_embedding.embed.assert_not_called()
    retrieval._run_hybrid_search.assert_not_called()


def test_search_without_access_context_passes_client_filter_through_and_embeds():
    # No access context (old Artemis): the client course filter flows through unchanged, exactly as before.
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    retrieval.llm_embedding = Mock()
    retrieval.llm_embedding.embed.return_value = [0.1]
    retrieval._run_hybrid_search = Mock(return_value=[])

    result = retrieval.search("query", limit=5, course_ids=[7], access_context=None)

    assert result == []
    retrieval.llm_embedding.embed.assert_called_once()
    assert retrieval._run_hybrid_search.call_args.kwargs["course_ids"] == [7]
