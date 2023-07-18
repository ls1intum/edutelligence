from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.routes.messages import router as messages_router
from app.routes.models import router as models_router

app = FastAPI(default_response_class=ORJSONResponse)

app.include_router(messages_router)
app.include_router(models_router)
