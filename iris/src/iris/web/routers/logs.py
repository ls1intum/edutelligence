"""Internal endpoint exposing Iris's recent ingestion log records to Artemis.

Artemis merges these with its own records in the admin ingestion dashboard, so an
administrator can read one ordered story across both services. Without it the
Artemis side can only report the error key an ingestion run ended with, never the
reason behind it, which lives here.

Internal and token-guarded, exactly like the ingestion webhooks: the records
carry course content and failure detail, so they are not public.
"""

from fastapi import APIRouter, Depends

from iris.common import recent_logs
from iris.dependencies import TokenValidator

router = APIRouter(prefix="/api/v1/internal/logs", tags=["logs"])


@router.get("/recent", dependencies=[Depends(TokenValidator())])
def get_recent_logs(limit: int = 500, level: str | None = None):
    """Return the most recent captured ingestion records, newest first.

    :param limit: how many records to return, capped at the buffer size
    :param level: return only records at exactly this level, or all when omitted
    :return: the records, newest first
    """
    return recent_logs.snapshot(limit=limit, level=level)
