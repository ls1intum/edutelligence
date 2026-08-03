import time
from datetime import datetime, timezone
from typing import Optional

import requests as http_requests
from sentry_sdk import capture_exception as sentry_capture

from iris.common.logging_config import get_logger
from iris.domain.ingestion.ingestion_status_update_dto import (
    IngestionStatusUpdateDTO,
)
from iris.domain.status.activity_dto import ActivityDTO
from iris.domain.status.run_state_dto import RunStateEnum
from iris.pipeline.shared.activity_tracker import ActivityTracker
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)

# Retry settings for status update callbacks.
# Ingestion/transcription pipelines can run for an hour; losing a callback
# because Artemis restarted for a few seconds is unacceptable.
_CALLBACK_MAX_RETRIES = 3
_CALLBACK_RETRY_BASE_SECONDS = 5


class IngestionStatusCallback(StatusCallback):
    """Callback for lecture ingestion and transcription pipeline status updates."""

    def __init__(
        self,
        run_id: str,
        base_url: str,
        lecture_unit_id: Optional[int] = None,
        status_url: Optional[str] = None,
    ):
        url = (
            status_url
            or f"{base_url}/api/iris/internal/webhooks/ingestion/runs/{run_id}/status"
        )
        status = IngestionStatusUpdateDTO(
            run_state=RunStateEnum.RUNNING,
            id=lecture_unit_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        super().__init__(url, run_id, status)
        # Live per-step progress for the admin ingestion dashboard: each emit posts a RUNNING update
        # carrying the current activity snapshot, so the dashboard can render the milestone line live.
        self.activity_tracker = ActivityTracker(emit=self._emit_activities)

    def _emit_activities(self, activities: list[ActivityDTO], seq: int) -> None:
        """Post a RUNNING status update carrying the current activity snapshot."""
        self.update(activities=activities, activity_seq=seq)

    def _post_status_payload(
        self, payload: dict, timeout: int = 200
    ) -> http_requests.Response:
        """Send a pre-serialized status payload to Artemis."""
        return http_requests.post(
            self.url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.run_id}",
            },
            json=payload,
            timeout=timeout,
        )

    def on_status_update(self) -> bool:
        """Send a status update to Artemis with bounded retry and no raise."""
        last_error = None
        payload = self._serialize_status()
        for attempt in range(_CALLBACK_MAX_RETRIES):
            try:
                resp = self._post_status_payload(payload, timeout=200)
                logger.info(
                    "Status callback to %s returned %d",
                    self.url,
                    resp.status_code,
                )
                resp.raise_for_status()
                return True
            except http_requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt < _CALLBACK_MAX_RETRIES - 1:
                    wait_seconds = _CALLBACK_RETRY_BASE_SECONDS * (attempt + 1)
                    logger.warning(
                        "Status update failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1,
                        _CALLBACK_MAX_RETRIES,
                        wait_seconds,
                        exc,
                    )
                    time.sleep(wait_seconds)

        logger.error(
            "Status update failed after %d attempts: %s",
            _CALLBACK_MAX_RETRIES,
            last_error,
        )
        if last_error is not None:
            sentry_capture(last_error)
        return False
