from fastapi.responses import ORJSONResponse
from fastapi import FastAPI

from app.config import settings
from app.web.routers.health import router as health_router
from app.web.routers.pipelines import router as pipelines_router
from app.web.routers.webhooks import router as webhooks_router

settings.set_env_vars()

app = FastAPI(default_response_class=ORJSONResponse)

app.include_router(health_router)
app.include_router(pipelines_router)
app.include_router(webhooks_router)
