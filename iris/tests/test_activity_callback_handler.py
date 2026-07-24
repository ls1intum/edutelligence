from uuid import uuid4

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.domain.status.activity_dto import ActivityKind, ActivityState
from iris.pipeline.shared.activity_callback_handler import ActivityCallbackHandler
from iris.pipeline.shared.activity_tracker import ActivityTracker
from iris.tools.activity_metadata import curate_detail


def _handler():
    emitted = []
    tracker = ActivityTracker(lambda items, seq: emitted.append((seq, items)))
    return ActivityCallbackHandler(tracker), emitted


def test_tool_start_and_end_pair_by_langchain_run_id():
    handler, emitted = _handler()
    run_id = uuid4()

    handler.on_tool_start(
        {"name": "lecture_content_retrieval"},
        "",
        run_id=run_id,
        inputs={"query": "sorting algorithms"},
    )
    handler.on_tool_end(["section one", "section two"], run_id=run_id)

    final_item = emitted[-1][1][0]
    assert [entry[0] for entry in emitted] == [1, 2]
    assert final_item.kind == ActivityKind.TOOL
    assert final_item.name == "lecture_content_retrieval"
    assert final_item.detail == "sorting algorithms"
    assert final_item.state == ActivityState.FINISHED
    assert final_item.result == "2 sections"
    assert final_item.duration_millis is not None


def test_unmapped_tool_emits_name_only_item():
    handler, emitted = _handler()
    run_id = uuid4()

    handler.on_tool_start(
        {"name": "unmapped_tool"},
        "",
        run_id=run_id,
        inputs={"query": "ignored"},
    )

    item = emitted[-1][1][0]
    assert item.name == "unmapped_tool"
    assert item.detail is None
    assert item.result is None


def test_unknown_tool_end_does_not_raise():
    handler, emitted = _handler()

    handler.on_tool_end("unused", run_id=uuid4())

    assert not emitted


def test_handler_swallow_internal_curation_error(monkeypatch, caplog):
    handler, emitted = _handler()

    def explode(unused_tool_name, unused_inputs):
        raise RuntimeError("curation failed")

    monkeypatch.setattr(
        "iris.pipeline.shared.activity_callback_handler.curate_detail", explode
    )

    handler.on_tool_start(
        {"name": "lecture_content_retrieval"},
        "",
        run_id=uuid4(),
        inputs={"query": "sorting"},
    )

    assert not emitted
    assert "Activity callback failed during tool start" in caplog.text


def test_tool_error_marks_item_failed():
    handler, emitted = _handler()
    run_id = uuid4()

    handler.on_tool_start({"name": "faq_content_retrieval"}, "", run_id=run_id)
    handler.on_tool_error(RuntimeError("boom"), run_id=run_id)

    item = emitted[-1][1][0]
    assert item.state == ActivityState.FAILED
    assert item.duration_millis is not None


def test_curation_truncates_detail_to_120_characters():
    detail = curate_detail("memiris_search_for_memories", {"query": "x" * 150})

    assert detail == "x" * 120
