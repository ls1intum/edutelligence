"""Whisper transcription model definitions.

These models are data classes that hold API configuration only.
The actual HTTP calls are made by WhisperClient in the transcription
pipeline utilities — these classes just store the endpoint, key,
and deployment info so WhisperClient can build the correct request.
"""

from typing import Literal

from pydantic import Field

from ...llm.external.model import LanguageModel


class WhisperModel(LanguageModel):
    """Base class for Whisper transcription models."""

    api_key: str
    name: str = Field(default="Whisper")
    description: str = Field(default="Whisper transcription model")


class AzureWhisperModel(WhisperModel):
    """Azure OpenAI Whisper transcription model."""

    type: Literal["azure_whisper"]
    endpoint: str
    api_version: str
    azure_deployment: str = Field(default="whisper")


class OpenAIWhisperModel(WhisperModel):
    """OpenAI Whisper transcription model."""

    type: Literal["openai_whisper"]
