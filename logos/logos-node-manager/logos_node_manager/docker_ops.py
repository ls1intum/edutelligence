"""The Docker operations of a deployment, as typed calls.

Compose stays the one place that defines the worker container (GPUs, volumes, limits), so the manager recreates the
container with ``docker compose up`` and never rebuilds that definition through the Docker API.

Two rules hold for everything in this module:

* ``docker compose config`` prints the resolved environment, secrets included. It is only called with ``--images``,
  and no output of it is logged.
* The requested image tag reaches Compose as the ``IMAGE_TAG`` process variable. A variable in the process environment
  beats the same variable in the ``.env`` file, so a later rewrite of that file cannot change what an earlier request
  deploys.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from logos_node_manager.config import Settings
from logos_node_manager.errors import DockerError
from logos_node_manager.runner import CommandResult, Runner

logger = logging.getLogger(__name__)

# Seconds allowed for the quick engine queries: inspect, tag, remove, logs, version.
QUERY_TIMEOUT_S = 30.0
# Compose has to read and interpolate the whole file before it prints the image names.
CONFIG_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class ContainerInfo:
    """The part of ``docker inspect`` that a deployment looks at."""

    id: str
    image_id: str
    image_ref: str
    status: str
    running: bool
    restarting: bool
    exit_code: int
    restart_count: int
    # None when the image defines no health check.
    health: str | None


def split_image_ref(ref: str) -> tuple[str, str | None]:
    """Split ``registry:port/name:tag`` into the name and the tag. A digest is dropped.

    The colon of a registry port is not a tag separator: a tag colon comes after the last slash.
    """
    name = ref.split("@", 1)[0]
    colon = name.rfind(":")
    if colon > name.rfind("/"):
        return name[:colon], name[colon + 1 :]
    return name, None


def _container_from_inspect(raw: dict) -> ContainerInfo:
    state = raw.get("State") or {}
    health = (state.get("Health") or {}).get("Status")
    return ContainerInfo(
        id=str(raw.get("Id") or ""),
        image_id=str(raw.get("Image") or ""),
        image_ref=str((raw.get("Config") or {}).get("Image") or ""),
        status=str(state.get("Status") or ""),
        running=bool(state.get("Running")),
        restarting=bool(state.get("Restarting")),
        exit_code=int(state.get("ExitCode") or 0),
        restart_count=int(raw.get("RestartCount") or 0),
        health=str(health) if health else None,
    )


def describe_registry_login(config_file: Path) -> str:
    """One line about the registry login the manager can see. Only names and counts, never a credential."""
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return f"no Docker login file at {config_file}"
    except (OSError, ValueError) as exc:
        return f"Docker login file {config_file} is unreadable: {exc}"
    registries = len(data.get("auths") or {})
    helper = data.get("credsStore") or ""
    helpers = len(data.get("credHelpers") or {})
    note = ""
    if helper or helpers:
        note = " (a credential helper is set; the helper program is not available in this container)"
    return (
        f"Docker login file: {registries} registry login(s), credsStore={helper or 'none'}, credHelpers={helpers}{note}"
    )


class Docker:
    """The docker command line, aimed at the worker service of one compose project."""

    def __init__(self, settings: Settings, runner: Runner) -> None:
        self._settings = settings
        self._runner = runner

    # ------------------------------------------------------------------ Compose

    def _compose(self, *args: str) -> list[str]:
        s = self._settings
        return [
            "docker",
            "compose",
            "-p",
            s.project_name,
            "-f",
            str(s.compose_file),
            "--env-file",
            str(s.env_file),
            *args,
        ]

    @staticmethod
    def _tag_env(tag: str | None) -> dict[str, str] | None:
        return {"IMAGE_TAG": tag} if tag else None

    def pull(self, tag: str) -> CommandResult:
        """Download the image of the worker service for ``tag``."""
        return self._runner.run(
            self._compose("pull", self._settings.service),
            timeout_s=self._settings.pull_timeout_s,
            env=self._tag_env(tag),
        )

    def up(self, tag: str, *, recreate: bool = False, pull_never: bool = False) -> CommandResult:
        """Create or replace the worker container.

        Only the worker service is touched (``--no-deps``). Compose recreates the container when its image or its
        configuration changed, and leaves it alone otherwise.
        """
        args = ["up", "-d", "--no-deps"]
        if recreate:
            args.append("--force-recreate")
        if pull_never:
            args += ["--pull", "never"]
        args.append(self._settings.service)
        return self._runner.run(self._compose(*args), timeout_s=self._settings.swap_timeout_s, env=self._tag_env(tag))

    def image_ref(self, tag: str) -> str:
        """The image reference Compose uses for the worker service when the tag is ``tag``."""
        result = self._runner.run(
            self._compose("config", "--images", self._settings.service),
            timeout_s=CONFIG_TIMEOUT_S,
            env=self._tag_env(tag),
        )
        if not result.ok:
            raise DockerError(f"docker compose config failed: {result.tail()}")
        refs = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(refs) != 1:
            raise DockerError(f"expected one image for service {self._settings.service!r}, got {len(refs)}")
        return refs[0]

    # ------------------------------------------------------------------ Engine

    def container(self) -> ContainerInfo | None:
        """The worker container, or None if it does not exist."""
        result = self._runner.run(
            ["docker", "inspect", "--type", "container", self._settings.container], timeout_s=QUERY_TIMEOUT_S
        )
        if not result.ok:
            if "no such" in result.stderr.lower():
                return None
            raise DockerError(f"docker inspect failed: {result.tail()}")
        try:
            return _container_from_inspect(json.loads(result.stdout)[0])
        except (ValueError, IndexError, TypeError) as exc:
            raise DockerError(f"docker inspect returned unexpected output: {exc}") from exc

    def image_id(self, ref: str) -> str | None:
        """The ID of a local image, or None if there is no such image."""
        result = self._runner.run(["docker", "image", "inspect", "--format", "{{.Id}}", ref], timeout_s=QUERY_TIMEOUT_S)
        if not result.ok:
            if "no such" in result.stderr.lower():
                return None
            raise DockerError(f"docker image inspect failed: {result.tail()}")
        return result.stdout.strip() or None

    def tag(self, source: str, target: str) -> None:
        """Give a local image another name."""
        result = self._runner.run(["docker", "tag", source, target], timeout_s=QUERY_TIMEOUT_S)
        if not result.ok:
            raise DockerError(f"docker tag failed: {result.tail()}")

    def remove_image(self, image_id: str) -> bool:
        """Delete a local image. Best effort: an image that a container still uses stays."""
        result = self._runner.run(["docker", "rmi", image_id], timeout_s=QUERY_TIMEOUT_S)
        if not result.ok:
            logger.info("Image %s was not removed: %s", image_id, result.tail(2))
        return result.ok

    def container_logs(self, lines: int = 40) -> str:
        """The end of the worker container's log, or an empty string if there is none."""
        result = self._runner.run(
            ["docker", "logs", "--tail", str(lines), self._settings.container], timeout_s=QUERY_TIMEOUT_S
        )
        return "\n".join(part for part in (result.stdout.rstrip(), result.stderr.rstrip()) if part)

    def versions(self) -> str:
        """Engine and Compose versions, for the log at start. Never raises."""
        engine = self._runner.run(
            ["docker", "version", "--format", "engine {{.Server.Version}} (API {{.Server.APIVersion}})"],
            timeout_s=QUERY_TIMEOUT_S,
        )
        compose = self._runner.run(["docker", "compose", "version", "--short"], timeout_s=QUERY_TIMEOUT_S)
        engine_text = engine.stdout.strip() if engine.ok else f"engine unavailable ({engine.tail(1)})"
        compose_text = f"compose {compose.stdout.strip()}" if compose.ok else f"compose unavailable ({compose.tail(1)})"
        return f"{engine_text}, {compose_text}"
