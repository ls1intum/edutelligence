import logging

from fastapi import FastAPI

from nebula.health import router as health_router
from nebula.transcript.config import Config
from nebula.transcript.routes.transcribe_routes import router as transcribe_router

# Set up logging and configuration
logging.basicConfig(level=getattr(logging, Config.get_log_level()))
Config.ensure_dirs()

# Initialize FastAPI app
app = FastAPI(title="Nebula Transcription Service")

# Include routers
app.include_router(health_router, prefix="/transcribe", tags=["Transcription"])
app.include_router(transcribe_router, prefix="/transcribe", tags=["Transcription"])


# Root endpoint
@app.get("/", include_in_schema=False)
async def root():
    return {"message": "FastAPI Nebula transcription service is running"}
