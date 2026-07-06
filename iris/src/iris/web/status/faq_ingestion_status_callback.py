from typing import Optional

from iris.common.logging_config import get_logger
from iris.web.status.ingestion_status_callback import IngestionStatusCallback

logger = get_logger(__name__)


class FaqIngestionStatus(IngestionStatusCallback):
    """Callback class for updating FAQ ingestion pipeline run status."""

    def __init__(
        self,
        run_id: str,
        base_url: str,
        faq_id: Optional[int] = None,
    ):
        url = (
            f"{base_url}/api/iris/internal/webhooks/ingestion/faqs/runs/{run_id}/status"
        )
        super().__init__(run_id, base_url, lecture_unit_id=faq_id, status_url=url)
