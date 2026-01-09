import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, ORJSONResponse
from starlette.background import BackgroundTask
from starlette.responses import Response

import iris.sentry as sentry
from iris.config import settings
from iris.tracing import init_langfuse, shutdown_langfuse
from iris.web.routers.health.health_endpoint import router as health_router
from iris.web.routers.ingestion_status import router as ingestion_status_router
from iris.web.routers.memiris import router as memiris_router
from iris.web.routers.pipelines import router as pipelines_router
from iris.web.routers.webhooks import router as webhooks_router

settings.set_env_vars()

sentry.init()
init_langfuse()

scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Import here to avoid circular imports
    from iris.common.memiris_setup import (  # noqa: E402 pylint: disable=import-outside-toplevel
        memory_sleep_task,
    )

    scheduler.add_job(memory_sleep_task, trigger="cron", hour=1, minute=0)
    scheduler.start()
    logging.info("Memory Sleep scheduler started (lifespan style)")

    yield

    shutdown_langfuse()
    scheduler.shutdown()
    logging.info("Memory Sleep Scheduler stopped gracefully")


app = FastAPI(default_response_class=ORJSONResponse, lifespan=lifespan)


def custom_openapi():
    if not app.openapi_schema:
        openapi_schema = FastAPI.openapi(app)
        # Add security scheme
        openapi_schema["components"]["securitySchemes"] = {
            "bearerAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "Authorization",
            }
        }
        # Apply the security globally
        for path in openapi_schema["paths"].values():
            for method in path.values():
                method.setdefault("security", []).append({"bearerAuth": []})
        app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[assignment]


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    exc_str = f"{exc}".replace("\n", " ").replace("   ", " ")
    logging.error("%s: %s", request, exc_str)
    content = {"status_code": 10422, "message": exc_str, "data": None}
    return JSONResponse(
        content=content, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
    )


def log_info(req_body, res_body):
    logging.info(req_body)
    logging.info(res_body)


@app.middleware("http")
async def some_middleware(request: Request, call_next):
    req_body = await request.body()
    response = await call_next(request)

    res_body = b""
    async for chunk in response.body_iterator:
        res_body += chunk

    task = BackgroundTask(log_info, req_body, res_body)
    return Response(
        content=res_body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
        background=task,
    )


app.include_router(health_router)
app.include_router(pipelines_router)
app.include_router(webhooks_router)
app.include_router(ingestion_status_router)
app.include_router(memiris_router)

# Initialize the LLM manager
# Import here to avoid circular imports
from iris.llm.llm_manager import LlmManager  # noqa: E402

LlmManager()
