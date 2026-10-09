from iris.common.logging_config import get_logger
from iris.web.status.ingestion_status_callback import IngestionStatusCallback

logger = get_logger(__name__)


class CourseMemoryIngestionStatus(IngestionStatusCallback):
    """Callback class for updating the status of a Course Memory ingestion run."""

    def __init__(self, run_id: str, base_url: str):
        url = (
            f"{base_url}/api/iris/internal/webhooks/ingestion/course-memory/"
            f"runs/{run_id}/status"
        )
        super().__init__(run_id, base_url, status_url=url)
