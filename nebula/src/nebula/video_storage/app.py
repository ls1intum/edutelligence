"""
FastAPI application for video storage service (Artemis-focused)
"""

import logging

from fastapi import FastAPI

from nebula.health import router as health_router
from nebula.video_storage.config import Config
from nebula.video_storage.routes.video_routes import router as video_router

# Set up logging and configuration
logging.basicConfig(level=getattr(logging, Config.get_log_level()))
Config.ensure_dirs()

# Initialize FastAPI app
app = FastAPI(
    title="Nebula Video Storage Service",
    description="Video upload and HLS streaming service for Artemis",
    version="1.0.0",
)

# Include routers
app.include_router(health_router, prefix="/video-storage", tags=["Health"])
app.include_router(video_router, prefix="/video-storage", tags=["Video Storage"])


# Root endpoint
@app.get("/", include_in_schema=False)
async def root():
    return {
        "message": "Nebula Video Storage Service for Artemis",
        "version": "1.0.0",
        "streaming_format": "HLS (HTTP Live Streaming)",
        "architecture": ("Artemis stores metadata, Nebula stores video files"),
        "endpoints": {
            "upload": (
                "POST /video-storage/upload - " "Upload video, returns playlist_url"
            ),
            "playlist": (
                "GET /video-storage/playlist/{video_id}/"
                "playlist.m3u8 - Get HLS playlist"
            ),
            "delete": ("DELETE /video-storage/delete/{video_id} - Delete video"),
            "health": "GET /video-storage/health - Health check",
        },
    }
