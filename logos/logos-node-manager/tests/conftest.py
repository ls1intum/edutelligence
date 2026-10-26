"""Test doubles for the node manager.

``FakeDocker`` simulates the part of the Docker engine that a deployment sees: one worker container, local images with
or without a name, a registry to pull from, and a script for how a freshly created container behaves over time.
``FakeOrchestrator`` answers the calls about the cordon of the node from a script. ``FakeClock`` makes the waits in the
checks cost no real time.
"""

from __future__ import annotations

from dataclasses import replace
from itertools import count

import pytest

from logos_node_manager.config import Settings
from logos_node_manager.deployer import Deployer
from logos_node_manager.docker_ops import ContainerInfo
from logos_node_manager.errors import DockerError
from logos_node_manager.orchestrator import CordonReply, NodeStatus
from logos_node_manager.runner import CommandResult
from logos_node_manager.state import Deployment, StateStore

REPO = "registry.example/logos/logos-workernode-vllm"
OLD = "sha256:" + "0" * 12 + "aaaa"
NEW = "sha256:" + "1" * 12 + "bbbb"
ANCIENT = "sha256:" + "2" * 12 + "cccc"

# What the orchestrator can answer to a request for the cordon. The worker session that runs before the swap is "old".
DRAINED = CordonReply(granted=True, drained=True, session_id="session-old")
BUSY = CordonReply(granted=True, drained=False, session_id="session-old", in_flight_orchestrator=2, in_flight_worker=1)
WAIT_FOR_TURN = CordonReply(granted=False, reason="another_node_in_maintenance", holder="node-b")
# What it sees of the node after the swap: a new session, with its first status.
RECONNECTED = NodeStatus(online=True, first_status_received=True, session_id="session-new")
NOT_BACK = NodeStatus(online=False, first_status_received=False, session_id=None)

HEALTHY = [{"health": "starting"}, {"health": "healthy"}]
CRASHED = [{"status": "exited", "running": False, "exit_code": 1, "health": "unhealthy"}]
UNHEALTHY = [{"health": "starting"}, {"health": "unhealthy"}]


class FakeClock:
    """Time that only moves when something sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeDocker:
    """The engine as the deployer sees it. Every field is a knob a test can turn."""

    def __init__(self) -> None:
        # name -> image id, on this host
        self.images: dict[str, str] = {f"{REPO}:latest": OLD}
        # Images that lost their last name and are still on the host. ``docker images`` lists them as <none>.
        self.unnamed: set[str] = set()
        # name -> image id, in the registry
        self.registry: dict[str, str] = {f"{REPO}:latest": NEW, f"{REPO}:v2": NEW}
        self._ids = count(1)
        self.container_info: ContainerInfo | None = ContainerInfo(
            id="c-old",
            image_id=OLD,
            image_ref=f"{REPO}:latest",
            status="running",
            running=True,
            restarting=False,
            exit_code=0,
            restart_count=0,
            health="healthy",
        )
        self._timeline: list[dict] = []

        # How a container behaves after it is created, as a list of field overrides handed out one per inspect call.
        # The last entry stays. The old image is the known good one, so a rollback always gets a working container.
        self.new_container_timeline: list[dict] = list(HEALTHY)
        self.old_image_timeline: list[dict] = list(HEALTHY)
        self.pull_error: str | None = None
        # One entry per call to ``up``: an error text, or None for success. Missing entries mean success.
        self.up_errors: list[str | None] = []
        # Whether a failing ``up`` has already removed the old container.
        self.failed_up_removes_container = False
        self.logs = "worker log line"
        self.calls: list[tuple] = []
        # The images that were actually deleted. ``calls`` also holds the attempts that the engine refused.
        self.removed: list[str] = []

    # ------------------------------------------------------------------ what a test can look at

    def host_images(self) -> set[str]:
        """Every image on this host, with or without a name."""
        return set(self.images.values()) | self.unnamed

    def _name(self, ref: str, image_id: str) -> None:
        """Point a name at an image. The image it pointed to before stays on the host, unnamed if that was its last."""
        before = self.images.get(ref)
        self.images[ref] = image_id
        self.unnamed.discard(image_id)
        if before and before != image_id and before not in self.images.values():
            self.unnamed.add(before)

    # ------------------------------------------------------------------ the Docker interface

    def pull(self, tag: str) -> CommandResult:
        self.calls.append(("pull", tag))
        if self.pull_error:
            return CommandResult(("pull",), 1, stderr=self.pull_error)
        ref = f"{REPO}:{tag}"
        if ref not in self.registry:
            return CommandResult(("pull",), 1, stderr=f"manifest for {ref} not found")
        self._name(ref, self.registry[ref])
        return CommandResult(("pull",), 0)

    def image_ref(self, tag: str) -> str:
        return f"{REPO}:{tag}"

    def image_id(self, ref: str) -> str | None:
        return self.images.get(ref)

    def tag(self, source: str, target: str) -> None:
        self.calls.append(("tag", source, target))
        image_id = source if source in self.host_images() else self.images.get(source)
        if image_id is None:
            raise DockerError(f"docker tag failed: No such image: {source}")
        self._name(target, image_id)

    def remove_image(self, image_id: str) -> bool:
        """``docker rmi <id>``: the engine refuses while a container uses the image or while it has several names."""
        self.calls.append(("remove_image", image_id))
        if image_id not in self.host_images():
            return False
        if self.container_info is not None and self.container_info.image_id == image_id:
            return False
        names = [ref for ref, known in self.images.items() if known == image_id]
        if len(names) > 1:
            return False
        for ref in names:
            del self.images[ref]
        self.unnamed.discard(image_id)
        self.removed.append(image_id)
        return True

    def container_logs(self, lines: int = 40) -> str:
        return self.logs

    def versions(self) -> str:
        return "engine fake, compose fake"

    def up(self, tag: str, *, recreate: bool = False, pull_never: bool = False) -> CommandResult:
        self.calls.append(("up", tag, recreate, pull_never))
        error = self.up_errors.pop(0) if self.up_errors else None
        if error:
            if self.failed_up_removes_container:
                self.container_info = None
            return CommandResult(("up",), 1, stderr=error)
        image = self.images.get(f"{REPO}:{tag}")
        if image is None:
            return CommandResult(("up",), 1, stderr="No such image")
        timeline = self.old_image_timeline if image == OLD else self.new_container_timeline
        current = self.container_info
        if current is not None and current.image_id == image and not recreate:
            if current.running:
                return CommandResult(("up",), 0)  # nothing to change
            # Compose starts a stopped container in place; it does not create another one.
            self.container_info = replace(current, status="running", running=True, health="starting")
            self._timeline = list(timeline)
            return CommandResult(("up",), 0)
        self.container_info = ContainerInfo(
            id=f"c-{next(self._ids)}",
            image_id=image,
            image_ref=f"{REPO}:{tag}",
            status="running",
            running=True,
            restarting=False,
            exit_code=0,
            restart_count=0,
            health="starting",
        )
        self._timeline = list(timeline)
        return CommandResult(("up",), 0)

    def container(self) -> ContainerInfo | None:
        if self.container_info is not None and self._timeline:
            override = self._timeline.pop(0) if len(self._timeline) > 1 else self._timeline[0]
            self.container_info = replace(self.container_info, **override)
        return self.container_info


class FakeOrchestrator:
    """The orchestrator as the deployer sees it.

    Each kind of call has a script: a list of replies or exceptions, handed out one per call. The last entry stays, so
    a script of one entry answers the same every time. An empty script answers like a node that is ready.
    """

    def __init__(self) -> None:
        self.cordon_replies: list = []
        self.status_replies: list = []
        self.release_replies: list = []
        self.report_replies: list = []
        self.calls: list[tuple] = []
        # The details of every report, by deployment id.
        self.reports: list[tuple[str, dict]] = []

    @staticmethod
    def _next(script: list, default):
        if not script:
            return default
        reply = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(reply, Exception):
            raise reply
        return reply

    def cordon(self, deployment_id: str) -> CordonReply:
        self.calls.append(("cordon", deployment_id))
        return self._next(self.cordon_replies, DRAINED)

    def status(self, deployment_id: str) -> NodeStatus:
        self.calls.append(("status", deployment_id))
        return self._next(self.status_replies, RECONNECTED)

    def release(self, deployment_id: str) -> None:
        self.calls.append(("release", deployment_id))
        self._next(self.release_replies, None)

    def report(self, deployment_id: str, details: dict) -> None:
        self.calls.append(("report", deployment_id))
        self._next(self.report_replies, None)
        self.reports.append((deployment_id, details))

    def count(self, call: str) -> int:
        return len([entry for entry in self.calls if entry[0] == call])


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings.from_env(
        {
            "NODE_MANAGER_PROJECT_DIR": str(tmp_path / "project"),
            "NODE_MANAGER_STATE_DIR": str(tmp_path / "state"),
            "NODE_MANAGER_STABILITY_WINDOW_S": "10",
            "NODE_MANAGER_POLL_INTERVAL_S": "5",
            "NODE_MANAGER_VERIFY_TIMEOUT_S": "60",
            "NODE_MANAGER_ROLLBACK_VERIFY_TIMEOUT_S": "60",
        }
    )


@pytest.fixture
def drain_settings(settings) -> Settings:
    """Settings of a host that drains: an orchestrator to ask, and short limits."""
    return replace(
        settings,
        drain_enabled=True,
        orchestrator_url="https://logos.example",
        node_key="the-secret-node-key",
        drain_timeout_s=60,
        turn_timeout_s=120,
        orchestrator_retry_window_s=20,
        reconnect_timeout_s=30,
    )


@pytest.fixture
def orchestrator() -> FakeOrchestrator:
    return FakeOrchestrator()


@pytest.fixture
def store(settings) -> StateStore:
    return StateStore(settings.state_dir)


@pytest.fixture
def docker() -> FakeDocker:
    return FakeDocker()


@pytest.fixture
def make_deployer(settings, store, docker, clock):
    """Build a deployer; ``should_stop`` can be replaced by the test."""

    def build(**overrides) -> Deployer:
        options = {"clock": clock, "sleep": clock.sleep, "now": lambda: "2026-01-01T00:00:00.000000+00:00"}
        options.update(overrides)
        return Deployer(options.pop("settings", settings), docker, store, **options)

    return build


@pytest.fixture
def deployer(make_deployer) -> Deployer:
    return make_deployer()


@pytest.fixture
def draining_deployer(make_deployer, drain_settings, orchestrator) -> Deployer:
    """A deployer on a host that drains, talking to the scripted orchestrator."""
    return make_deployer(settings=drain_settings, orchestrator=orchestrator)


def queued(store: StateStore, tag: str = "v2", deployment_id: str = "run-1") -> Deployment:
    return store.submit(Deployment(id=deployment_id, tag=tag, requested_at="2026-01-01T00:00:00.000000+00:00"))
