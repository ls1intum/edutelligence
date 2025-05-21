import logging
import os

import yaml
from fastapi import FastAPI

from gateway.routes import transcribe
from gateway.security import AuthMiddleware, add_security_schema_to_app

# ─────────────────────────────
# ✅ Logging Setup
# ─────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("nebula.gateway")

# ─────────────────────────────
# 🔐 Load API Key from Config
# ─────────────────────────────
config_path = os.environ.get("APPLICATION_YML_PATH")
if not config_path or not os.path.exists(config_path):
    raise RuntimeError("Missing or invalid APPLICATION_YML_PATH environment variable.")

with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

API_KEY = config["api_keys"][0]["token"]
HEADER_NAME = "Authorization"
EXCLUDE_PATHS = ["/transcribe"]

# ─────────────────────────────
# 🚀 Initialize FastAPI App
# ─────────────────────────────
app = FastAPI(title="Nebula Gateway")
logger.info("✅ Gateway initialized with secured routing.")

# Add Auth middleware
app.add_middleware(
    AuthMiddleware,
    api_key=API_KEY,
    header_name=HEADER_NAME,
    exclude_paths=EXCLUDE_PATHS,
)

# Add OpenAPI schema with auth header
add_security_schema_to_app(app, header_name=HEADER_NAME, exclude_paths=EXCLUDE_PATHS)

# Add routes
app.include_router(transcribe.router, prefix="/transcribe", tags=["Transcription"])
