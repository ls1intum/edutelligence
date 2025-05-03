from pathlib import Path

class Config:
    BASE_DIR = Path(__file__).resolve().parent

    VIDEO_STORAGE_PATH = BASE_DIR / "temp"
    WHISPER_MODEL = "base"
    LOG_LEVEL = "INFO"
    LLM_CONFIG_PATH = BASE_DIR / "llm_config.nebula.yml"

    @staticmethod
    def ensure_dirs():
        Config.VIDEO_STORAGE_PATH.mkdir(parents=True, exist_ok=True)
