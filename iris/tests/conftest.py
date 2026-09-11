import os
from pathlib import Path

# Set APPLICATION_YML_PATH before any pipeline imports trigger Settings loading.
os.environ.setdefault(
    "APPLICATION_YML_PATH",
    str(Path(__file__).resolve().parent.parent / "application.example.yml"),
)

# Pre-load iris.domain so the iris.common.pyris_message <-> iris.domain import
# cycle always resolves in the correct order. Without this, a test module that
# imports a retrieval module (e.g. iris.retrieval.*) before any domain/pipeline
# module hits a partially-initialized import error when run in isolation.
import iris.domain  # noqa: E402,F401  pylint: disable=unused-import,wrong-import-position
