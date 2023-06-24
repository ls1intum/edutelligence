from fastapi import APIRouter, Depends
from datetime import datetime, timezone

from app.core.custom_exceptions import BadDataException
from app.dependencies import PermissionsValidator
from app.models.dtos import SendMessageRequest, SendMessageResponse
from app.services.guidance_wrapper import GuidanceWrapper

router = APIRouter(tags=["messages"])


@router.post(
    "/api/v1/messages", dependencies=[Depends(PermissionsValidator())]
)
def send_message(body: SendMessageRequest) -> SendMessageResponse:
    guidance = GuidanceWrapper(
        model=body.preferred_model,
        handlebars=body.template.content,
        parameters=body.parameters,
    )

    try:
        content = guidance.query()
    except (KeyError, ValueError) as e:
        raise BadDataException(str(e))

    # Turn content into an array if it's not already
    if not isinstance(content, list):
        content = [content]

    return SendMessageResponse(
        usedModel=body.preferred_model,
        message=SendMessageResponse.Message(
            sentAt=datetime.now(timezone.utc), content=content
        ),
    )
