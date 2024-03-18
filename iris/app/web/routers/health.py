from fastapi import APIRouter, status, Response, Depends

from app.dependencies import TokenValidator

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get(
    "/",
    dependencies=[Depends(TokenValidator())],
)
def health_check():
    return Response(status_code=status.HTTP_200_OK)
