import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nebula.common.config import Config
from nebula.health import router as health_router
from nebula.tracing import init_langfuse, shutdown_langfuse
from nebula.transcript.queue_worker import start_worker, stop_worker
from nebula.transcript.routes.transcribe_routes import router as transcribe_router
from nebula.transcript.transcriber_config import ensure_dirs

logging.basicConfig(level=getattr(logging, Config.LOG_LEVEL))
ensure_dirs()


@asynccontextmanager
async def lifespan(_app: FastAPI):  # pylint: disable=invalid-name,unused-argument
    init_langfuse()
    start_worker()
    logging.info("FIFO worker started")
    try:
        yield
    finally:
        await stop_worker()
        shutdown_langfuse()
        logging.info("FIFO worker stopped")


app = FastAPI(title="Nebula Transcription Service", lifespan=lifespan)


app.include_router(health_router, prefix="/transcribe", tags=["Transcription"])
app.include_router(transcribe_router, prefix="/transcribe", tags=["Transcription"])


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "FastAPI Nebula transcription service is running"}
