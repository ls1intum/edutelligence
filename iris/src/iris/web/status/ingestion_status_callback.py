import time
from typing import List, Optional

import requests as http_requests
from sentry_sdk import capture_exception as sentry_capture
from sentry_sdk import capture_message

from iris.common.logging_config import get_logger

from ...domain.ingestion.ingestion_status_update_dto import (
    IngestionStatusUpdateDTO,
)
from ...domain.status.stage_dto import StageDTO
from ...domain.status.stage_state_dto import StageStateEnum
from .status_update import StatusCallback

logger = get_logger(__name__)

# Retry settings for status update callbacks.
# Ingestion/transcription pipelines can run for an hour — losing a callback
# because Artemis restarted for 3 seconds is unacceptable.
_CALLBACK_MAX_RETRIES = 3
_CALLBACK_RETRY_BASE_SECONDS = 5


class IngestionStatusCallback(StatusCallback):
    """Callback for Lecture ingestion and transcription pipeline status updates.

    Extends the base StatusCallback with:
    - Optional transcription stages prepended before ingestion stages
    - Retry logic on callback delivery (protects long-running pipelines)
    """

    def __init__(
        self,
        run_id: str,
        base_url: str,
        initial_stages: Optional[List[StageDTO]] = None,
        lecture_unit_id: Optional[int] = None,
        include_transcription_stages: bool = False,
    ):
        url = f"{base_url}/api/iris/internal/webhooks/ingestion/runs/{run_id}/status"

        current_stage_index = len(initial_stages) if initial_stages else 0
        stages = list(initial_stages) if initial_stages else []

        if include_transcription_stages:
            stages += [
                StageDTO(
                    weight=10,
                    state=StageStateEnum.NOT_STARTED,
                    name="Downloading video",
                ),
                StageDTO(
                    weight=10,
                    state=StageStateEnum.NOT_STARTED,
                    name="Extracting audio",
                ),
                StageDTO(
                    weight=30,
                    state=StageStateEnum.NOT_STARTED,
                    name="Transcribing",
                ),
                StageDTO(
                    weight=20,
                    state=StageStateEnum.NOT_STARTED,
                    name="Detecting slides",
                ),
                StageDTO(
                    weight=15,
                    state=StageStateEnum.NOT_STARTED,
                    name="Aligning transcript with slides",
                ),
            ]

        stages += [
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Old slides removal",
            ),
            StageDTO(
                weight=20,
                state=StageStateEnum.NOT_STARTED,
                name="Slides Interpretation",
            ),
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Slides ingestion",
            ),
            StageDTO(
                weight=5,
                state=StageStateEnum.NOT_STARTED,
                name="Old transcriptions removal",
            ),
            StageDTO(
                weight=5,
                state=StageStateEnum.NOT_STARTED,
                name="Transcription chunking",
            ),
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Transcription summarization",
            ),
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Transcription ingestion",
            ),
            StageDTO(
                weight=30,
                state=StageStateEnum.NOT_STARTED,
                name="Lecture unit summary ingestion",
            ),
        ]
        status = IngestionStatusUpdateDTO(stages=stages, id=lecture_unit_id)
        stage = stages[current_stage_index]
        super().__init__(url, run_id, status, stage, current_stage_index)

    def _post_status(self, timeout: int) -> http_requests.Response:
        """Send the current status payload to Artemis."""
        return http_requests.post(
            self.url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.run_id}",
            },
            json=self.status.model_dump(by_alias=True),
            timeout=timeout,
        )

    def on_status_update(self) -> bool:
        """Send a status update to Artemis with retry for transient failures.

        Retries up to 3 times with linear backoff (5s, 10s, 15s) before
        giving up.  This protects hour-long pipelines from losing their
        result because Artemis was briefly unavailable (e.g. during a deploy).

        Returns:
            True if the status update was sent successfully.

        Raises:
            RuntimeError: If all retry attempts fail.
        """
        last_error = None
        for attempt in range(_CALLBACK_MAX_RETRIES):
            try:
                resp = self._post_status(timeout=200)
                logger.info(
                    "Status callback to %s returned %d",
                    self.url,
                    resp.status_code,
                )
                resp.raise_for_status()
                return True
            except http_requests.exceptions.RequestException as e:
                last_error = e
                if attempt < _CALLBACK_MAX_RETRIES - 1:
                    wait = _CALLBACK_RETRY_BASE_SECONDS * (attempt + 1)
                    logger.warning(
                        "Status update failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1,
                        _CALLBACK_MAX_RETRIES,
                        wait,
                        e,
                    )
                    time.sleep(wait)
        logger.error(
            "Status update failed after %d attempts: %s",
            _CALLBACK_MAX_RETRIES,
            last_error,
        )
        raise RuntimeError(
            f"Artemis callback failed after {_CALLBACK_MAX_RETRIES} attempts: {last_error}"
        ) from last_error

    def on_status_update_best_effort(self) -> None:
        """Best-effort status update that never raises.

        Used by error() so the error callback itself doesn't cause
        another exception when Artemis is unreachable.
        """
        try:
            resp = self._post_status(timeout=30)
            resp.raise_for_status()
            logger.info("Error callback to %s returned %d", self.url, resp.status_code)
        except http_requests.exceptions.RequestException as e:
            logger.warning("Error callback also failed (best-effort): %s", e)

    def error(
        self,
        message: str,
        exception=None,
        tokens=None,
    ):
        """Send error status to Artemis (best-effort, never raises).

        Overrides base class to use best-effort delivery so that a callback
        failure during error reporting doesn't mask the original error.
        """
        failed_stage_name = self.stage.name
        self.stage.state = StageStateEnum.ERROR
        self.stage.message = message
        self.status.result = None
        if hasattr(self.status, "suggestions"):
            self.status.suggestions = None
        self.status.tokens = tokens or self.status.tokens

        rest_of_index = self.current_stage_index + 1
        for stage in self.status.stages[rest_of_index:]:
            stage.state = StageStateEnum.SKIPPED
            stage.message = "Skipped due to previous error"

        self.stage = self.status.stages[-1]
        self.on_status_update_best_effort()

        logger.error(
            "Error occurred in job %s in stage %s: %s",
            self.run_id,
            failed_stage_name,
            message,
        )
        if exception:
            sentry_capture(exception)
        else:
            capture_message(
                f"Error occurred in job {self.run_id} in stage {failed_stage_name}: {message}"
            )
