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
