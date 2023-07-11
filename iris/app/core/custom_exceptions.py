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


class InternalServerException(HTTPException):
    def __init__(self, error_message: str):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "type": "other",
                "errorMessage": error_message,
            },
        )


class MissingParameterException(HTTPException):
    def __init__(self, error_message: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "missing_parameter",
                "errorMessage": error_message,
            },
        )


class InvalidTemplateException(HTTPException):
    def __init__(self, error_message: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "invalid_template",
                "errorMessage": error_message,
            },
        )


class InvalidModelException(HTTPException):
    def __init__(self, error_message: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "invalid_model",
                "errorMessage": error_message,
            },
        )
