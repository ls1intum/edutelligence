import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from atlasml.clients.weaviate import get_weaviate_client
from atlasml.routers.competency import router as competency_router
from atlasml.routers.health import router as health_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)
ENV = os.getenv("ENV", "dev")


@asynccontextmanager
async def lifespan(app):
    logger.info("🚀 Starting AtlasML API...")
    logger.info(
        f"🔌 Weaviate client status: {'Connected' if get_weaviate_client().is_alive() else 'Disconnected'}"
    )
    logger.info(f"🌐 API running on port {os.getenv('PORT', '8000')}")
    yield

    logger.info("Shutting down AtlasML API...")
    get_weaviate_client().close()
    logger.info("Weaviate client closed.")


app = FastAPI(title="AtlasML API", lifespan=lifespan)
app.include_router(health_router)
app.include_router(competency_router)
