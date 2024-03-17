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
