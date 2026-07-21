from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ValidationError

from iris.domain.autonomous_tutor.autonomous_tutor_pipeline_execution_dto import (
    AutonomousTutorPipelineExecutionDTO,
)
from iris.domain.chat.chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.qa.schema import Scenario, UseCase
from iris.qa.yaml_utils import safe_load_unique


class ScenarioContractError(ValueError):
    """Raised when a scenario no longer matches the production wire contract."""


@dataclass(frozen=True)
class ContractResult:
    scenario_id: str
    dto_type: str
    round_trip_payload: dict[str, Any]


_WIRE_FIELDS = {
    UseCase.CHAT: {
        "chatMode",
        "chatHistory",
        "settings",
        "sessionTitle",
        "user",
        "customInstructions",
        "course",
        "programmingExercise",
        "textExercise",
        "lecture",
        "lectureUnitId",
        "programmingExerciseSubmission",
        "textExerciseSubmission",
        "metrics",
        "context",
    },
    UseCase.TUTOR_SUGGESTION: {
        "chatMode",
        "course",
        "post",
        "chatHistory",
        "user",
        "settings",
        "textExerciseDTO",
        "submission",
        "programmingExerciseDTO",
        "lectureId",
    },
    UseCase.AUTONOMOUS_TUTOR: {
        "course",
        "post",
        "user",
        "settings",
        "programmingExercise",
        "textExercise",
        "lecture",
    },
}

_PROGRAMMING_EXERCISE_FIELDS = {
    "id",
    "title",
    "programmingLanguage",
    "templateRepository",
    "solutionRepository",
    "testRepository",
    "problemStatement",
    "startDate",
    "endDate",
}

_SUBMISSION_FIELDS = {
    "id",
    "date",
    "repository",
    "isPractice",
    "buildFailed",
    "buildLogEntries",
    "latestResult",
}

_IGNORED_SNAPSHOT_PARTS = {".git", ".pytest_cache", "__pycache__"}


def _dto_for(scenario: Scenario) -> type[BaseModel] | None:
    return {
        UseCase.CHAT: ChatPipelineExecutionDTO,
        UseCase.TUTOR_SUGGESTION: CommunicationTutorSuggestionPipelineExecutionDTO,
        UseCase.AUTONOMOUS_TUTOR: AutonomousTutorPipelineExecutionDTO,
        UseCase.GLOBAL_SEARCH: None,
    }[scenario.use_case]


def _validate_global_search(scenario: Scenario) -> ContractResult:
    payload = scenario.payload
    _validate_synthetic_now(scenario.id, payload.get("qa", {}).get("syntheticNow"))
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ScenarioContractError(f"{scenario.id}: global search requires a query")
    limit = payload.get("limit", 5)
    if not isinstance(limit, int) or not 1 <= limit <= 5:
        raise ScenarioContractError(f"{scenario.id}: global search limit must be 1..5")
    intent = payload.get("intent")
    if intent not in {"SEARCH", "SKIP_AI"}:
        raise ScenarioContractError(
            f"{scenario.id}: global search intent must be SEARCH or SKIP_AI"
        )
    sources = payload.get("qa", {}).get("sources", [])
    if not isinstance(sources, list):
        raise ScenarioContractError(f"{scenario.id}: qa.sources must be a list")
    return ContractResult(scenario.id, "GlobalSearchInvocation", dict(payload))


def _history_datetime(value: Any, *, scenario_id: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as error:
            raise ScenarioContractError(
                f"{scenario_id}: invalid submission-history timestamp {value!r}"
            ) from error
    if parsed.tzinfo is None:
        raise ScenarioContractError(
            f"{scenario_id}: submission-history timestamps must include a timezone"
        )
    return parsed


def _validate_synthetic_now(scenario_id: str, value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ScenarioContractError(
            f"{scenario_id}: qa.syntheticNow must be a nonempty ISO timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ScenarioContractError(
            f"{scenario_id}: invalid qa.syntheticNow timestamp {value!r}"
        ) from error
    if parsed.tzinfo is None:
        raise ScenarioContractError(
            f"{scenario_id}: qa.syntheticNow must include a timezone"
        )
    return parsed


def _validate_scenario_timestamps(
    scenario_id: str, payload: dict[str, Any], synthetic_now: datetime
) -> None:
    timestamps: list[tuple[str, Any]] = []
    message_timestamps: list[datetime] = []
    message_ids: set[int] = set()
    for index, message in enumerate(payload.get("chatHistory", [])):
        if not isinstance(message, dict):
            raise ScenarioContractError(
                f"{scenario_id}: chatHistory[{index}] must be an object"
            )
        message_id = message.get("id")
        if not isinstance(message_id, int) or isinstance(message_id, bool):
            raise ScenarioContractError(
                f"{scenario_id}: chatHistory[{index}].id must be an integer"
            )
        if message_id in message_ids:
            raise ScenarioContractError(
                f"{scenario_id}: duplicate chat message id {message_id}"
            )
        message_ids.add(message_id)
        if message.get("sentAt") is None:
            raise ScenarioContractError(
                f"{scenario_id}: chatHistory[{index}].sentAt is required by Artemis"
            )
        sent_at = _history_datetime(message["sentAt"], scenario_id=scenario_id)
        message_timestamps.append(sent_at)
        timestamps.append((f"chatHistory[{index}].sentAt", message["sentAt"]))

        contents = message.get("contents")
        if not isinstance(contents, list) or not contents:
            raise ScenarioContractError(
                f"{scenario_id}: chatHistory[{index}].contents must be nonempty"
            )
        for content_index, content in enumerate(contents):
            content_type = content.get("type") if isinstance(content, dict) else None
            if content_type not in {"text", "json", "image"}:
                raise ScenarioContractError(
                    f"{scenario_id}: chatHistory[{index}].contents[{content_index}] "
                    "must use an Artemis text/json/image type discriminator"
                )
    if any(
        current <= previous
        for previous, current in zip(message_timestamps, message_timestamps[1:])
    ):
        raise ScenarioContractError(
            f"{scenario_id}: chatHistory sentAt values must be strictly chronological"
        )
    for field in ("programmingExerciseSubmission", "submission"):
        submission = payload.get(field)
        if not isinstance(submission, dict):
            continue
        if submission.get("date") is not None:
            timestamps.append((f"{field}.date", submission["date"]))
        for index, entry in enumerate(submission.get("buildLogEntries", [])):
            if isinstance(entry, dict) and entry.get("timestamp") is not None:
                timestamps.append(
                    (f"{field}.buildLogEntries[{index}].timestamp", entry["timestamp"])
                )
        result = submission.get("latestResult")
        if isinstance(result, dict) and result.get("completionDate") is not None:
            timestamps.append(
                (f"{field}.latestResult.completionDate", result["completionDate"])
            )
    for label, value in timestamps:
        parsed = _history_datetime(value, scenario_id=scenario_id)
        if parsed > synthetic_now:
            raise ScenarioContractError(
                f"{scenario_id}: {label} {parsed.isoformat()} is after "
                f"qa.syntheticNow {synthetic_now.isoformat()}"
            )


def _validate_submission_history(
    scenario_id: str,
    *,
    qa_root: Path,
    provenance: Any,
    payload: dict[str, Any],
) -> None:
    if not isinstance(provenance, str) or not provenance:
        raise ScenarioContractError(
            f"{scenario_id}: submissionHistory must be a nonempty relative path"
        )
    relative = Path(provenance)
    if relative.is_absolute() or ".." in relative.parts:
        raise ScenarioContractError(
            f"{scenario_id}: submission history escapes the QA artifact root"
        )
    history_path = qa_root / relative
    artifact_root = (qa_root / "artifacts").resolve()
    resolved_history = history_path.resolve()
    if artifact_root not in resolved_history.parents:
        raise ScenarioContractError(
            f"{scenario_id}: submission history must be below qa/artifacts"
        )
    cursor = qa_root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ScenarioContractError(
                f"{scenario_id}: submission history may not traverse symlinks"
            )
    try:
        history = safe_load_unique(history_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise ScenarioContractError(
            f"{scenario_id}: cannot read submission history {provenance}: {error}"
        ) from error
    if not isinstance(history, dict) or not isinstance(
        history.get("submissions"), list
    ):
        raise ScenarioContractError(
            f"{scenario_id}: submission history requires a submissions list"
        )
    entries = history["submissions"]
    if not entries:
        raise ScenarioContractError(
            f"{scenario_id}: submission history must not be empty"
        )
    required = {"id", "commit", "date", "snapshot", "build", "note"}
    seen_ids: set[int] = set()
    timestamps: list[datetime] = []
    by_id: dict[int, dict[str, Any]] = {}
    repositories_by_id: dict[int, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not required <= set(entry):
            raise ScenarioContractError(
                f"{scenario_id}: every history entry requires {sorted(required)}"
            )
        entry_id = entry["id"]
        if not isinstance(entry_id, int) or isinstance(entry_id, bool):
            raise ScenarioContractError(
                f"{scenario_id}: submission-history ids must be integers"
            )
        if entry_id in seen_ids:
            raise ScenarioContractError(
                f"{scenario_id}: duplicate submission-history id {entry_id}"
            )
        seen_ids.add(entry_id)
        by_id[entry_id] = entry
        timestamps.append(_history_datetime(entry["date"], scenario_id=scenario_id))
        if not isinstance(entry["commit"], str) or not entry["commit"].strip():
            raise ScenarioContractError(
                f"{scenario_id}: submission-history commits must be nonempty"
            )
        if entry["build"] not in {"failed", "passed", "not-run"}:
            raise ScenarioContractError(
                f"{scenario_id}: invalid submission-history build state"
            )
        if not isinstance(entry["note"], str) or not entry["note"].strip():
            raise ScenarioContractError(
                f"{scenario_id}: submission-history notes must be nonempty"
            )
        snapshot = Path(str(entry["snapshot"]))
        if snapshot.is_absolute() or ".." in snapshot.parts:
            raise ScenarioContractError(
                f"{scenario_id}: history snapshot escapes its artifact directory"
            )
        snapshot_path = history_path.parent / snapshot
        resolved_snapshot = snapshot_path.resolve()
        if history_path.parent.resolve() not in resolved_snapshot.parents:
            raise ScenarioContractError(
                f"{scenario_id}: history snapshot escapes its artifact directory"
            )
        cursor = history_path.parent
        for part in snapshot.parts:
            cursor /= part
            if cursor.is_symlink():
                raise ScenarioContractError(
                    f"{scenario_id}: history snapshot may not traverse symlinks"
                )
        snapshot_items = list(resolved_snapshot.rglob("*"))
        if any(item.is_symlink() for item in snapshot_items):
            raise ScenarioContractError(
                f"{scenario_id}: history snapshots may not contain symlinks"
            )
        repository: dict[str, str] = {}
        if resolved_snapshot.is_dir():
            for item in snapshot_items:
                relative_item = item.relative_to(resolved_snapshot)
                if not item.is_file() or _IGNORED_SNAPSHOT_PARTS & set(
                    relative_item.parts
                ):
                    continue
                try:
                    repository[relative_item.as_posix()] = item.read_text(
                        encoding="utf-8"
                    )
                except (OSError, UnicodeDecodeError) as error:
                    raise ScenarioContractError(
                        f"{scenario_id}: cannot read history snapshot file "
                        f"{relative_item}: {error}"
                    ) from error
        if not repository:
            raise ScenarioContractError(
                f"{scenario_id}: history snapshot is missing or empty: {snapshot}"
            )
        repositories_by_id[entry_id] = repository
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ScenarioContractError(
            f"{scenario_id}: submission history must be strictly chronological"
        )

    submission = payload.get("programmingExerciseSubmission") or payload.get(
        "submission"
    )
    if not isinstance(submission, dict) or submission.get("id") not in by_id:
        raise ScenarioContractError(
            f"{scenario_id}: selected Artemis submission is absent from its history"
        )
    entry = by_id[submission["id"]]
    if (
        _history_datetime(submission.get("date"), scenario_id=scenario_id)
        != timestamps[entries.index(entry)]
    ):
        raise ScenarioContractError(
            f"{scenario_id}: selected submission date differs from its history"
        )
    if bool(submission.get("buildFailed")) != (entry["build"] == "failed"):
        raise ScenarioContractError(
            f"{scenario_id}: selected submission build state differs from its history"
        )
    if submission.get("repository") != repositories_by_id[submission["id"]]:
        raise ScenarioContractError(
            f"{scenario_id}: selected submission repository differs from its "
            "history snapshot"
        )


def validate_scenario_contract(
    scenario: Scenario,
    *,
    qa_root: Path,
) -> ContractResult:
    """Parse a scenario through the production DTO and verify QA-only provenance."""
    if scenario.use_case == UseCase.GLOBAL_SEARCH:
        return _validate_global_search(scenario)

    payload = dict(scenario.payload)
    qa_metadata = payload.pop("qa", {}) or {}
    synthetic_now = _validate_synthetic_now(
        scenario.id, qa_metadata.get("syntheticNow")
    )
    _validate_scenario_timestamps(scenario.id, payload, synthetic_now)
    unsupported = set(payload) - _WIRE_FIELDS[scenario.use_case]
    if unsupported:
        raise ScenarioContractError(
            f"{scenario.id}: fields not sent by the current Artemis wire DTO: "
            f"{sorted(unsupported)}"
        )
    for field in ("programmingExercise", "programmingExerciseDTO"):
        if field in payload:
            unsupported = set(payload[field]) - _PROGRAMMING_EXERCISE_FIELDS
            if unsupported:
                raise ScenarioContractError(
                    f"{scenario.id}: unsupported Artemis {field} fields: "
                    f"{sorted(unsupported)}"
                )
    for field in ("programmingExerciseSubmission", "submission"):
        if field in payload:
            unsupported = set(payload[field]) - _SUBMISSION_FIELDS
            if unsupported:
                raise ScenarioContractError(
                    f"{scenario.id}: unsupported Artemis {field} fields: "
                    f"{sorted(unsupported)}"
                )
    dto_type = _dto_for(scenario)
    if dto_type is None:  # pragma: no cover - global search returns above
        raise ScenarioContractError(f"{scenario.id}: no production DTO type")
    try:
        dto = dto_type.model_validate(payload)
    except ValidationError as error:
        raise ScenarioContractError(
            f"{scenario.id}: invalid {dto_type.__name__} payload: {error}"
        ) from error

    settings = getattr(dto, "settings", None)
    wire_support = settings.support_level if settings else "moderate"
    if wire_support != scenario.support_level:
        raise ScenarioContractError(
            f"{scenario.id}: schema support {scenario.support_level} differs from "
            f"wire support {wire_support}"
        )

    if scenario.use_case == UseCase.CHAT:
        chat_dto = cast(ChatPipelineExecutionDTO, dto)
        if chat_dto.chat_mode.value != scenario.mode:
            raise ScenarioContractError(
                f"{scenario.id}: schema mode {scenario.mode} differs from wire mode "
                f"{chat_dto.chat_mode.value}"
            )
        if chat_dto.settings and chat_dto.settings.stream_response:
            raise ScenarioContractError(
                f"{scenario.id}: paid QA requires streamResponse=false so "
                "truncation and usage are accounted atomically"
            )
        if not chat_dto.chat_history:
            raise ScenarioContractError(
                f"{scenario.id}: chat history must not be empty"
            )
        if chat_dto.chat_history[-1].sender.value != "USER":
            raise ScenarioContractError(
                f"{scenario.id}: the next-answer contract requires a final USER message"
            )

    provenance = qa_metadata.get("submissionHistory")
    if (
        scenario.use_case == UseCase.CHAT
        and scenario.mode == "PROGRAMMING_EXERCISE_CHAT"
        and not provenance
    ):
        raise ScenarioContractError(
            f"{scenario.id}: programming chat requires submission-history provenance"
        )
    if provenance:
        _validate_submission_history(
            scenario.id,
            qa_root=qa_root,
            provenance=provenance,
            payload=payload,
        )

    # Dump and parse again to catch alias or polymorphic-content drift.
    round_trip = dto.model_dump(by_alias=True, mode="json", exclude_none=True)
    # Three characters per token is deliberately conservative for mixed
    # prose/code fixtures. The runtime ceiling retains headroom for production
    # prompts, tool schemas, and later agent turns.
    fixture_tokens = math.ceil(len(json.dumps(round_trip, ensure_ascii=False)) / 3)
    if fixture_tokens > scenario.token_ceiling.max_input_tokens:
        raise ScenarioContractError(
            f"{scenario.id}: fixture estimate {fixture_tokens} tokens exceeds "
            f"input ceiling {scenario.token_ceiling.max_input_tokens}"
        )
    try:
        dto_type.model_validate(round_trip)
    except ValidationError as error:  # pragma: no cover - defensive against DTO drift
        raise ScenarioContractError(
            f"{scenario.id}: DTO round-trip failed: {error}"
        ) from error
    return ContractResult(scenario.id, dto_type.__name__, round_trip)


def validate_suite_contracts(
    scenarios: list[Scenario],
    *,
    qa_root: Path,
) -> list[ContractResult]:
    results = []
    errors = []
    for scenario in scenarios:
        try:
            results.append(validate_scenario_contract(scenario, qa_root=qa_root))
        except ScenarioContractError as error:
            errors.append(str(error))
    if errors:
        raise ScenarioContractError(
            "Scenario contract failures:\n- " + "\n- ".join(errors)
        )
    return results
