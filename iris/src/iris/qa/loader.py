from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from iris.qa.schema import Scenario, ScenarioSuite
from iris.qa.yaml_utils import safe_load_unique

# pylint: disable=inconsistent-quotes


class ScenarioLoadError(ValueError):
    """Raised when scenario files or fixture references are invalid."""


_IGNORED_REPOSITORY_PARTS = {".git", ".pytest_cache", "__pycache__"}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _load_yaml(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return safe_load_unique(stream)
    except (OSError, yaml.YAMLError) as error:
        raise ScenarioLoadError(f"Cannot load {path}: {error}") from error


def _fixture_payload(path: Path, fixture_root: Path, stack: tuple[Path, ...]) -> dict:
    resolved = path.resolve()
    root = fixture_root.resolve()
    if root not in resolved.parents and resolved != root:
        raise ScenarioLoadError(f"Fixture escapes fixture root: {path}")
    if resolved in stack:
        cycle = " -> ".join(str(item) for item in (*stack, resolved))
        raise ScenarioLoadError(f"Fixture inheritance cycle: {cycle}")
    raw = _load_yaml(resolved)
    if not isinstance(raw, dict):
        raise ScenarioLoadError(f"Fixture must be a mapping: {resolved}")

    payload: dict[str, Any] = {}
    for parent in raw.pop("extends", []) or []:
        payload = _deep_merge(
            payload,
            _fixture_payload(fixture_root / parent, fixture_root, (*stack, resolved)),
        )
    return _deep_merge(payload, raw)


def _scenario_from_raw(raw: dict[str, Any], fixture_root: Path) -> Scenario:
    resolved_payload: dict[str, Any] = {}
    fixtures = raw.get("fixtures", []) or []
    if not isinstance(fixtures, list):
        raise ScenarioLoadError("scenario fixtures must be a list")
    for reference in fixtures:
        resolved_payload = _deep_merge(
            resolved_payload,
            _fixture_payload(fixture_root / reference, fixture_root, ()),
        )
    payload = raw.get("payload", {})
    if not isinstance(payload, dict):
        raise ScenarioLoadError("scenario payload must be a mapping")
    resolved_payload = _deep_merge(resolved_payload, payload)
    return Scenario.model_validate({**raw, "payload": resolved_payload})


def _repository_snapshot(path: Path, artifact_root: Path) -> dict[str, str]:
    absolute_root = artifact_root.absolute()
    try:
        relative_reference = path.absolute().relative_to(absolute_root)
    except ValueError:
        relative_reference = None
    if relative_reference is not None:
        cursor = absolute_root
        for part in relative_reference.parts:
            cursor /= part
            if cursor.is_symlink():
                raise ScenarioLoadError(
                    "Artifact repository references may not traverse symlinks: "
                    f"{cursor}"
                )
    resolved = path.resolve()
    root = artifact_root.resolve()
    if root not in resolved.parents and resolved != root:
        raise ScenarioLoadError(f"Artifact repository escapes artifact root: {path}")
    if not resolved.is_dir():
        raise ScenarioLoadError(f"Artifact repository is not a directory: {path}")

    files: dict[str, str] = {}
    for item in sorted(resolved.rglob("*")):
        if item.is_symlink():
            raise ScenarioLoadError(
                f"Artifact repositories may not contain symlinks: {item}"
            )
        relative_path = item.relative_to(resolved)
        if not item.is_file() or _IGNORED_REPOSITORY_PARTS & set(relative_path.parts):
            continue
        try:
            relative = relative_path.as_posix()
            files[relative] = item.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise ScenarioLoadError(
                f"Artifact repository file is not UTF-8: {item}"
            ) from error
    if not files:
        raise ScenarioLoadError(f"Artifact repository contains no files: {path}")
    return files


def _hydrate_artifacts(value: Any, artifact_root: Path) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$repository"}:
            reference = value["$repository"]
            if not isinstance(reference, str) or not reference:
                raise ScenarioLoadError("$repository must be a non-empty relative path")
            return _repository_snapshot(artifact_root / reference, artifact_root)
        return {
            key: _hydrate_artifacts(item, artifact_root) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_hydrate_artifacts(item, artifact_root) for item in value]
    return value


def load_suite(
    scenario_root: Path,
    fixture_root: Path,
    artifact_root: Path | None = None,
) -> ScenarioSuite:
    artifact_root = artifact_root or fixture_root.parent / "artifacts"
    scenario_files = sorted(scenario_root.rglob("*.yml")) + sorted(
        scenario_root.rglob("*.yaml")
    )
    if not scenario_files:
        raise ScenarioLoadError(f"No scenario files found below {scenario_root}")

    scenarios: list[Scenario] = []
    version = 1
    for path in scenario_files:
        raw = _load_yaml(path)
        if not isinstance(raw, dict):
            raise ScenarioLoadError(f"Scenario file must be a mapping: {path}")
        version = max(version, int(raw.get("version", 1)))
        entries = raw.get("scenarios")
        if not isinstance(entries, list):
            raise ScenarioLoadError(f"Missing scenarios list: {path}")
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ScenarioLoadError(
                    f"Scenario entry {index} in {path} must be a mapping"
                )
            try:
                scenario = _scenario_from_raw(entry, fixture_root)
                scenario.payload = _hydrate_artifacts(scenario.payload, artifact_root)
                scenarios.append(scenario)
            except (ScenarioLoadError, ValueError) as error:
                raise ScenarioLoadError(
                    f"Invalid scenario {entry.get('id', index)!r} in {path}: {error}"
                ) from error

    return ScenarioSuite(version=version, scenarios=scenarios)


def filter_scenarios(
    suite: ScenarioSuite,
    *,
    profile: str | None = None,
    scenario_ids: set[str] | None = None,
    tags: set[str] | None = None,
    difficulties: set[str] | None = None,
) -> list[Scenario]:
    selected = suite.scenarios
    if profile:
        selected = [scenario for scenario in selected if profile in scenario.profiles]
    if scenario_ids:
        selected = [scenario for scenario in selected if scenario.id in scenario_ids]
        missing = scenario_ids - {scenario.id for scenario in selected}
        if missing:
            raise ScenarioLoadError(
                f"Unknown or filtered scenario ids: {sorted(missing)}"
            )
    if tags:
        selected = [scenario for scenario in selected if tags <= scenario.tags]
    if difficulties:
        selected = [
            scenario for scenario in selected if scenario.difficulty in difficulties
        ]
    return selected
