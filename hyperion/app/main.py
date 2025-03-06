import gradio as gr
from fastapi import FastAPI, status
from fastapi.openapi.utils import get_openapi

from app.security import AuthMiddleware, add_security_schema_to_openapi
from app.models import get_model
from app.settings import settings
from app.project_meta import project_meta
from app.health import router as health_router

app = FastAPI(
    title=project_meta.title,
    description=project_meta.description,
    version=project_meta.version,
    contact=project_meta.contact,
)

app.add_middleware(AuthMiddleware)


# Custom OpenAPI schema
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema = add_security_schema_to_openapi(openapi_schema)
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

# Include Routers
app.include_router(health_router)

ChatModel = get_model(settings.MODEL_NAME)
model = ChatModel()


@app.get(
    "/run",
    status_code=status.HTTP_200_OK,
    response_model=str,
)
def run(query: str):
    return model.invoke(query).content


io = gr.Interface(fn=run, inputs="textbox", outputs="textbox")
playground_auth = (
    (settings.PLAYGROUND_USERNAME, settings.PLAYGROUND_PASSWORD)
    if settings.PLAYGROUND_PASSWORD
    else None
)
app = gr.mount_gradio_app(
    app, io, path="/playground", root_path="/playground", auth=playground_auth
)
