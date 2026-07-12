from iris.common.logging_config import get_logger
from iris.web.status.ingestion_status_callback import IngestionStatusCallback

logger = get_logger(__name__)


class LecturesDeletionStatusCallback(IngestionStatusCallback):
    """Callback class for updating lecture deletion pipeline run status."""

    def __init__(self, run_id: str, base_url: str):
        url = f"{base_url}/api/iris/internal/webhooks/ingestion/runs/{run_id}/status"
        super().__init__(run_id, base_url, status_url=url)
