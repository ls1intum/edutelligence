from fastapi import APIRouter, Response, status

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("/")
def health():
    return Response(
        status_code=status.HTTP_200_OK,
        content=b"[]",
        media_type="application/json",
    )
