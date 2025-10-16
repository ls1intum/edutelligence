import logging

from fastapi import FastAPI

from nebula.health import router as health_router
from nebula.transcript.config import Config
from nebula.transcript.queue_worker import start_worker, stop_worker  # NEW
from nebula.transcript.routes.transcribe_routes import router as transcribe_router

logging.basicConfig(level=getattr(logging, Config.get_log_level()))
Config.ensure_dirs()

app = FastAPI(title="Nebula Transcription Service")


@app.on_event("startup")
async def _startup():
    start_worker()
    logging.info("🔧 FIFO worker started")


@app.on_event("shutdown")
async def _shutdown():
    await stop_worker()
    logging.info("🛑 FIFO worker stopped")


app.include_router(health_router, prefix="/transcribe", tags=["Transcription"])
app.include_router(transcribe_router, prefix="/transcribe", tags=["Transcription"])


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "FastAPI Nebula transcription service is running"}
