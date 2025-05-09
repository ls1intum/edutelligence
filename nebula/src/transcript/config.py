import yaml
from pathlib import Path


class Config:
    BASE_DIR = Path(__file__).resolve().parent
    VIDEO_STORAGE_PATH = BASE_DIR / "temp"
    WHISPER_MODEL = "base"
    LOG_LEVEL = "INFO"
    LLM_CONFIG_PATH = BASE_DIR / "llm_config.nebula.yml"
    API_KEYS = []

    @staticmethod
    def ensure_dirs() -> None:
        """Ensure required directories exist."""
        Config.VIDEO_STORAGE_PATH.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def load_local_config() -> None:
        """Load local.yml into Config.API_KEYS"""
        local_path = Config.BASE_DIR.parent / "application_local.nebula.yml"
        print(f"[Config] Loading from: {local_path}")
        if local_path.exists():
            with open(local_path, "r") as f:
                data = yaml.safe_load(f)
                Config.API_KEYS = [entry["token"] for entry in data.get("api_keys", [])]
        else:
            Config.API_KEYS = []


# Call it immediately on import
Config.load_local_config()
