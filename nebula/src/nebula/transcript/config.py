import logging
import os
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger(__name__)


class Config:
    """Central configuration loader for Nebula."""

    _loaded = False
    _api_keys: List[str] = []
    _log_level: str = "INFO"

    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    VIDEO_STORAGE_PATH = BASE_DIR / "temp"
    WHISPER_MODEL = "base"

    APPLICATION_YML_PATH = Path(
        os.getenv(
            "APPLICATION_YML_PATH", BASE_DIR.parent / "application_local.nebula.yml"
        )
    )
    LLM_CONFIG_PATH = Path(
        os.getenv("LLM_CONFIG_PATH", BASE_DIR.parent / "llm_config.nebula.yml")
    )

    @classmethod
    def load(cls) -> None:
        if cls._loaded:
            return

        logger.info("Loading config from: %s", cls.APPLICATION_YML_PATH)
        if cls.APPLICATION_YML_PATH.exists():
            with open(cls.APPLICATION_YML_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                cls._api_keys = [entry["token"] for entry in data.get("api_keys", [])]
                cls._log_level = data.get("log_level", "INFO")
        else:
            logger.info("No application_local config file found, skipping")

        cls._loaded = True

    @classmethod
    def _load_llm_config(cls) -> List[dict]:
        if not cls.LLM_CONFIG_PATH.exists():
            raise FileNotFoundError(f"LLM config not found at {cls.LLM_CONFIG_PATH}")
        with open(cls.LLM_CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    @classmethod
    def _find_llm_id(cls, types: List[str], capability: Optional[str] = None) -> str:
        config_list = cls._load_llm_config()
        for entry in config_list:
            if entry.get("type") in types:
                if capability:
                    capabilities = entry.get("capabilities", {})
                    if isinstance(capabilities, dict):
                        if not capabilities.get(capability):
                            continue
                    elif isinstance(capabilities, list):
                        if capability not in capabilities:
                            continue
                    else:
                        continue
                return entry["id"]
        raise ValueError(
            f"No LLM found for types {types} with capability '{capability}'"
        )

    @classmethod
    def get_api_keys(cls) -> List[str]:
        cls.load()
        return cls._api_keys

    @classmethod
    def get_log_level(cls) -> str:
        cls.load()
        return cls._log_level

    @classmethod
    def get_whisper_llm_id(cls) -> str:
        # Looks for either Azure or OpenAI Whisper configs
        return cls._find_llm_id(types=["azure_whisper", "openai_whisper"])

    @classmethod
    def get_gpt_vision_llm_id(cls) -> str:
        # Must have image recognition = true
        return cls._find_llm_id(
            types=["azure_chat", "openai"], capability="image_recognition"
        )

    @classmethod
    def ensure_dirs(cls) -> None:
        cls.VIDEO_STORAGE_PATH.mkdir(parents=True, exist_ok=True)
