from typing import Optional
from pydantic import Field, SecretStr
from langchain_core.utils.utils import secret_from_env
from langchain_openai import ChatOpenAI

from app.settings import settings


class ChatOpenWebUI(ChatOpenAI):
    openai_api_key: Optional[SecretStr] = Field(
        alias="api_key",
        default_factory=secret_from_env(settings.OPENWEBUI_API_KEY, default=None),
    )

    @property
    def lc_secrets(self) -> dict[str, str]:
        return {"openai_api_key": "OPENWEBUI_API_KEY"}

    def __init__(self, openai_api_key: Optional[str] = None, **kwargs):
        openai_api_key = openai_api_key or settings.OPENWEBUI_API_KEY
        base_url = settings.OPENWEBUI_BASE_URL
        if base_url:
            if not base_url.endswith('/'):
                base_url += '/'
            if not base_url.endswith('v1/'):
                base_url += 'v1/'
        
        super().__init__(
            base_url=base_url or "http://localhost:8080/ollama/v1/",
            openai_api_key=openai_api_key,
            **kwargs
        )
