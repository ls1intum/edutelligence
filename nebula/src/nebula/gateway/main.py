import logging
import os
import threading
from contextlib import asynccontextmanager

import yaml
from fastapi import FastAPI

from nebula.gateway import grpc_server  # ⬅️ dein gRPC-Server
from nebula.gateway.routes import transcribe
from nebula.gateway.security import AuthMiddleware, add_security_schema_to_app

logger = logging.getLogger("nebula.gateway")
logging.basicConfig(level=logging.INFO)

# Config laden
config_path = os.environ.get("APPLICATION_YML_PATH", "application_local.nebula.yml")
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

API_KEY = config["api_keys"][0]["token"]
HEADER_NAME = "Authorization"
EXCLUDE_PATHS = ["/transcribe"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Lifespan startup starting...")
    yield
    logger.info("🛑 Lifespan shutting down.")
    grpc_server.stop()


# FastAPI initialisieren
app = FastAPI(title="Nebula Gateway", lifespan=lifespan)


app.add_middleware(
    AuthMiddleware,
    api_key=API_KEY,
    header_name=HEADER_NAME,
    exclude_paths=EXCLUDE_PATHS,
)
add_security_schema_to_app(app, header_name=HEADER_NAME, exclude_paths=EXCLUDE_PATHS)

app.include_router(transcribe.router, prefix="/transcribe", tags=["Transcription"])
