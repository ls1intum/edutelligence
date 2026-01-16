# pylint: disable=wrong-import-position
"""Root conftest for all Nebula tests.

Sets required environment variables before any module imports to prevent
RuntimeError from missing env vars at import time.
"""
import os
import tempfile

# Set required env vars BEFORE any nebula module imports
os.environ.setdefault("LLM_CONFIG_PATH", "/tmp/test_llm_config.yml")
os.environ.setdefault("NEBULA_TEMP_DIR", tempfile.gettempdir())
