"""
Deprecated HTTP relay endpoints.

Inference offload is now handled exclusively over the secure node<->Logos
websocket session.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from node_controller.auth import verify_api_key

router = APIRouter(tags=["relay"])


@router.post(
    "/relay/lanes/{lane_id}/infer",
    summary="Deprecated: HTTP relay endpoint is disabled; use secure websocket node provider path",
    dependencies=[Depends(verify_api_key)],
    deprecated=True,
)
async def relay_lane_infer(lane_id: str):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            f"HTTP relay is deprecated and disabled for lane '{lane_id}'. "
            "Use Logos node provider websocket offload."
        ),
    )
