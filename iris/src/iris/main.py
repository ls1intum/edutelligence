import time
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, ORJSONResponse

import iris.sentry as sentry
from iris.common.logging_config import (
    generate_request_id,
    get_logger,
    set_request_id,
    setup_logging,
)
from iris.config import settings
from iris.tracing import init_langfuse, shutdown_langfuse
from iris.web.routers.health.health_endpoint import router as health_router
from iris.web.routers.ingestion_status import router as ingestion_status_router
from iris.web.routers.memiris import router as memiris_router
from iris.web.routers.pipelines import router as pipelines_router
from iris.web.routers.webhooks import router as webhooks_router

# Initialize logging first
setup_logging()

logger = get_logger(__name__)

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
    logger.info("Scheduler started")
    memory_sleep_task()
    yield

    shutdown_langfuse()
    scheduler.shutdown()
    logger.info("Scheduler stopped")


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
    logger.error("Validation error | path=%s | error=%s", request.url.path, exc_str)
    content = {"status_code": 10422, "message": exc_str, "data": None}
    return JSONResponse(
        content=content, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
    )


# Paths to exclude from request logging (health checks are too noisy)
EXCLUDED_LOG_PATHS = {"/api/v1/health", "/api/v1/health/"}


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """
    Middleware to log requests with correlation IDs.

    - Generates a unique request ID for each request
    - Logs request start (DEBUG) and completion (INFO)
    - Skips logging for health check endpoints
    - Tracks request duration
    """
    # Generate and set request ID
    request_id = generate_request_id()
    set_request_id(request_id)

    # Check if we should log this request
    path = request.url.path
    should_log = path not in EXCLUDED_LOG_PATHS

    start_time = time.perf_counter()

    if should_log:
        logger.debug("Request started | method=%s path=%s", request.method, path)

    try:
        response = await call_next(request)
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        if should_log:
            logger.error(
                "Request failed | method=%s path=%s | duration=%dms | error=%s",
                request.method,
                path,
                duration_ms,
                str(e),
            )
        raise

    duration_ms = (time.perf_counter() - start_time) * 1000

    if should_log:
        logger.info(
            "Request completed | method=%s path=%s status=%d | duration=%dms",
            request.method,
            path,
            response.status_code,
            duration_ms,
        )

    return response


app.include_router(health_router)
app.include_router(pipelines_router)
app.include_router(webhooks_router)
app.include_router(ingestion_status_router)
app.include_router(memiris_router)

# Initialize the LLM manager
# Import here to avoid circular imports
from iris.llm.llm_manager import LlmManager  # noqa: E402

LlmManager()
