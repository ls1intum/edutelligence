from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from parsimonious.exceptions import IncompleteParseError

from app.core.custom_exceptions import (
    MissingParameterException,
    InvalidTemplateException,
    InternalServerException,
    InvalidModelException,
)
from app.dependencies import TokenPermissionsValidator
from app.models.dtos import SendMessageRequest, SendMessageResponse
from app.services.circuit_breaker import CircuitBreaker
from app.services.guidance_wrapper import GuidanceWrapper
from app.config import settings

router = APIRouter(tags=["messages"])


@router.post(
    "/api/v1/messages", dependencies=[Depends(TokenPermissionsValidator())]
)
def send_message(body: SendMessageRequest) -> SendMessageResponse:
    try:
        model = settings.pyris.llms[body.preferred_model]
    except ValueError as e:
        raise InvalidModelException(str(e))

    guidance = GuidanceWrapper(
        model=model,
        handlebars=body.template.content,
        parameters=body.parameters,
    )

    try:
        content = CircuitBreaker.protected_call(
            func=guidance.query,
            cache_key=body.preferred_model,
            accepted_exceptions=(KeyError, SyntaxError, IncompleteParseError),
        )
    except KeyError as e:
        raise MissingParameterException(str(e))
    except (SyntaxError, IncompleteParseError) as e:
        raise InvalidTemplateException(str(e))
    except Exception as e:
        raise InternalServerException(str(e))

    # Turn content into an array if it's not already
    if not isinstance(content, list):
        content = [content]

    return SendMessageResponse(
        usedModel=body.preferred_model,
        message=SendMessageResponse.Message(
            sentAt=datetime.now(timezone.utc), content=content
        ),
    )
