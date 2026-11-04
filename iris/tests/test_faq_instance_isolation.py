"""FAQ reads return only the FAQs of the asking Artemis instance.

Several Artemis instances can share one Pyris, and their course ids overlap, so every FAQ read filters by
the base URL too and checks it exactly: with word tokenization the Weaviate filter also matches a URL that
contains all words of ours.
"""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.domain.rewriting_pipeline_execution_dto import (  # noqa: E402
    RewritingPipelineExecutionDTO,
)
from iris.pipeline.rewriting_pipeline import RewritingPipeline  # noqa: E402
from iris.retrieval import faq_retrieval_utils  # noqa: E402
from iris.retrieval.faq_retrieval import FaqRetrieval  # noqa: E402
from iris.retrieval.faq_retrieval_utils import (  # noqa: E402
    fetch_owned_faqs,
    should_allow_faq_tool,
)
from iris.tools import chat_tool_providers  # noqa: E402
from iris.tools.faq_content_retrieval import (  # noqa: E402
    create_tool_faq_content_retrieval,
)

OWN = "https://artemis.example"
LONGER = "https://artemis-test.artemis.example"


def _row(faq_id, base_url=OWN):
    properties = {"faq_id": faq_id, "course_id": 7, "question_title": f"Q{faq_id}"}
    if base_url is not None:
        properties["base_url"] = base_url
    return SimpleNamespace(uuid=SimpleNamespace(int=faq_id), properties=properties)


class _Pages:
    """A Weaviate query whose result is ``rows`` in rank order, served by offset and limit."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        offset = kwargs.get("offset", 0)
        end = offset + kwargs["limit"]
        return SimpleNamespace(objects=self.rows[offset:end])


def _filter_targets(filters):
    if hasattr(filters, "filters"):
        return [target for f in filters.filters for target in _filter_targets(f)]
    return [(filters.target, filters.value)]


def _retrieval(rows):
    retrieval = FaqRetrieval.__new__(FaqRetrieval)
    retrieval.collection = MagicMock()
    retrieval.collection.query.hybrid.side_effect = _Pages(rows)
    retrieval.collection.query.fetch_objects.side_effect = _Pages(rows)
    retrieval.llm_embedding = MagicMock()
    retrieval.llm_embedding.embed.return_value = [0.1, 0.2]
    retrieval.tokens = []
    return retrieval


def test_the_search_filters_by_course_and_instance():
    retrieval = _retrieval([_row(1)])

    assert retrieval("exam?", 7, OWN) == [_row(1).properties]

    filters = retrieval.collection.query.hybrid.call_args.kwargs["filters"]
    assert sorted(_filter_targets(filters)) == [("base_url", OWN), ("course_id", 7)]


def test_rows_of_another_instance_and_legacy_rows_are_dropped():
    # With word tokenization the filter also returns the longer URL; legacy rows have no base URL
    rows = [_row(1, LONGER), _row(2, None), _row(3)]

    assert [faq["faq_id"] for faq in _retrieval(rows)("exam?", 7, OWN)] == [3]


def test_foreign_rows_cannot_push_owned_faqs_out_of_the_result():
    rows = [_row(i, LONGER) for i in range(12)] + [_row(100), _row(101)]
    retrieval = _retrieval(rows)

    result = retrieval("exam?", 7, OWN, result_limit=10)

    assert [faq["faq_id"] for faq in result] == [100, 101]
    # The query vector is computed once for all pages
    assert retrieval.llm_embedding.embed.call_count == 1
    assert [
        call.kwargs["offset"]
        for call in retrieval.collection.query.hybrid.call_args_list
    ] == [0, 10]


def test_a_field_tokenized_result_is_read_with_one_query():
    retrieval = _retrieval([_row(i) for i in range(20)])

    assert len(retrieval("exam?", 7, OWN, result_limit=10)) == 10
    assert retrieval.collection.query.hybrid.call_count == 1


def test_the_scan_stops_at_its_page_budget():
    pages = _Pages([_row(i, LONGER) for i in range(100)] + [_row(1000)])

    owned, budget_spent = fetch_owned_faqs(
        lambda offset, limit: pages(offset=offset, limit=limit).objects, OWN, 10
    )

    assert owned == []
    assert budget_spent is True
    assert len(pages.calls) == faq_retrieval_utils._MAX_PAGES


def test_a_fully_read_result_does_not_report_a_spent_budget():
    pages = _Pages([_row(1, LONGER), _row(2, LONGER)])

    owned, budget_spent = fetch_owned_faqs(
        lambda offset, limit: pages(offset=offset, limit=limit).objects, OWN, 1
    )

    assert (owned, budget_spent) == ([], False)


def test_get_faqs_from_db_is_scoped_in_both_branches():
    rows = [_row(1, LONGER), _row(2, None), _row(3)]
    retrieval = _retrieval(rows)

    with_search = retrieval.get_faqs_from_db(7, OWN, search_text="exam")
    without_search = retrieval.get_faqs_from_db(7, OWN)

    assert [faq["properties"]["faq_id"] for faq in with_search] == [3]
    assert [faq["properties"]["faq_id"] for faq in without_search] == [3]
    for query in (
        retrieval.collection.query.hybrid,
        retrieval.collection.query.fetch_objects,
    ):
        assert ("base_url", OWN) in _filter_targets(query.call_args.kwargs["filters"])


def test_without_a_base_url_no_faq_is_read():
    retrieval = _retrieval([_row(1)])

    assert retrieval("exam?", 7, None) == []
    assert retrieval.get_faqs_from_db(7, "") == []
    retrieval.collection.query.hybrid.assert_not_called()
    retrieval.collection.query.fetch_objects.assert_not_called()


def _db(rows):
    db = MagicMock()
    db.faqs.query.fetch_objects.side_effect = _Pages(rows)
    return db


def test_the_tool_gate_is_scoped_to_the_instance():
    db = _db([_row(1)])
    assert should_allow_faq_tool(db, 7, OWN) is True
    assert ("base_url", OWN) in _filter_targets(
        db.faqs.query.fetch_objects.call_args.kwargs["filters"]
    )

    assert should_allow_faq_tool(_db([_row(1, LONGER), _row(2, None)]), 7, OWN) is False
    assert should_allow_faq_tool(_db([_row(1)]), 7, None) is False
    assert should_allow_faq_tool(_db([_row(1)]), 7, "") is False


def test_the_gate_finds_an_owned_row_behind_foreign_rows():
    rows = [_row(i, LONGER) for i in range(4)] + [_row(100)]
    assert should_allow_faq_tool(_db(rows), 7, OWN) is True


def test_the_gate_stays_open_when_its_scan_budget_runs_out():
    # Five foreign rows fill the budget; the owned sixth row is never read
    rows = [_row(i, LONGER) for i in range(5)] + [_row(100)]
    db = _db(rows)

    assert should_allow_faq_tool(db, 7, OWN) is True
    assert db.faqs.query.fetch_objects.call_count == faq_retrieval_utils._MAX_PAGES


def test_the_tool_passes_the_base_url():
    retriever = MagicMock(return_value=[])

    create_tool_faq_content_retrieval(retriever, 7, OWN, None)("exam?")

    assert retriever.call_args.kwargs["base_url"] == OWN


def test_the_chat_provider_hands_the_request_base_url_to_the_tool():
    state = SimpleNamespace(
        allow_faq_tool=True,
        dto=SimpleNamespace(
            course=SimpleNamespace(id=7),
            settings=SimpleNamespace(artemis_base_url=OWN),
        ),
        db=MagicMock(),
        callback=None,
    )
    with patch.object(chat_tool_providers, "FaqRetrieval") as retrieval_class:
        retrieval_class.return_value.return_value = []
        chat_tool_providers.provide_faq_retrieval(state)("exam?")

    assert retrieval_class.return_value.call_args.kwargs["base_url"] == OWN


def test_rewriting_checks_consistency_against_the_instance_faqs():
    pipeline = RewritingPipeline.__new__(RewritingPipeline)
    pipeline.variant_id = "faq"
    pipeline.rewriting_handler = MagicMock()
    pipeline.rewriting_handler.chat.return_value = SimpleNamespace(
        token_usage=None, contents=[SimpleNamespace(text_content="Rewritten")]
    )
    pipeline._append_tokens = MagicMock()
    pipeline.faq_retriever = MagicMock()
    pipeline.faq_retriever.get_faqs_from_db.return_value = []
    pipeline.check_faq_consistency = MagicMock(return_value={"type": "consistent"})
    pipeline.callback = MagicMock()
    pipeline.tokens = []
    dto = RewritingPipelineExecutionDTO(
        execution={"settings": {"authenticationToken": "token", "artemisBaseUrl": OWN}},
        courseId=7,
        toBeRewritten="Text",
    )

    pipeline(dto)

    kwargs = pipeline.faq_retriever.get_faqs_from_db.call_args.kwargs
    assert (kwargs["course_id"], kwargs["base_url"]) == (7, OWN)
