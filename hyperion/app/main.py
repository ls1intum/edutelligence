import gradio as gr
from pydantic import BaseModel
from fastapi import FastAPI, status

from app.security import AuthMiddleware, get_openapi_schema_with_security_schema
from app.models import get_model
from app.settings import settings
from app.project_meta import project_meta

app = FastAPI(
    title=project_meta.title,
    description=project_meta.description,
    version=project_meta.version,
    contact=project_meta.contact,
)
app.add_middleware(AuthMiddleware)
app.openapi_schema = get_openapi_schema_with_security_schema(app)


@app.get(
    "/run",
    status_code=status.HTTP_200_OK,
    response_model=str,
)
def run(query: str):
    ChatModel = get_model(settings.MODEL_NAME)
    model = ChatModel()
    return model.invoke(query).content


class HealthCheck(BaseModel):
    """Response model to validate and return when performing a health check."""

    status: str
    version: str


@app.get(
    "/health",
    tags=["healthcheck"],
    summary="Perform a Health Check",
    response_description="Return HTTP Status Code 200 (OK)",
    status_code=status.HTTP_200_OK,
    response_model=HealthCheck,
)
def get_health() -> HealthCheck:
    """
    ## Perform a Health Check
    Endpoint to perform a healthcheck on. This endpoint can primarily be used Docker
    to ensure a robust container orchestration and management is in place. Other
    services which rely on proper functioning of the API service will not deploy if this
    endpoint returns any other HTTP status code except 200 (OK).
    Returns:
        HealthCheck: Returns a JSON response with the health status
    """
    return HealthCheck(status="OK", version=project_meta.version)


io = gr.Interface(fn=run, inputs="textbox", outputs="textbox")
playground_auth = (
    (settings.PLAYGROUND_USERNAME, settings.PLAYGROUND_PASSWORD)
    if settings.PLAYGROUND_PASSWORD
    else None
)
app = gr.mount_gradio_app(
    app, io, path="/playground", root_path="/playground", auth=playground_auth
)
