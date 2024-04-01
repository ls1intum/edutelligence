from fastapi import APIRouter, status, Response

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router.post("/lecture-units")
def lecture_webhook():
    return Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/assignment")
def assignment_webhook():
    return Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)
