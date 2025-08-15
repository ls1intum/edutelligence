import logging

from fastapi import FastAPI

from nebula.faq.routes.faq_routes import router as faq_router
from nebula.health import router as health_router
from nebula.transcript.config import Config

# Set up logging and configuration
logging.basicConfig(level=getattr(logging, Config.get_log_level()))
Config.ensure_dirs()

# Initialize FastAPI app
app = FastAPI(title="Nebula FAQ Service")

# Include routers
app.include_router(health_router, prefix="/faq", tags=["FAQ"])
app.include_router(faq_router, prefix="/faq", tags=["FAQ"])


# Root endpoint
@app.get("/", include_in_schema=False)
async def root():
    return {"message": "FastAPI Nebula Faq service is running"}
