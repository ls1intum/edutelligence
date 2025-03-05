from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from assessment_module_manager.logger import logger

description = """
This is the Athena API. You are interacting with the Assessment Module Manager, 
which is responsible for deciding which assessment modules to run when there are
new submissions or new feedback.

You would usually connect this API with an LMS of your choice to get suggestions
from any of the modules that are available. You can find a list of modules at
the [/modules](/modules) endpoint.
"""

app = FastAPI(
    title="Athena API",
    description=description,
    version="0.1.0"
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error("Validation error: %s \n Errors: %s\n Request body: %s", exc, exc.errors(), exc.body)
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )
