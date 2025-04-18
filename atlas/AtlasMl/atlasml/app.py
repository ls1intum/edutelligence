from fastapi import FastAPI
import os 

from atlasml.clients.weaviate import weaviate_client
from atlasml.routers import health_router

ENV = os.getenv("ENV", "dev")

app = FastAPI(title="AtlasML API")

app.include_router(health_router)

@app.on_event("startup")
def startup_event():
    """Startup event for the application."""
    print("🚀 Starting AtlasML API...")
    print(f"🔌 Weaviate client status: {'Connected' if weaviate_client.is_alive() else 'Disconnected'}")

@app.on_event("shutdown")
def shutdown_event():
    """Shutdown event for the application."""
    print("👋 Shutting down AtlasML API...")
    weaviate_client.close()
    print("🔌 Weaviate client closed.")
