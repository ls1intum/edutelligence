import asyncio
import logging
import os
import yaml
from fastapi import FastAPI

from contextlib import asynccontextmanager

from nebula.gateway.routes import transcribe
from nebula.gateway.security import AuthMiddleware, add_security_schema_to_app
from nebula.gateway import grpc_server  # ⬅️ dein gRPC-Server

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
    # gRPC-Server als Hintergrund-Task starten
    grpc_task = asyncio.create_task(asyncio.to_thread(grpc_server.serve()))
    yield
    # Hier könnte man bei Bedarf den gRPC-Server ordentlich herunterfahren
    logger.info("🛑 Stopping gRPC server...")
    grpc_server.stop()
    grpc_task.cancel()

# FastAPI initialisieren
app = FastAPI(title="Nebula Gateway", lifespan=lifespan)


app.add_middleware(AuthMiddleware, api_key=API_KEY, header_name=HEADER_NAME, exclude_paths=EXCLUDE_PATHS)
add_security_schema_to_app(app, header_name=HEADER_NAME, exclude_paths=EXCLUDE_PATHS)

app.include_router(transcribe.router, prefix="/transcribe", tags=["Transcription"])
logging.info("Started gateway service")