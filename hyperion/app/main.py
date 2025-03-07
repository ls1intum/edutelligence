import gradio as gr
from gradio.themes.utils import colors, sizes
from fastapi import FastAPI, status
from langfuse.callback import CallbackHandler
from langchain_core.messages import HumanMessage, AIMessage

from shared.security import AuthMiddleware, add_security_schema_to_app
from shared.health import create_health_router

from app.models import get_model
from app.logger import logger
from app.settings import settings
from app.project_meta import project_meta

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


def generate_chat_response(message, history):
    history_langchain_format = []
    if not history:
        history_langchain_format.append(
            AIMessage(
                content=(
                    "You are an AI assistant that provides information about TUM's courses, events, and FAQ. "
                    "You must respond politely, professionally, and with TUM branding in mind."
                )
            )
        )

    for msg in history:
        if msg["role"] == "user":
            history_langchain_format.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            history_langchain_format.append(AIMessage(content=msg["content"]))
    history_langchain_format.append(HumanMessage(content=message))
    response = model.invoke(history_langchain_format)
    return response.content

tum_primary = colors.Color(
    name="tum_primary",
    c50="#E8F4FD",   # lightest tint (approximation)
    c100="#C7E0FB",
    c200="#A5CCF8",
    c300="#82B8F5",
    c400="#60A4F3",
    c500="#0065BD",  # official TUM blue
    c600="#0058AA",  # a bit darker
    c700="#004C97",
    c800="#004084",
    c900="#003471",
    c950="#00285E"
)

theme = gr.themes.Base(
    primary_hue=tum_primary,
    font="Arial",
    radius_size=sizes.radius_none
)

def like(evt: gr.LikeData):
    print("User liked the response")
    print(evt.index, evt.liked, evt.value)

hello_world = gr.Interface(fn=run, inputs="textbox", outputs="textbox")
chat = gr.ChatInterface(
    generate_chat_response, 
    type="messages",
    flagging_mode="manual",
    flagging_options=["Like", "Dislike"],
)
playground = gr.TabbedInterface(
    [hello_world, chat],
    ["Hello World", "Chat"],
    theme=theme,
    css="""
.submit-button {
    color: white !important;
    background-color: #3070b3 !important;
    border-color: #3070b3 !important; 
    border-radius: 0px; 
    border-width: 1px !important; 
    border-style: solid !important;
} 
.submit-button:hover {
    color: #3070b3 !important;
    background-color: white !important;
}
"""
)

playground_auth = (
    (settings.PLAYGROUND_USERNAME, settings.PLAYGROUND_PASSWORD)
    if settings.PLAYGROUND_PASSWORD
    else None
)
app = gr.mount_gradio_app(
    app, playground, path="/playground", root_path="/playground", auth=playground_auth
)
