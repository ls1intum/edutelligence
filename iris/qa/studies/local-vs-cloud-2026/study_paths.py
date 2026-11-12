"""Shared paths of the local-vs-cloud study.

IRIS_STUDY_CONFIG: folder with application.<name>.yml and llm_config.yml (built by
build_configs.py). It holds API keys, so keep it outside the repository.
IRIS_STUDY_DATA: folder for runs and judgments (default: ./data, ignored by git).
"""

import os
from pathlib import Path

STUDY = Path(__file__).resolve().parent
IRIS = STUDY.parents[2]
SCENARIOS = STUDY / "scenarios"
DATA = Path(os.environ.get("IRIS_STUDY_DATA", str(STUDY / "data")))


def config_dir() -> Path:
    """The folder with the per-configuration Iris settings (contains keys)."""
    value = os.environ.get("IRIS_STUDY_CONFIG")
    if not value:
        raise SystemExit(
            "Set IRIS_STUDY_CONFIG to the folder written by build_configs.py"
        )
    return Path(value)
