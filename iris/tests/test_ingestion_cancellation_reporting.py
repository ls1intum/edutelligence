"""A superseded ingestion run must not send a terminal status update.

Artemis has by then switched to the superseding run's token, so a ``fail`` here
would be dropped — or worse, mark the unit broken while the replacement works.
"""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from iris.pipeline.lecture_ingestion_update_pipeline import (
    LectureIngestionUpdatePipeline,
)

_MOD = "iris.pipeline.lecture_ingestion_update_pipeline"


def _pipeline(cancel_event):
    lecture_unit = MagicMock()
    lecture_unit.lecture_unit_id = 7
    lecture_unit.course_id = 1
    lecture_unit.lecture_id = 2

    dto = MagicMock()
    dto.lecture_unit = lecture_unit
    dto.settings = SimpleNamespace(
        authentication_token="token",
        artemis_base_url="https://artemis.example",
        artemis_llm_selection="OPENAI",
    )

    return LectureIngestionUpdatePipeline(dto, cancel_event=cancel_event)


def _run(pipeline) -> None:
    """Drive the public entry point, bypassing only the @observe wrapper."""
    LectureIngestionUpdatePipeline.__call__.__wrapped__(pipeline)


def test_cancelled_run_sends_no_terminal_status_update():
    cancel_event = threading.Event()
    cancel_event.set()
    pipeline = _pipeline(cancel_event)

    with patch(f"{_MOD}.IngestionStatusCallback") as callback_cls:
        callback = MagicMock()
        callback_cls.return_value = callback

        _run(pipeline)

    callback.fail.assert_not_called()
    callback.finish.assert_not_called()


def test_uncancelled_failure_still_reports_as_a_failure():
    """The silent path must be reserved for cancellation, not swallow bugs."""
    pipeline = _pipeline(cancel_event=None)

    with (
        patch(f"{_MOD}.IngestionStatusCallback") as callback_cls,
        patch(f"{_MOD}.lecture_update_lock"),
        patch(
            f"{_MOD}.LectureUnitPipeline.fetch_existing_properties",
            side_effect=RuntimeError("weaviate down"),
        ),
    ):
        callback = MagicMock()
        callback_cls.return_value = callback

        _run(pipeline)

    callback.fail.assert_called_once()


def test_ingestion_preparation_runs_outside_lecture_update_lock():
    lecture_unit = SimpleNamespace(
        lecture_unit_id=7,
        course_id=1,
        lecture_id=2,
        course_name="Course",
        course_description="Description",
        lecture_name="Lecture",
        lecture_unit_name="Unit",
        lecture_unit_link="",
        video_link=None,
        pdf_file_base64="pdf",
        transcription=SimpleNamespace(language="en", segments=[object()]),
        display_page_numbers=[1],
    )
    dto = MagicMock()
    dto.lecture_unit = lecture_unit
    dto.settings = SimpleNamespace(
        authentication_token="token",
        artemis_base_url="https://artemis.example",
        artemis_llm_selection="OPENAI",
    )

    pipeline = LectureIngestionUpdatePipeline(dto)

    lock_state = SimpleNamespace(inside=False, acquisitions=0)

    class TrackingLock:
        def __enter__(self):
            assert lock_state.inside is False
            lock_state.inside = True
            lock_state.acquisitions += 1

        def __exit__(self, *_args):
            lock_state.inside = False

    callback = MagicMock()
    callback.finish.side_effect = lambda **_kwargs: (
        _assert_outside_lock(lock_state),
        None,
    )[1]

    page_pipeline = MagicMock(tokens=[])
    page_pipeline.prepare_replacement.side_effect = lambda: _prepare_page(lock_state)
    page_pipeline.commit_prepared_replacement.side_effect = (
        lambda _payload: _commit_inside_lock(lock_state)
    )
    transcription_pipeline = MagicMock(tokens=[])
    transcription_pipeline.prepare_replacement.side_effect = (
        lambda: _prepare_transcription(lock_state)
    )
    transcription_pipeline.commit_prepared_replacement.side_effect = (
        lambda _payload: _commit_inside_lock(lock_state)
    )
    segment_pipeline = MagicMock(tokens=[])
    segment_pipeline.prepare_replacement.side_effect = lambda: _prepare_segments(
        lock_state
    )
    segment_pipeline.commit_prepared_replacement.side_effect = (
        lambda _payload: _commit_inside_lock(lock_state)
    )
    unit_pipeline = MagicMock()
    unit_pipeline.prepare_replacement.side_effect = lambda *_args: _prepare_unit(
        lock_state
    )
    unit_pipeline.commit_prepared_replacement.side_effect = (
        lambda **_kwargs: _commit_inside_lock(lock_state)
    )

    with (
        patch(f"{_MOD}.IngestionStatusCallback", return_value=callback),
        patch(f"{_MOD}.find_variant", return_value=MagicMock()),
        patch(f"{_MOD}.VectorDatabase") as vector_db_cls,
        patch(f"{_MOD}.lecture_update_lock", side_effect=lambda *_args: TrackingLock()),
        patch(f"{_MOD}.LectureUnitPageIngestionPipeline", return_value=page_pipeline),
        patch(
            f"{_MOD}.TranscriptionIngestionPipeline",
            return_value=transcription_pipeline,
        ),
        patch(
            f"{_MOD}.LectureUnitSegmentSummaryPipeline", return_value=segment_pipeline
        ),
        patch(f"{_MOD}.LectureUnitPipeline", return_value=unit_pipeline),
    ):
        vector_db_cls.return_value.get_client.return_value = MagicMock()
        _run(pipeline)

    # One acquisition for the initial property snapshot, then one per commit
    # window — every preparation step in between runs outside the lock.
    assert lock_state.acquisitions == 3
    callback.finish.assert_called_once()


def _assert_outside_lock(lock_state):
    assert lock_state.inside is False


def _commit_inside_lock(lock_state):
    assert lock_state.inside is True


def _prepare_page(lock_state):
    assert lock_state.inside is False
    return "en", [({"page": 1}, [0.1])]


def _prepare_transcription(lock_state):
    assert lock_state.inside is False
    return [({"segment": 1}, [0.2])]


def _prepare_segments(lock_state):
    assert lock_state.inside is False
    return (
        ["segment summary"],
        [
            {
                "slide_number": 1,
                "display_page_number": 1,
                "summary": "segment summary",
                "embedding": [0.3],
            }
        ],
    )


def _prepare_unit(lock_state):
    assert lock_state.inside is False
    return [], [0.4]
