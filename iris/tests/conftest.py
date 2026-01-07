import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TEST_WEAVIATE_HOST = "localhost"
TEST_WEAVIATE_PORT = 8002
TEST_WEAVIATE_GRPC_PORT = 50052

# Set APPLICATION_YML_PATH before any pipeline imports trigger Settings loading.
os.environ.setdefault(
    "APPLICATION_YML_PATH",
    str(ROOT / "application.example.yml"),
)
os.environ.setdefault("LLM_CONFIG_PATH", str(ROOT / "llm_config.example.yml"))
