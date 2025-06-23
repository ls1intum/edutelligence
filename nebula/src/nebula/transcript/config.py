import logging
import os
from pathlib import Path
from typing import List

import yaml

logger = logging.getLogger(__name__)


class Config:
    """Holds configuration settings loaded from the environment or YAML files."""

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
                logger.debug("Raw YAML data: %s", data)
                cls._api_keys = [entry["token"] for entry in data.get("api_keys", [])]
                cls._log_level = data.get("log_level", "INFO")
        else:
            logger.info("No config file found, skipping")
        cls._loaded = True

    @classmethod
    def get_api_keys(cls) -> List[str]:
        cls.load()
        return cls._api_keys

    @classmethod
    def get_log_level(cls) -> str:
        cls.load()
        return cls._log_level

    @classmethod
    def ensure_dirs(cls) -> None:
        cls.VIDEO_STORAGE_PATH.mkdir(parents=True, exist_ok=True)
