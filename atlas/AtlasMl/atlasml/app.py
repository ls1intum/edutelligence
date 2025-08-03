import logging
import os
import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

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


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Log request
        logger.info(f"🔄 {request.method} {request.url.path}")
        
        # Read request body for POST requests
        if request.method == "POST":
            body = await request.body()
            if body:
                try:
                    body_str = body.decode('utf-8')
                    # Try to parse as JSON for better formatting
                    try:
                        body_json = json.loads(body_str)
                        logger.info(f"📥 Request body: {json.dumps(body_json, indent=2)}")
                    except:
                        logger.info(f"📥 Request body: {body_str}")
                except:
                    logger.info(f"📥 Request body: <binary data>")
            
            # Recreate request with body for the actual handler
            async def receive():
                return {"type": "http.request", "body": body}
            
            request._receive = receive
        
        response = await call_next(request)
        
        # Log response
        process_time = time.time() - start_time
        logger.info(f"📤 Response: {response.status_code} (took {process_time:.3f}s)")
        
        return response


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

# Add validation error handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"❌ Validation error for {request.method} {request.url.path}")
    logger.error(f"❌ Validation details: {exc.errors()}")
    logger.error(f"❌ Request body was: {await request.body()}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": str(await request.body())}
    )

# Add logging middleware
app.add_middleware(RequestLoggingMiddleware)

app.include_router(health_router)
app.include_router(competency_router)
