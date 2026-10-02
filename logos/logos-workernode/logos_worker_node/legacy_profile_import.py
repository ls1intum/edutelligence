"""One-time hand-over of a node's former local profile files to Logos.

Workers used to keep model_profiles.yml and calibration_unsupported_models.txt
in their state directory. Their content is sent once with the startup profile
request; Logos ignores it as soon as the node has profiles in the database.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROFILES_FILE = "model_profiles.yml"
_UNSUPPORTED_FILE = Path("calibration_logs") / "calibration_unsupported_models.txt"
_MIGRATED_SUFFIX = ".migrated"


def _legacy_files(state_dir: Path) -> list[Path]:
    return [state_dir / _PROFILES_FILE, state_dir / _UNSUPPORTED_FILE]


def read_legacy_profiles(state_dir: Path) -> dict[str, Any] | None:
    """The request's ``legacy_import`` body, or None when nothing is left."""
    profiles_path, unsupported_path = _legacy_files(state_dir)
    if not profiles_path.exists() and not unsupported_path.exists():
        return None
    profiles: dict[str, Any] = {}
    if profiles_path.exists():
        try:
            data = yaml.safe_load(profiles_path.read_text(encoding="utf-8")) or {}
            raw = data.get("model_profiles") if isinstance(data, dict) else None
            profiles = {str(k): v for k, v in (raw or {}).items() if isinstance(v, dict)}
        except Exception:  # noqa: BLE001
            logger.exception("Could not read %s; its profiles are not handed over", profiles_path)
    unsupported: dict[str, str] = {}
    if unsupported_path.exists():
        for line in unsupported_path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            model = parts[0].strip()
            if model:
                unsupported[model] = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "unknown"
    return {"model_profiles": profiles, "unsupported_models": unsupported}


def mark_legacy_profiles_migrated(state_dir: Path) -> None:
    """Rename the files instead of deleting them, so a rollback can use them."""
    for path in _legacy_files(state_dir):
        if path.exists():
            path.rename(path.with_name(path.name + _MIGRATED_SUFFIX))
            logger.info("Handed %s over to Logos; kept as %s%s", path, path.name, _MIGRATED_SUFFIX)
