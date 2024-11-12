from abc import ABC

from langchain_community.chat_models import FakeListChatModel
from pydantic import BaseModel


class FakeLLM(BaseModel, ABC):

    def get_model(self) -> FakeListChatModel:
        return FakeListChatModel(responses=["mock"])