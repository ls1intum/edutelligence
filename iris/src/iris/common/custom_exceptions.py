from typing import Optional

from fastapi import HTTPException, status


class RequiresAuthenticationException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "not_authenticated",
                "errorMessage": "Requires authentication",
            },
        )


class PermissionDeniedException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "type": "not_authorized",
                "errorMessage": "Permission denied",
            },
        )


class PipelineInvocationError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "bad_request",
                "errorMessage": "Cannot invoke pipeline",
            },
        )


class PipelineNotFoundException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "pipeline_not_found",
                "errorMessage": "Pipeline not found",
            },
        )


class IngestionCancelledException(Exception):
    """Raised when an ingestion job is superseded by a newer request.

    This is a controlled stop, not a failure. Artemis has already moved on to
    the newer run's token, so the cancelled job unwinds and exits without
    sending a terminal status update of its own.
    """

    def __init__(
        self,
        lecture_unit_id: Optional[int] = None,
        reason: str = "Superseded by a newer ingestion request",
    ):
        self.lecture_unit_id = lecture_unit_id
        self.reason = reason
        super().__init__(f"Lecture {lecture_unit_id} ingestion cancelled: {reason}")
