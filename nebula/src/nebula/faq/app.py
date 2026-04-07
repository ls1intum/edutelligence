import logging

from fastapi import FastAPI

from nebula.common.config import Config
from nebula.faq.routes.faq_routes import router as faq_router
from nebula.health import router as health_router

# Set up logging and configuration
logging.basicConfig(level=getattr(logging, Config.LOG_LEVEL))

# Initialize FastAPI app
app = FastAPI(title="Nebula FAQ Service")

# Include routers
app.include_router(health_router, prefix="/faq", tags=["FAQ"])
app.include_router(faq_router, prefix="/faq", tags=["FAQ"])


# Root endpoint
@app.get("/", include_in_schema=False)
async def root():
    return {"message": "FastAPI Nebula Faq service is running"}
