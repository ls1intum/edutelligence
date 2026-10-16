from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from iris.common.logging_config import get_logger

logger = get_logger(__name__)


def describe_validation_errors(exc: RequestValidationError) -> str:
    """Describe what failed validation without the input values.

    The default description quotes the input, and a request from Artemis carries the
    callback token of its run, which must not end up in a log or a response.
    """
    descriptions = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()))
        descriptions.append(
            f"{location}: {error.get("msg", "")} ({error.get("type", "")})"
        )
    return "; ".join(descriptions)


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    exc_str = describe_validation_errors(exc)
    logger.error("Validation error | path=%s | error=%s", request.url.path, exc_str)
    content = {"status_code": 10422, "message": exc_str, "data": None}
    return JSONResponse(
        content=content, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
    )
