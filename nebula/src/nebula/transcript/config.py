import os
import yaml
from pathlib import Path


class Config:
    BASE_DIR = Path(__file__).resolve().parent
    VIDEO_STORAGE_PATH = BASE_DIR / "temp"
    WHISPER_MODEL = "base"
    LOG_LEVEL = "INFO"
    API_KEYS = []

    # Load paths from env or fall back to root-level config
    APPLICATION_YML_PATH = Path(
        os.getenv(
            "APPLICATION_YML_PATH", BASE_DIR.parent / "application_local.nebula.yml"
        )
    )
    LLM_CONFIG_PATH = Path(
        os.getenv("LLM_CONFIG_PATH", BASE_DIR.parent / "llm_config.nebula.yml")
    )

    @staticmethod
    def ensure_dirs() -> None:
        Config.VIDEO_STORAGE_PATH.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def load_local_config() -> None:
        print(f"[Config] Loading from: {Config.APPLICATION_YML_PATH}")
        if Config.APPLICATION_YML_PATH.exists():
            with open(Config.APPLICATION_YML_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                print(f"[DEBUG] Raw YAML data: {data}")
                Config.API_KEYS = [entry["token"] for entry in data.get("api_keys", [])]
        else:
            Config.API_KEYS = []


# Run loader on import
Config.load_local_config()
