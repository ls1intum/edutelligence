from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.routes.messages import router as messages_router
from app.routes.health import router as health_router
from app.services.hazelcast_client import hazelcast_client
from app.routes.models import router as models_router

app = FastAPI(default_response_class=ORJSONResponse)


@app.on_event("shutdown")
async def shutdown():
    hazelcast_client.shutdown()


app.include_router(messages_router)
app.include_router(health_router)
app.include_router(models_router)
