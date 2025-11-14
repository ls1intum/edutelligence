import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class Config:
    """Central configuration loader for Nebula."""

    _loaded = False
    _log_level: str = "INFO"

    BASE_DIR = Path(__file__).resolve().parent.parent.parent

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
                cls._log_level = data.get("log_level", "INFO")
        else:
            logger.info("No application config file found, skipping")

        cls._loaded = True

    @classmethod
    def get_log_level(cls) -> str:
        cls.load()
        return cls._log_level
