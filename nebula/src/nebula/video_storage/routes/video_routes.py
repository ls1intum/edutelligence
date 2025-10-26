"""
API routes for video upload and streaming (Artemis-focused)
Only essential endpoints - Artemis stores metadata, Nebula stores files
"""

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from nebula.video_storage.config import Config
from nebula.video_storage.dto import ErrorResponse, UploadResponse
from nebula.video_storage.storage import VideoStorageService

router = APIRouter()
logger = logging.getLogger(__name__)

# Initialize storage service
storage_service = VideoStorageService()


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid file format or size",
        },
        413: {"model": ErrorResponse, "description": "File too large"},
    },
)
async def upload_video(file: UploadFile = File(...)):
    """
    Upload a video file and convert to HLS format

    Returns playlist_url that Artemis should store for video playback.
    Artemis should store all other metadata (title, lecture_id, etc.)

    Args:
        file: Video file to upload

    Returns:
        UploadResponse with video_id, playlist_url, and duration
    """
    logger.info("Received upload request for file: %s", file.filename)

    # Validate file type
    if file.content_type not in Config.ALLOWED_MIME_TYPES:
        logger.warning("Invalid content type: %s", file.content_type)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid file type. Allowed types: "
                f'{\", \".join(Config.ALLOWED_MIME_TYPES)}'
            ),
        )

    # Validate file extension
    if file.filename:
        file_ext = "." + file.filename.split(".")[-1].lower()
        if file_ext not in Config.ALLOWED_EXTENSIONS:
            logger.warning("Invalid file extension: %s", file_ext)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid file extension. Allowed: "
                    f'{\", \".join(Config.ALLOWED_EXTENSIONS)}'
                ),
            )

    # Read file data
    try:
        video_data = await file.read()
    except Exception as e:
        logger.error("Error reading uploaded file: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read uploaded file",
        ) from e

    # Check file size
    if len(video_data) > Config.MAX_FILE_SIZE:
        max_size_gb = Config.MAX_FILE_SIZE / (1024**3)
        logger.warning(
            "File too large: %s bytes (max: %s)", len(video_data), Config.MAX_FILE_SIZE
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(f"File too large. Maximum size: {max_size_gb:.2f} GB"),
        )

    # Save video
    try:
        metadata = storage_service.save_video(
            video_data=video_data,
            filename=file.filename or "video.mp4",
            content_type=file.content_type or "video/mp4",
        )

        logger.info("Successfully saved video with ID: %s", metadata.video_id)

        # Generate playlist URL for Artemis
        playlist_url = f"/video-storage/playlist/{metadata.video_id}/playlist.m3u8"

        return UploadResponse(
            video_id=metadata.video_id,
            filename=metadata.filename,
            size_bytes=metadata.size_bytes,
            uploaded_at=metadata.uploaded_at,
            playlist_url=playlist_url,
            duration_seconds=metadata.duration_seconds,
        )

    except Exception as e:
        logger.error("Error saving video: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save video",
        ) from e


@router.get(
    "/playlist/{video_id}/playlist.m3u8",
    responses={
        200: {
            "description": "HLS playlist",
            "content": {"application/vnd.apple.mpegurl": {}},
        },
        404: {"model": ErrorResponse, "description": "Playlist not found"},
    },
)
async def get_playlist(video_id: str):
    """
    Get HLS playlist for video streaming in Artemis

    This endpoint is called by Artemis video player using the playlist_url
    stored in Artemis database.

    Args:
        video_id: Unique identifier of the video

    Returns:
        HLS playlist (.m3u8)
    """
    logger.info("Playlist request for video: %s", video_id)

    # Get playlist path
    playlist_path = storage_service.get_playlist_path(video_id)
    if playlist_path is None:
        logger.warning("Playlist not found: %s", video_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found"
        )

    return FileResponse(
        path=str(playlist_path),
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Cache-Control": "no-cache",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get(
    "/playlist/{video_id}/{segment_name}",
    responses={
        200: {
            "description": "HLS segment",
            "content": {"video/mp2t": {}},
        },
        404: {"model": ErrorResponse, "description": "Segment not found"},
    },
)
async def get_segment(video_id: str, segment_name: str):
    """
    Get HLS video segment

    Called automatically by the video player - not called directly by
    Artemis. The player reads the playlist and requests segments as needed.

    Args:
        video_id: Unique identifier of the video
        segment_name: Name of the segment file (e.g., segment000.ts)

    Returns:
        HLS segment (.ts)
    """
    logger.info("Segment request for video: %s, segment: %s", video_id, segment_name)

    # Get segment path
    segment_path = storage_service.get_hls_segment_path(video_id, segment_name)
    if segment_path is None:
        logger.warning("Segment not found: %s/%s", video_id, segment_name)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found"
        )

    return FileResponse(
        path=str(segment_path),
        media_type="video/mp2t",
        headers={
            "Cache-Control": "public, max-age=31536000",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.delete(
    "/delete/{video_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": ErrorResponse, "description": "Video not found"},
    },
)
async def delete_video(video_id: str):
    """
    Delete a video and all associated files

    Called by Artemis when a lecture video is removed.
    Artemis should also delete its metadata entry after calling this.

    Args:
        video_id: Unique identifier of the video
    """
    logger.info("Delete request for video: %s", video_id)

    if not storage_service.video_exists(video_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video not found"
        )

    success = storage_service.delete_video(video_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete video",
        )

    logger.info("Successfully deleted video: %s", video_id)


@router.get("/test")
async def test():
    """Test endpoint to verify service is running"""
    return {"message": "Video storage service is up", "status": "ok"}
