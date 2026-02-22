"""Whisper transcription model definitions.

These models are used exclusively by the video transcription pipeline
and are not part of the standard Iris chat/completion pipeline.
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
