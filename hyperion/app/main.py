import gradio as gr
from fastapi import FastAPI, status
from langfuse.callback import CallbackHandler

from shared.security import AuthMiddleware, add_security_schema_to_app
from shared.health import create_health_router

from app.models import get_model
from app.logger import logger
from app.settings import settings
from app.project_meta import project_meta
from app.consistency_checker.routes import router as consistency_checker_router

app = FastAPI(
    title=project_meta.title,
    description=project_meta.description,
    version=project_meta.version,
    contact=project_meta.contact,
)

# Add security schema to the app, can be disabled for development
if not settings.DISABLE_AUTH:
    logger.warning(
        "API authentication is disabled. This is not recommended for production."
    )

    exclude_paths = ["/playground"]
    app.add_middleware(
        AuthMiddleware,
        api_key=settings.API_KEY,
        header_name="X-API-Key",
        exclude_paths=exclude_paths,
    )
    add_security_schema_to_app(
        app, header_name="X-API-Key", exclude_paths=exclude_paths
    )

# Add routers
app.include_router(create_health_router(app.version))
app.include_router(consistency_checker_router)

callbacks = []
if settings.langfuse_enabled:
    langfuse_handler = CallbackHandler()
    langfuse_handler.auth_check()
    callbacks.append(langfuse_handler)

ChatModel = get_model(settings.MODEL_NAME)
model = ChatModel().with_config(callbacks=callbacks)


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
