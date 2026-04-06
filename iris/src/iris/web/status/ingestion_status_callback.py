import time
from typing import List, Optional

import requests as http_requests

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

    def on_status_update(self):
        """Send a status update to Artemis with retry for transient failures.

        Retries up to 3 times with linear backoff (5s, 10s, 15s) before
        giving up.  This protects hour-long pipelines from losing their
        result because Artemis was briefly unavailable (e.g. during a deploy).
        """
        last_error = None
        for attempt in range(_CALLBACK_MAX_RETRIES):
            try:
                http_requests.post(
                    self.url,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.run_id}",
                    },
                    json=self.status.model_dump(by_alias=True),
                    timeout=200,
                ).raise_for_status()
                return
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
