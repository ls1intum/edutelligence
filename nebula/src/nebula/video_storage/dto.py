"""
Data Transfer Objects for video storage service
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class VideoMetadata(BaseModel):
    """Metadata for a video"""

    video_id: str = Field(..., description="Unique identifier for the video")
    filename: str = Field(..., description="Original filename of the video")
    content_type: str = Field(..., description="MIME type of the video")
    size_bytes: int = Field(..., description="Size of the video in bytes")
    uploaded_at: datetime = Field(
        default_factory=datetime.now, description="Upload timestamp"
    )
    duration_seconds: Optional[float] = Field(
        None, description="Duration of video in seconds"
    )


class UploadResponse(BaseModel):
    """Response after successful video upload"""

    video_id: str = Field(..., description="Unique identifier for the uploaded video")
    filename: str = Field(..., description="Original filename")
    size_bytes: int = Field(..., description="Size in bytes")
    uploaded_at: datetime = Field(..., description="Upload timestamp")
    playlist_url: str = Field(..., description="HLS playlist URL for streaming")
    duration_seconds: Optional[float] = Field(
        None, description="Video duration in seconds"
    )
    message: str = Field(default="Video uploaded and converted to HLS successfully")


class VideoInfo(BaseModel):
    """Information about a stored video"""

    video_id: str = Field(..., description="Unique identifier for the video")
    filename: str = Field(..., description="Original filename")
    content_type: str = Field(..., description="MIME type")
    size_bytes: int = Field(..., description="Size in bytes")
    uploaded_at: datetime = Field(..., description="Upload timestamp")
    duration_seconds: Optional[float] = Field(None, description="Duration in seconds")
    playlist_url: str = Field(..., description="HLS playlist URL for streaming")
    download_url: str = Field(..., description="URL to download the original video")


class VideoListResponse(BaseModel):
    """Response containing list of videos"""

    videos: list[VideoInfo] = Field(..., description="List of video metadata")
    count: int = Field(..., description="Total number of videos")


class ErrorResponse(BaseModel):
    """Error response"""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Additional error details")
