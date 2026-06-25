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
    """Raised when an ingestion job is cancelled by a newer job.

    This is a controlled cancellation, not an error. The job thread
    should exit cleanly and report cancellation status to Artemis.
    """

    def __init__(self, lecture_unit_id: int, reason: str = "Superseded by newer job"):
        self.lecture_unit_id = lecture_unit_id
        self.reason = reason
        super().__init__(f"Lecture {lecture_unit_id} ingestion cancelled: {reason}")
