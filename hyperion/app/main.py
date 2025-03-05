import tomllib
from pydantic import BaseModel
from fastapi import FastAPI, status
import gradio as gr

from app.settings import settings
from app.models import get_model


# Read project metadata from pyproject.toml
with open("pyproject.toml", "rb") as f:
    META = tomllib.load(f)

name = META["project"]["name"]
description = META["project"]["description"]
version = META["project"]["version"]
contact = META["project"]["authors"][0]

app = FastAPI(
    title=name[0].upper() + name[1:],
    description=description,
    version=version,
    contact=contact,
)


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
    return HealthCheck(status="OK", version=version)


io = gr.Interface(fn=run, inputs="textbox", outputs="textbox")
app = gr.mount_gradio_app(app, io, path="/playground", root_path="/playground")
