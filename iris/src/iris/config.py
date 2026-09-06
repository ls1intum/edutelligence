import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, model_validator


class APIKeyConfig(BaseModel):
    token: str


class WeaviateSettings(BaseModel):
    host: str
    port: int
    grpc_port: int
    http_secure: bool = False
    grpc_secure: bool = False
    api_key: Optional[str] = None


class MemirisLlmConfiguration(BaseModel):
    """
    Configuration for the LLMs used by Memiris.
     - embeddings: List of embedding model identifiers (same for local and cloud).
     - learning_extractor: Model identifier(s) for the learning extractor.
        Can be a string or dict with 'local' and 'cloud' keys.
     - learning_deduplicator: Model identifier(s) for the learning deduplicator.
        Can be a string or dict with 'local' and 'cloud' keys.
     - memory_creator: Model identifier(s) for the memory creator.
        Can be a string or dict with 'local' and 'cloud' keys.
     - sleep_tool_llm: Model identifier(s) for the sleep tool LLM.
        Can be a string or dict with 'local' and 'cloud' keys.
     - sleep_json_llm: Model identifier(s) for the sleep JSON LLM.
        Can be a string or dict with 'local' and 'cloud' keys.
    """

    embeddings: list[str] = Field(default_factory=list)
    learning_extractor: str | dict[str, str] = Field()
    learning_deduplicator: str | dict[str, str] = Field()
    memory_creator: str | dict[str, str] = Field()
    sleep_tool_llm: str | dict[str, str] = Field()
    sleep_json_llm: str | dict[str, str] = Field()


class MemirisSettings(BaseModel):
    """
    Settings for Memiris configuration.
     - enabled: Whether Memiris is enabled or not.
     - sleep_enabled: Whether the sleep functionality of Memiris is enabled or not.
     - llm_configuration: The configuration for the LLMs used by Memiris. Required if Memiris is enabled.
    """

    enabled: bool = Field(default=True)
    sleep_enabled: bool = Field(default=True)
    llm_configuration: Optional[MemirisLlmConfiguration] = Field(default=None)

    @model_validator(mode="after")
    def validate_llm_configuration_when_enabled(self):
        """Validate that LLM configuration is provided when Memiris is enabled."""
        if self.enabled and not self.llm_configuration:
            raise ValueError(
                "Memiris llm_configuration is required when memiris.enabled=True"
            )
        return self


class LangfuseSettings(BaseModel):
    """Settings for LangFuse observability integration."""

    enabled: bool = Field(default=False)
    public_key: Optional[str] = Field(default=None)
    secret_key: Optional[str] = Field(default=None)
    host: str = Field(default="https://cloud.langfuse.com")

    @model_validator(mode="after")
    def validate_keys_when_enabled(self):
        """Validate that keys are provided when LangFuse is enabled."""
        if self.enabled and (not self.public_key or not self.secret_key):
            raise ValueError(
                "LangFuse public_key and secret_key are required when enabled=True"
            )
        return self


LlmRoleConfiguration = dict[
    str, dict[str, str] | str
]  # role -> {local/cloud -> model_id} or role -> model_id (for roles like embedding/reranker)
LlmVariantConfiguration = dict[str, LlmRoleConfiguration]  # variant_id -> role config


class TranscriptionSettings(BaseModel):
    """Settings for video transcription pipeline.

    Whisper API configuration (endpoint, key, deployment) is loaded from
    llm_config.yml, not here.  Add an entry with type 'azure_whisper' or
    'openai_whisper' to llm_config.yml and set whisper_model to its id.
    """

    enabled: bool = Field(default=False, description="Enable video transcription")
    temp_dir: str = Field(
        default="/tmp/iris-transcription",  # nosec B108
        description="Directory for temporary video/audio files",
    )
    chunk_duration_seconds: int = Field(
        default=900, description="Audio chunk duration in seconds (default: 15 min)"
    )
    whisper_model: str = Field(
        default="whisper",
        description="Model ID to look up in llm_config.yml",
    )
    whisper_max_workers: int = Field(
        default=2,
        description="Max parallel Whisper API requests per transcription job",
    )
    whisper_request_timeout_seconds: int = Field(
        default=300,
        description="Timeout in seconds for a single Whisper API request",
    )
    whisper_max_retries: int = Field(
        default=6,
        description="Max retry attempts per chunk on transient failures",
    )
    download_timeout_seconds: int = Field(
        default=3600,
        description="Timeout for video download via FFmpeg (default: 1 hour)",
    )
    extract_audio_timeout_seconds: int = Field(
        default=600,
        description="Timeout for audio extraction via FFmpeg (default: 10 min)",
    )
    youtube_max_duration_seconds: int = Field(
        default=21600,
        description="Max YouTube video duration in seconds (default: 6 hours). "
        "Videos longer than this are rejected with YOUTUBE_TOO_LONG.",
    )
    youtube_download_timeout_seconds: int = Field(
        default=3600,
        description="Timeout for yt-dlp download of a YouTube video (default: 1 hour). "
        "Must be large enough to cover the slowest download up to "
        "``youtube_max_duration_seconds``; increase this if long videos start "
        "failing with YOUTUBE_DOWNLOAD_FAILED due to timeout.",
    )
    no_speech_filter_threshold: float = Field(
        default=0.8,
        description=(
            "Whisper no_speech_prob threshold (0.0-1.0). Segments above this "
            "are discarded. Use 0.8 for noisy lecture halls, 0.6 for studios, "
            "1.0 to disable."
        ),
    )


class Settings(BaseModel):
    """Settings represents application configuration settings loaded from a YAML file."""

    api_keys: list[APIKeyConfig]
    env_vars: dict[str, str]
    weaviate: WeaviateSettings
    memiris: MemirisSettings
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    local_llm_enabled: bool = Field(default=True)
    llm_configuration: dict[str, LlmVariantConfiguration] = Field(default_factory=dict)
    transcription: TranscriptionSettings = Field(default_factory=TranscriptionSettings)
    global_search_rerank_floor: float = Field(
        default=0.10,
        description="Junk floor for global-search candidates: the score below "
        "which a reranked candidate is treated as garbage rather than as a "
        "weak answer. Calibrated against the NEGATIVE distribution, not the "
        "relevant one, because junk scores in a tight, stable band while "
        "relevance does not: across three runs on Qwen3-Reranker-8B, "
        "deliberately irrelevant candidates peaked at 0.065 while genuinely "
        "relevant lecture content sat at 0.24-0.62 and entity records "
        "(30-char titles) at 0.08-0.35. 0.10 sits 0.035 above the junk "
        "ceiling, 3.5x the reranker's measured run-to-run noise (+/-0.01), so "
        "borderline candidates are not decided by serving nondeterminism. It "
        "does clip the very bottom of the entity band: 0.08 would keep ~28 "
        "percent more entity candidates but leaves only 1.5x noise margin over "
        "junk. Revisit once entity search_text enrichment lifts that band. "
        "Volume is capped by `limit`, "
        "not by this value. A query whose candidates ALL fall below the floor "
        "returns no sources - the honest empty state, skipping the answer LLM. "
        "Set to 0.0 for log-only calibration.",
    )
    global_search_pointer_floor: float = Field(
        default=0.08,
        description="Lower admission bound for ENTITY POINTER candidates when "
        "nothing clears the main rerank floor. Derived from the same "
        "calibration as the floor: junk peaks at 0.065 and reranker noise is "
        "about +/-0.01, so 0.08 stays above the junk ceiling while admitting "
        "the borderline band the 0.10 floor deliberately clips (a topical "
        "lecture-unit card for a concept question sits at 0.08-0.10). Applies "
        "ONLY to entity cards and ONLY when the floored pool is empty — the "
        "honest reading of that state is 'no content answers this, but this "
        "material seems related', which the answer stage phrases as "
        "navigation. Must stay below global_search_rerank_floor.",
    )
    global_search_expand_units: bool = Field(
        default=True,
        description="Graph expansion for the ANSWER path: once a candidate "
        "survives the floor, fetch the rest of its lecture unit's material by "
        "structural join instead of making each sibling win its own ranking "
        "slot. Measured on the scattered-scenario harness: at least one "
        "relevant item is returned for 93 percent of queries, but every "
        "collection holding relevant material is represented for only 16 "
        "percent - the anchor is found, the rest loses the ranking contest. A "
        "join has 100 percent recall by construction, which turns a "
        "multi-collection conjunction into the single question of whether the "
        "anchor was right. Not applied to the instant results list, which is a "
        "ranked list by contract and has a ~400ms budget.",
    )
    global_search_expand_max_units: int = Field(
        default=4,
        description="How many distinct lecture units to expand, taken in rank "
        "order. Bounds both the fetch and the context handed to the answer LLM.",
    )
    global_search_expand_per_unit: int = Field(
        default=3,
        description="Extra passages pulled per expanded unit. Siblings are "
        "appended after the ranked anchors and inherit their anchor's score, so "
        "ordering is unchanged for everything that earned its place.",
    )
    global_search_expand_fetch_limit: int = Field(
        default=200,
        description="Per-collection cap on the expansion join. Deliberately "
        "larger than max_units * per_unit: numeric unit ids collide across "
        "Artemis instances sharing one Weaviate, so over-fetching and filtering "
        "on the full (base_url, course_id, lecture_unit_id) key is what keeps "
        "another instance's unit out of the results.",
    )
    global_search_rerank_results_list: bool = Field(
        default=True,
        description="Also rerank the instant results list (SKIP_AI / REST "
        "search). The AI answer path is always reranked. The list adds the "
        "reranker's latency to an otherwise ~400ms response — disable if list "
        "latency matters more than mid-list ranking quality.",
    )
    global_search_rerank_list_timeout_s: float = Field(
        default=2.0,
        description="Rerank wall-clock budget for the instant results list, in "
        "seconds. A slow rerank call degrades to the fused ordering at this "
        "budget instead of pinning the list at the answer path's longer "
        "timeout (which can exceed the caller's own timeout and surface as a "
        "failed search in the UI).",
    )

    @classmethod
    def get_settings(cls):
        """Get the settings from the configuration file."""
        file_path_env = os.environ.get("APPLICATION_YML_PATH")
        if not file_path_env:
            raise EnvironmentError(
                "APPLICATION_YML_PATH environment variable is not set."
            )

        file_path = Path(file_path_env)
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                settings_file = yaml.safe_load(file)
            return cls.model_validate(settings_file)
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Configuration file not found at {file_path}."
            ) from e
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Error parsing YAML file at {file_path}.") from e

    def set_env_vars(self):
        """Set environment variables from the settings."""
        for key, value in self.env_vars.items():
            os.environ[key] = value


settings = Settings.get_settings()
