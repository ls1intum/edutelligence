from typing import List

from .status_update import StatusCallback
from ...domain.ingestion.ingestion_status_update_dto import IngestionStatusUpdateDTO
from ...domain.status.stage_state_dto import StageStateEnum
from ...domain.status.stage_dto import StageDTO
import logging

logger = logging.getLogger(__name__)


class FaqIngestionStatus(StatusCallback):
    """
    Callback class for updating the status of a Faq ingestion Pipeline run.
    """

    def __init__(
        self,
        run_id: str,
        base_url: str,
        initial_stages: List[StageDTO] = None,
        faq_id: int = None,
    ):
        url = (
            f"{base_url}/api/public/pyris/webhooks/ingestion/faqs/runs/{run_id}/status"
        )

        current_stage_index = len(initial_stages) if initial_stages else 0
        stages = initial_stages or []
        stages += [
            StageDTO(
                weight=10, state=StageStateEnum.NOT_STARTED, name="Old faq removal"
            ),
            StageDTO(
                weight=30,
                state=StageStateEnum.NOT_STARTED,
                name="Faq Interpretation",
            ),
            StageDTO(
                weight=60,
                state=StageStateEnum.NOT_STARTED,
                name="Faq ingestion",
            ),
        ]
        status = IngestionStatusUpdateDTO(stages=stages, id=faq_id)
        stage = stages[current_stage_index]
        super().__init__(url, run_id, status, stage, current_stage_index)
