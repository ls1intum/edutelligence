"""Regression tests for the convergent lecture ingestion write path.

Covers the invariants that keep a lecture unit from ending up partially
ingested: all LLM work happens before any delete, every Weaviate batch and
delete result is verified, vision failures fail the run instead of degrading
it, and stale segments are pruned.
"""

# pylint: disable=protected-access,import-outside-toplevel

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.ingestion_errors import (
    SLIDE_VISION_FAILED,
    STALE_CONTENT_DELETE_FAILED,
    VECTOR_STORE_WRITE_FAILED,
    IngestionStageError,
)
from iris.pipeline.lecture_ingestion_pipeline import (
    VISION_MAX_ATTEMPTS,
    LectureUnitPageIngestionPipeline,
)
from iris.pipeline.lecture_ingestion_update_pipeline import (
    LectureIngestionUpdatePipeline,
)
from iris.pipeline.lecture_unit_segment_summary_pipeline import (
    LectureUnitSegmentSummaryPipeline,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)
from iris.vector_database.lecture_unit_schema import LectureUnitSchema


def _delete_result(failed: int = 0, matches: int = 0) -> SimpleNamespace:
    return SimpleNamespace(failed=failed, matches=matches, successful=matches - failed)


def _patch_pdf(monkeypatch, page_count: int = 1) -> None:
    fake_doc = SimpleNamespace(page_count=page_count)
    monkeypatch.setattr(
        "iris.pipeline.lecture_ingestion_pipeline.save_pdf",
        MagicMock(return_value="/tmp/test.pdf"),
    )
    monkeypatch.setattr(
        "iris.pipeline.lecture_ingestion_pipeline.cleanup_temporary_file",
        MagicMock(),
    )
    monkeypatch.setattr(
        "iris.pipeline.lecture_ingestion_pipeline.fitz.open",
        MagicMock(return_value=fake_doc),
    )


_CURRENT_RUN_ID = "run-current"
_UUID_OLD = "11111111-1111-1111-1111-111111111111"
_UUID_NEW = "22222222-2222-2222-2222-222222222222"
_UUID_GHOST = "99999999-9999-9999-9999-999999999999"


def _sample_chunk(page_number: int = 1, text: str = "text") -> dict:
    return {
        LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value: text,
        LectureUnitPageChunkSchema.PAGE_NUMBER.value: page_number,
    }


def _page_pipeline(
    events: list, stale_rows=None, ghost_uuids=None
) -> LectureUnitPageIngestionPipeline:
    pipeline = object.__new__(LectureUnitPageIngestionPipeline)
    lecture_unit = SimpleNamespace(
        pdf_file_base64="cGRm",
        attachment_version=2,
        course_id=11,
        lecture_id=12,
        lecture_unit_id=13,
        lecture_name="Lecture",
        lecture_unit_name="Unit",
        course_name="Course",
        display_page_numbers=None,
        content_fingerprint="v1:fp",
        force_reingest=False,
        ingestion_run_id=_CURRENT_RUN_ID,
        chunk_counts_by_page=None,
        quality_score=None,
        quality_flags=None,
    )
    pipeline.dto = SimpleNamespace(
        lecture_unit=lecture_unit,
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.callback = SimpleNamespace(update=MagicMock(), fail=MagicMock())
    pipeline.tokens = []
    pipeline.course_language = "en"
    pipeline._hidden_until_by_page = {}
    pipeline.skipped = False
    pipeline.kept_previous_generation = False

    def record_delete(**_kwargs):
        events.append("delete")
        return _delete_result(matches=1)

    batch = SimpleNamespace(
        add_object=MagicMock(side_effect=lambda **_kwargs: events.append("insert"))
    )
    batch_context = MagicMock()
    batch_context.__enter__ = MagicMock(return_value=batch)
    batch_context.__exit__ = MagicMock(return_value=None)

    def route_fetch(**kwargs):
        # The sweep asks only for the run id; every other read gets no rows so
        # the structural skip check keeps deciding "needs update".
        if kwargs.get("return_properties") == [
            LectureUnitPageChunkSchema.INGESTION_RUN_ID.value
        ]:
            return SimpleNamespace(objects=list(stale_rows or []))
        return SimpleNamespace(objects=[])

    ghosts = set(ghost_uuids or [])

    def confirm_by_id(object_uuid):
        # A ghost uuid has no object-store record (returns None); every other row
        # is a real, object-store-confirmed generation.
        return None if object_uuid in ghosts else SimpleNamespace()

    pipeline.collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(side_effect=route_fetch),
            fetch_object_by_id=MagicMock(side_effect=confirm_by_id),
        ),
        data=SimpleNamespace(delete_many=MagicMock(side_effect=record_delete)),
        batch=SimpleNamespace(
            rate_limit=MagicMock(return_value=batch_context),
            failed_objects=[],
        ),
    )
    pipeline.lecture_unit_collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=[]))
        )
    )
    pipeline.llm_embedding = SimpleNamespace(
        embed=MagicMock(side_effect=lambda _text: events.append("embed") or [0.1])
    )
    return pipeline


def _stale_row(run_id="run-old", uuid=_UUID_OLD):
    return SimpleNamespace(
        uuid=uuid,
        properties={LectureUnitPageChunkSchema.INGESTION_RUN_ID.value: run_id},
    )


def test_page_replacement_writes_before_purging_old_generations(monkeypatch):
    events: list = []
    pipeline = _page_pipeline(events, stale_rows=[_stale_row()])
    pipeline.chunk_data = MagicMock(
        side_effect=lambda **_kwargs: events.append("chunk") or [_sample_chunk()]
    )
    _patch_pdf(monkeypatch)

    course_language = pipeline()[0]

    assert course_language == "en"
    # The new generation is inserted before anything is deleted, so a crash
    # mid-write can duplicate but never destroy the stored content.
    assert events == ["chunk", "embed", "insert", "delete"]
    pipeline.callback.fail.assert_not_called()


def test_convergence_ignores_object_store_ghost_generations(monkeypatch):
    """A ghost generation (scan-visible but absent from the object store) must not
    trigger a convergence escalation or a false STALE_CONTENT_DELETE_FAILED: the
    unit's only real generation is already clean and ghosts cannot be deleted."""
    events: list = []
    real_row = _stale_row(run_id="run-new", uuid=_UUID_NEW)
    ghost_row = _stale_row(run_id="run-ghost", uuid=_UUID_GHOST)
    pipeline = _page_pipeline(
        events, stale_rows=[real_row, ghost_row], ghost_uuids=[_UUID_GHOST]
    )
    pipeline.chunk_data = MagicMock(
        side_effect=lambda **_kwargs: events.append("chunk") or [_sample_chunk()]
    )
    _patch_pdf(monkeypatch)

    course_language = pipeline()[0]

    assert course_language == "en"
    # Only the real generation counts, so the unit converges after the single
    # purge: no escalation delete-and-rewrite, no failure raised.
    assert events == ["chunk", "embed", "insert", "delete"]
    pipeline.callback.fail.assert_not_called()


def test_page_replacement_purges_by_unit_identity_every_run(monkeypatch):
    # The purge is a single unit-scoped delete that keeps this run's written ids
    # and removes everything else; it runs every time (idempotent when the unit is
    # already clean) so previous generations and ghost rows always converge away.
    events: list = []
    pipeline = _page_pipeline(events)
    pipeline.chunk_data = MagicMock(
        side_effect=lambda **_kwargs: events.append("chunk") or [_sample_chunk()]
    )
    _patch_pdf(monkeypatch)

    pipeline()

    assert events == ["chunk", "embed", "insert", "delete"]
    pipeline.collection.data.delete_many.assert_called_once()


def test_page_replacement_fails_run_when_batch_drops_objects(monkeypatch):
    events: list = []
    pipeline = _page_pipeline(events)
    pipeline.collection.batch.failed_objects = [SimpleNamespace(message="boom")]
    pipeline.chunk_data = MagicMock(return_value=[_sample_chunk()])
    _patch_pdf(monkeypatch)

    with pytest.raises(IngestionStageError) as exc_info:
        pipeline()

    assert exc_info.value.error_code == VECTOR_STORE_WRITE_FAILED
    pipeline.callback.fail.assert_not_called()


def test_page_replacement_fails_run_when_sweep_delete_fails(monkeypatch):
    events: list = []
    pipeline = _page_pipeline(events, stale_rows=[_stale_row()])
    pipeline.collection.data.delete_many = MagicMock(
        return_value=_delete_result(failed=1, matches=3)
    )
    pipeline.chunk_data = MagicMock(return_value=[_sample_chunk()])
    _patch_pdf(monkeypatch)

    with pytest.raises(IngestionStageError) as exc_info:
        pipeline()

    assert exc_info.value.error_code == STALE_CONTENT_DELETE_FAILED


def test_unit_row_replacement_fails_run_when_delete_fails(monkeypatch):
    """The unit-row write path must verify its delete like every other delete."""
    from iris.pipeline.lecture_unit_pipeline import LectureUnitPipeline

    monkeypatch.setattr(
        "iris.pipeline.lecture_unit_pipeline.LectureUnitSegmentSummaryPipeline",
        MagicMock(return_value=MagicMock(return_value=([], []))),
    )
    monkeypatch.setattr(
        "iris.pipeline.lecture_unit_pipeline.LectureUnitSummaryPipeline",
        MagicMock(return_value=MagicMock(return_value=("summary", []))),
    )

    pipeline = object.__new__(LectureUnitPipeline)
    pipeline.weaviate_client = MagicMock()
    pipeline.local = True
    pipeline.callback = None
    pipeline.llm_embedding = SimpleNamespace(embed=MagicMock(return_value=[0.1]))

    # No stored row is reused, so the pipeline writes a new row and then purges
    # the rest by unit identity. The purge's delete fails, and that must fail the run.
    pipeline.lecture_unit_collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=[]))
        ),
        data=SimpleNamespace(
            delete_many=MagicMock(return_value=_delete_result(failed=1, matches=1)),
            insert=MagicMock(return_value=_UUID_NEW),
        ),
    )
    lecture_unit = SimpleNamespace(
        course_id=11,
        lecture_id=12,
        lecture_unit_id=13,
        base_url="https://artemis.example",
        course_name="Course",
        course_description="",
        course_language="en",
        lecture_name="Lecture",
        lecture_unit_name="Unit",
        lecture_unit_link="",
        video_link="",
        content_fingerprint="v1:abc",
        lecture_unit_summary=None,
        ingestion_run_id=_CURRENT_RUN_ID,
        expected_chunk_counts_json=None,
        pdf_page_count=1,
        pipeline_version=1,
        quality_score=None,
        quality_flags_json=None,
        content_unchanged=False,
    )

    with pytest.raises(IngestionStageError) as exc_info:
        pipeline(lecture_unit, initial_properties={})

    assert exc_info.value.error_code == STALE_CONTENT_DELETE_FAILED
    # The new generation's row is written before the sweep touches anything.
    pipeline.lecture_unit_collection.data.insert.assert_called_once()


def test_attachment_needs_update_is_structural():
    pipeline = object.__new__(LectureUnitPageIngestionPipeline)
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            attachment_version=2, course_id=1, lecture_id=2, lecture_unit_id=3
        ),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.lecture_unit_collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=[]))
        )
    )

    def needs_update(stored_chunks, page_count):
        rows = [
            SimpleNamespace(
                properties={
                    LectureUnitPageChunkSchema.PAGE_NUMBER.value: page,
                    LectureUnitPageChunkSchema.PAGE_VERSION.value: version,
                    LectureUnitPageChunkSchema.INGESTION_RUN_ID.value: run_id,
                    LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value: display,
                }
            )
            for page, version, run_id, display in stored_chunks
        ]
        pipeline.collection = SimpleNamespace(
            query=SimpleNamespace(
                fetch_objects=MagicMock(return_value=SimpleNamespace(objects=rows))
            )
        )
        return pipeline.check_if_attachment_needs_update(page_count)

    run = _CURRENT_RUN_ID
    assert needs_update([], page_count=2) is True
    assert needs_update([(1, None, run, 1), (2, None, run, 2)], page_count=2) is True
    assert needs_update([(1, 3, run, 1), (2, 3, run, 2)], page_count=2) is True
    assert needs_update([(1, 2, run, 1)], page_count=2) is True
    assert (
        needs_update([(1, 2, run, 1), (2, 2, run, 2), (3, 2, run, 3)], page_count=2)
        is True
    )
    # Mixed ingestion generations mean a crashed write left old and new rows.
    assert needs_update([(1, 2, run, 1), (2, 2, "run-old", 2)], page_count=2) is True
    # A null display number is legacy data; re-ingest to repopulate real numbers.
    assert needs_update([(1, 2, run, None), (2, 2, run, 2)], page_count=2) is True
    assert needs_update([(1, 2, run, 1), (2, 2, run, 2)], page_count=2) is False
    # Legacy rows without any run id stay skippable when otherwise complete.
    assert needs_update([(1, 2, None, 1), (2, 2, None, 2)], page_count=2) is False


def test_attachment_needs_update_when_stored_chunk_counts_mismatch():
    """A crash inside a batch flush can drop chunks below page granularity."""
    pipeline = object.__new__(LectureUnitPageIngestionPipeline)
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            attachment_version=2, course_id=1, lecture_id=2, lecture_unit_id=3
        ),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    unit_row = SimpleNamespace(
        properties={LectureUnitSchema.EXPECTED_CHUNK_COUNTS.value: '{"1": 2, "2": 1}'}
    )
    pipeline.lecture_unit_collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=[unit_row]))
        )
    )
    stored_rows = [
        SimpleNamespace(
            properties={
                LectureUnitPageChunkSchema.PAGE_NUMBER.value: page,
                LectureUnitPageChunkSchema.PAGE_VERSION.value: 2,
                LectureUnitPageChunkSchema.INGESTION_RUN_ID.value: _CURRENT_RUN_ID,
                LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value: page,
            }
        )
        for page in (1, 2)
    ]
    pipeline.collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=stored_rows))
        )
    )

    # Pages 1..2 are covered, but page 1 should hold two chunks and holds one.
    assert pipeline.check_if_attachment_needs_update(2) is True


def test_interpret_image_retries_then_fails_the_run():
    pipeline = object.__new__(LectureUnitPageIngestionPipeline)
    pipeline.tokens = []
    pipeline._append_tokens = MagicMock()
    pipeline.llm_chat = SimpleNamespace(
        chat=MagicMock(side_effect=RuntimeError("vision down"))
    )

    with pytest.raises(IngestionStageError) as exc_info:
        pipeline.interpret_image("aW1n", "", "Lecture", "en")

    assert exc_info.value.error_code == SLIDE_VISION_FAILED
    assert pipeline.llm_chat.chat.call_count == VISION_MAX_ATTEMPTS


def test_interpret_image_rejects_empty_descriptions():
    pipeline = object.__new__(LectureUnitPageIngestionPipeline)
    pipeline.tokens = []
    pipeline._append_tokens = MagicMock()
    empty_response = SimpleNamespace(
        token_usage=None,
        contents=[
            SimpleNamespace(
                text_content='{"display_page_number": 3, "academic_description": ""}'
            )
        ],
    )
    pipeline.llm_chat = SimpleNamespace(chat=MagicMock(return_value=empty_response))

    with pytest.raises(IngestionStageError) as exc_info:
        pipeline.interpret_image("aW1n", "", "Lecture", "en")

    assert exc_info.value.error_code == SLIDE_VISION_FAILED
    assert pipeline.llm_chat.chat.call_count == VISION_MAX_ATTEMPTS


def test_update_pipeline_forwards_stage_error_code_once():
    pipeline = object.__new__(LectureIngestionUpdatePipeline)
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            course_id=1,
            course_name="Course",
            course_description="",
            lecture_id=2,
            lecture_name="Lecture",
            lecture_unit_id=3,
            lecture_unit_name="Unit",
            lecture_unit_link="",
            video_link=None,
            transcription=None,
            content_fingerprint=None,
            chunk_counts_by_page=None,
            pdf_page_count=None,
            quality_score=None,
            quality_flags=None,
        ),
        settings=SimpleNamespace(
            authentication_token="run-1",
            artemis_base_url="https://artemis.example",
            artemis_llm_selection=None,
        ),
    )
    pipeline.variant_id = "default"
    pipeline._is_local = False
    pipeline._run_ingestion = MagicMock(
        side_effect=IngestionStageError(SLIDE_VISION_FAILED, "page 4 failed")
    )
    callback = MagicMock()

    with (
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.IngestionStatusCallback",
            return_value=callback,
        ),
        patch("iris.pipeline.lecture_ingestion_update_pipeline.VectorDatabase"),
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.LectureUnitPipeline"
        ) as unit_pipeline,
    ):
        unit_pipeline.fetch_existing_properties.return_value = {}
        pipeline._run()

    callback.fail.assert_called_once()
    assert callback.fail.call_args.kwargs["code"] == SLIDE_VISION_FAILED


def test_force_reingest_bypasses_the_structural_skip(monkeypatch):
    events: list = []
    pipeline = _page_pipeline(events)
    pipeline.dto.lecture_unit.force_reingest = True
    pipeline.check_if_attachment_needs_update = MagicMock(return_value=False)
    pipeline.chunk_data = MagicMock(
        side_effect=lambda **_kwargs: events.append("chunk") or [_sample_chunk()]
    )
    _patch_pdf(monkeypatch)

    pipeline()

    # The skip check is not even consulted: unchanged content is re-processed.
    pipeline.check_if_attachment_needs_update.assert_not_called()
    assert "chunk" in events
    assert "insert" in events


def test_quality_reingest_keeps_the_better_stored_generation(monkeypatch):
    events: list = []
    pipeline = _page_pipeline(events)
    pipeline.dto.lecture_unit.force_reingest = True
    stored_unit_row = SimpleNamespace(
        properties={
            LectureUnitSchema.QUALITY_SCORE.value: 0.9,
            LectureUnitSchema.EXPECTED_CHUNK_COUNTS.value: '{"1": 3}',
            LectureUnitSchema.QUALITY_FLAGS.value: '["thin pages: [2]"]',
        }
    )
    pipeline.lecture_unit_collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(
                return_value=SimpleNamespace(objects=[stored_unit_row])
            )
        )
    )
    # The re-run produces a thin page, scoring below the stored generation.
    pipeline.chunk_data = MagicMock(return_value=[_sample_chunk(text="tiny")])
    _patch_pdf(monkeypatch)

    pipeline()

    # Nothing was embedded or written: the stored generation stays.
    assert "insert" not in events
    assert "embed" not in events
    assert pipeline.kept_previous_generation is True
    # The kept generation's ledger travels on the DTO into the unit row rewrite.
    assert pipeline.dto.lecture_unit.quality_score == 0.9
    assert pipeline.dto.lecture_unit.chunk_counts_by_page == {1: 3}


def test_purge_other_rows_deletes_everything_except_kept_ids():
    from iris.vector_database.batch_verify import purge_other_rows

    delete_many = MagicMock(return_value=_delete_result(matches=5))
    collection = SimpleNamespace(data=SimpleNamespace(delete_many=delete_many))

    purged = purge_other_rows(collection, MagicMock(), [_UUID_NEW], "page chunks")

    # A single unit-scoped delete keeps this run's ids and removes the rest.
    assert purged == 5
    delete_many.assert_called_once()


def test_purge_other_rows_skips_when_nothing_to_keep():
    """An empty write must never trigger a unit-wide wipe."""
    from iris.vector_database.batch_verify import purge_other_rows

    delete_many = MagicMock()
    collection = SimpleNamespace(data=SimpleNamespace(delete_many=delete_many))

    purged = purge_other_rows(collection, MagicMock(), [], "page chunks")

    assert purged == 0
    delete_many.assert_not_called()


def test_purge_other_rows_fails_when_delete_reports_failures():
    from iris.vector_database.batch_verify import purge_other_rows

    collection = SimpleNamespace(
        data=SimpleNamespace(
            delete_many=MagicMock(return_value=_delete_result(failed=2, matches=5))
        )
    )

    with pytest.raises(IngestionStageError) as exc_info:
        purge_other_rows(collection, MagicMock(), [_UUID_NEW], "page chunks")

    assert exc_info.value.error_code == STALE_CONTENT_DELETE_FAILED


def _reconcile(raw):
    return LectureUnitPageIngestionPipeline._reconcile_display_page_numbers(raw)


def test_reconcile_fills_unread_title_slide_from_offset():
    # Title slide unread, the rest numbered == physical page (offset 0).
    assert _reconcile([-1, 2, 3, 4]) == [1, 2, 3, 4]


def test_reconcile_applies_a_constant_offset_for_a_mid_deck_gap():
    # Printed == physical + 2 (two unnumbered lead slides); the gap fills to 6.
    assert _reconcile([3, 4, 5, -1, 7]) == [3, 4, 5, 6, 7]


def test_reconcile_maps_front_matter_before_page_one_to_unknown():
    # Numbering starts at physical page 11 (dominant offset -10). The 10
    # front-matter slides fall before printed "page 1", so they map to -1
    # ("unknown"), never to 0 or a negative page number.
    raw = [-1] * 10 + [1, 2, 3, 4, 5]
    reconciled = _reconcile(raw)
    assert reconciled == [-1] * 10 + [1, 2, 3, 4, 5]
    assert all(value == -1 or value > 0 for value in reconciled)


def test_reconcile_interpolates_between_read_neighbors():
    assert _reconcile([5, -1, 7]) == [5, 6, 7]


def test_reconcile_falls_back_to_sequential_when_nothing_is_read():
    assert _reconcile([-1, -1, -1]) == [1, 2, 3]


def test_reconcile_keeps_confidently_read_numbers():
    assert _reconcile([1, 2, 3, 4, 5]) == [1, 2, 3, 4, 5]


def test_reconcile_snaps_misread_outliers_to_dominant_offset():
    # Vision misread several slides as "6"; the majority read their true number,
    # so every page snaps to the dominant offset (0) and the 6s are corrected.
    assert _reconcile([1, 6, 6, 4, 5, 6, 6, 8, 9, 10]) == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
    ]


def test_reconcile_without_a_majority_keeps_confident_reads():
    # No offset commands a strict majority (2 of 4), so reads are trusted rather
    # than overridden — a genuinely irregular deck is left as vision saw it.
    assert _reconcile([1, 1, 1, 4]) == [1, 1, 1, 4]


def test_detect_course_language_uses_whole_deck_dominant():
    from iris.pipeline.lecture_ingestion_pipeline import detect_course_language

    # English dominates; a lone formula-only slide cannot flip the verdict because
    # detection is over the whole corpus, not one page (no content is special-cased).
    pages = [
        "Introduction to deep learning and neural network optimization methods. " * 4,
        "𝒔 𝛻𝜽 𝛽 ∘ ε 𝑘+1",
        "The lecture explains gradient descent and backpropagation in detail. " * 4,
    ]
    assert detect_course_language(pages) == "en"


def test_detect_course_language_floors_to_default_on_sparse_text():
    from iris.pipeline.lecture_ingestion_pipeline import detect_course_language

    # Too little text to judge → default rather than a guess from a scrap.
    assert detect_course_language(["", "12", "𝛻"]) == "en"


def test_resolve_course_language_prefers_declared_artemis_language():
    pipeline = object.__new__(LectureUnitPageIngestionPipeline)
    pipeline.dto = SimpleNamespace(lecture_unit=SimpleNamespace(course_language="de"))
    # The declared language is authoritative: the document is never consulted.
    assert pipeline._resolve_course_language(doc=None) == "de"


def test_pipeline_version_stamped_only_when_content_pipeline_ran():
    """A metadata-only re-dispatch (no chunk counts) must not bump the pipeline version.

    Otherwise the row would read as already on the current version while its quality_score
    stayed at the old low value, permanently disarming the once-per-version quality requeue.
    """
    from iris.common.ingestion_version import INGESTION_PIPELINE_VERSION

    pipeline = object.__new__(LectureIngestionUpdatePipeline)

    def dto_with(chunk_counts):
        lecture_unit = SimpleNamespace(
            course_id=1,
            course_name="Course",
            course_description="",
            lecture_id=2,
            lecture_name="Lecture",
            lecture_unit_id=3,
            lecture_unit_name="Unit",
            lecture_unit_link="link",
            video_link=None,
            content_fingerprint="fp",
            ingestion_run_id="run",
            chunk_counts_by_page=chunk_counts,
            pdf_page_count=7,
            quality_flags=None,
            quality_score=0.4,
        )
        return SimpleNamespace(
            lecture_unit=lecture_unit,
            settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
        )

    pipeline.dto = dto_with({1: 5})
    ran = pipeline._build_lecture_unit_dto()  # pylint: disable=protected-access
    assert ran.pipeline_version == INGESTION_PIPELINE_VERSION

    pipeline.dto = dto_with(None)
    skipped = pipeline._build_lecture_unit_dto()  # pylint: disable=protected-access
    assert skipped.pipeline_version is None
    # quality_score is still carried so the ledger fallback preserves/compares it.
    assert skipped.quality_score == 0.4


def test_stale_segments_are_pruned_after_the_slide_loop():
    pipeline = object.__new__(LectureUnitSegmentSummaryPipeline)
    pipeline.lecture_unit_dto = SimpleNamespace(
        course_id=1,
        lecture_id=2,
        lecture_unit_id=3,
        base_url="https://artemis.example",
        lecture_name="Lecture",
    )
    delete_many = MagicMock(return_value=_delete_result(matches=2))
    pipeline.lecture_unit_segment_collection = SimpleNamespace(
        data=SimpleNamespace(delete_many=delete_many)
    )

    pipeline._prune_stale_segments(1, 5)

    delete_many.assert_called_once()


def test_stale_segment_prune_failure_fails_the_run():
    pipeline = object.__new__(LectureUnitSegmentSummaryPipeline)
    pipeline.lecture_unit_dto = SimpleNamespace(
        course_id=1,
        lecture_id=2,
        lecture_unit_id=3,
        base_url="https://artemis.example",
        lecture_name="Lecture",
    )
    pipeline.lecture_unit_segment_collection = SimpleNamespace(
        data=SimpleNamespace(
            delete_many=MagicMock(return_value=_delete_result(failed=1, matches=2))
        )
    )

    with pytest.raises(IngestionStageError) as exc_info:
        pipeline._prune_stale_segments(1, 5)

    assert exc_info.value.error_code == STALE_CONTENT_DELETE_FAILED
