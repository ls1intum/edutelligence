from fastapi import FastAPI
import os 

from atlasml.routers import health_router

ENV = os.getenv("ENV", "dev")

app = FastAPI(title="AtlasML API")

app.include_router(health_router)
