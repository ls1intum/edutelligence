import gradio as gr
from fastapi import FastAPI, status

from shared.security import AuthMiddleware, add_security_schema_to_app
from shared.health import create_health_router

from app.models import get_model
from app.settings import settings
from app.project_meta import project_meta

app = FastAPI(
    title=project_meta.title,
    description=project_meta.description,
    version=project_meta.version,
    contact=project_meta.contact,
)

exclude_paths = ["/playground"]
app.add_middleware(
    AuthMiddleware,
    api_key=settings.API_KEY,
    header_name=settings.API_KEY_HEADER,
    exclude_paths=exclude_paths,
)
add_security_schema_to_app(
    app, header_name=settings.API_KEY_HEADER, exclude_paths=exclude_paths
)

# Add routers
app.include_router(create_health_router(app.version))


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
