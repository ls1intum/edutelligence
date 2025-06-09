import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

from atlasml.clients.weaviate import weaviate_client
from atlasml.routers.competency import router as competency_router
from atlasml.routers.health import router as health_router
from atlasml.tasks.scheduler import periodic_task

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)
ENV = os.getenv("ENV", "dev")
scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app):
    logger.info("🚀 Starting AtlasML API...")
    logger.info(
        f"🔌 Weaviate client status: {'Connected' if weaviate_client.is_alive() else 'Disconnected'}"
    )

    """Lifespan context manager for scheduler."""
    if not scheduler.running:
        scheduler.start()

        # TODO: configure this for the future
        scheduler.add_job(
            periodic_task,
            trigger=IntervalTrigger(seconds=60),
            id="periodic_task",
            replace_existing=True,
        )
        logger.info("Scheduler started")
    else:
        logger.info("Scheduler is already running")

    yield

    logger.info("Shutting down AtlasML API...")
    weaviate_client.close()
    logger.info("Weaviate client closed.")


app = FastAPI(title="AtlasML API", lifespan=lifespan)
app.include_router(health_router)
app.include_router(competency_router)
