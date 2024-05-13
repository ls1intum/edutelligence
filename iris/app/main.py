from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from fastapi import FastAPI

from app.web.routers.health import router as health_router
from app.web.routers.pipelines import router as pipelines_router
from app.web.routers.webhooks import router as webhooks_router

import logging
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI(default_response_class=ORJSONResponse)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    exc_str = f'{exc}'.replace('\n', ' ').replace('   ', ' ')
    logging.error(f"{request}: {exc_str}")
    content = {'status_code': 10422, 'message': exc_str, 'data': None}
    return JSONResponse(content=content, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

app.include_router(health_router)
app.include_router(pipelines_router)
app.include_router(webhooks_router)
