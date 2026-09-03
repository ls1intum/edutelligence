"""Tests for the Docker Engine API calls, against the daemon's real shapes.

The Engine API is exact: a wrong guess about a response's shape does not show
up as an exception in the happy path, it shows up as a service that fails at
the first real launch. So the parsers here are tested against payloads shaped
like the daemon's actual answers.
"""

from __future__ import annotations

import pytest
from app import docker_engine
from app.docker_engine import DockerError


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


# A real `docker volume inspect` / GET /volumes/{name} answer for a local
# volume: the volume object comes back at the top level, not keyed by name.
LOCAL_VOLUME = {
    "Name": "logos_agent_artifacts",
    "Driver": "local",
    "Mountpoint": "/var/lib/docker/volumes/logos_agent_artifacts/_data",
    "CreatedAt": "2026-08-30T07:00:00.000000000Z",
    "Labels": {"logos.agent": "artifacts"},
    "Scope": "local",
    "Options": {},
}


class TestVolumeMountpoint:
    async def test_reads_the_mountpoint_from_the_volume_object(self, monkeypatch):
        async def fake_request(method, path, **kwargs):
            assert method == "GET"
            assert path == "/volumes/logos_agent_artifacts"
            return _FakeResponse(LOCAL_VOLUME)

        monkeypatch.setattr(docker_engine, "_request", fake_request)
        mountpoint = await docker_engine.volume_mountpoint("logos_agent_artifacts")
        assert mountpoint == "/var/lib/docker/volumes/logos_agent_artifacts/_data"

    async def test_a_volume_without_a_host_mountpoint_is_an_error(self, monkeypatch):
        # Non-local drivers have no host path at all; the bind-source
        # resolution this runner depends on is impossible for them.
        async def fake_request(method, path, **kwargs):
            return _FakeResponse({"Name": "remote", "Driver": "rclone", "Scope": "global"})

        monkeypatch.setattr(docker_engine, "_request", fake_request)
        with pytest.raises(DockerError):
            await docker_engine.volume_mountpoint("remote")


class TestNetworkIsolation:
    """The session network's `Internal` flag is the isolation boundary.

    An internal bridge has no route off the host, which is the reason a
    container running an agent with permission prompts disabled may hold no
    reusable credential and still be safe. An existing network created as a
    plain bridge would take that away silently.
    """

    async def test_an_existing_internal_network_is_accepted(self, monkeypatch):
        calls: list = []

        async def fake_request(method, path, **kwargs):
            calls.append((method, path))
            if method == "GET":
                return {"Name": "logos-agent-net", "Internal": True}
            return {}

        monkeypatch.setattr(docker_engine, "_request", fake_request)

        await docker_engine.ensure_network("logos-agent-net", internal=True)

        # Verified, not recreated.
        assert [m for m, _ in calls] == ["GET"]

    async def test_a_plain_bridge_is_refused_rather_than_used(self, monkeypatch):
        async def fake_request(method, path, **kwargs):
            if method == "GET":
                return {"Name": "logos-agent-net", "Internal": False}
            return {}

        monkeypatch.setattr(docker_engine, "_request", fake_request)

        with pytest.raises(docker_engine.DockerError, match="external egress"):
            await docker_engine.ensure_network("logos-agent-net", internal=True)

    async def test_a_missing_network_is_created_with_the_flag(self, monkeypatch):
        created: dict = {}

        async def fake_request(method, path, **kwargs):
            if method == "GET":
                raise docker_engine.DockerError(404, "no such network")
            created.update(kwargs.get("json") or {})
            return {}

        monkeypatch.setattr(docker_engine, "_request", fake_request)

        await docker_engine.ensure_network("logos-agent-net", internal=True)

        assert created["Internal"] is True


class TestPauseReportsReality:
    """A pause the daemon refused must not be recorded as one.

    Docker answers 409 for a container that is not running: a session moved
    to 'paused' around a container that has exited can never be settled.
    """

    async def test_a_successful_pause_is_reported(self, monkeypatch):
        async def fake_request(method, path, **kwargs):
            return {}

        monkeypatch.setattr(docker_engine, "_request", fake_request)
        assert await docker_engine.pause_container("cid") is True

    async def test_an_already_paused_container_counts_as_paused(self, monkeypatch):
        async def fake_request(method, path, **kwargs):
            raise docker_engine.DockerError(304, "already paused")

        monkeypatch.setattr(docker_engine, "_request", fake_request)
        assert await docker_engine.pause_container("cid") is True

    async def test_a_container_that_is_not_running_is_not_paused(self, monkeypatch):
        async def fake_request(method, path, **kwargs):
            raise docker_engine.DockerError(409, "container is not running")

        monkeypatch.setattr(docker_engine, "_request", fake_request)
        assert await docker_engine.pause_container("cid") is False

    async def test_a_vanished_container_is_not_paused(self, monkeypatch):
        async def fake_request(method, path, **kwargs):
            raise docker_engine.DockerError(404, "no such container")

        monkeypatch.setattr(docker_engine, "_request", fake_request)
        assert await docker_engine.pause_container("cid") is False
        assert await docker_engine.unpause_container("cid") is False


class TestNetworkDetach:
    """Cutting a frozen session off its network ends its upstream request."""

    async def test_disconnect_forces_the_endpoint_down(self, monkeypatch):
        sent: dict = {}

        async def fake_request(method, path, **kwargs):
            sent.update({"method": method, "path": path, "json": kwargs.get("json")})
            return {}

        monkeypatch.setattr(docker_engine, "_request", fake_request)

        assert await docker_engine.disconnect_network("logos-agent-net", "cid") is True
        assert sent["path"] == "/networks/logos-agent-net/disconnect"
        assert sent["json"] == {"Container": "cid", "Force": True}

    async def test_an_already_attached_container_counts_as_connected(self, monkeypatch):
        async def fake_request(method, path, **kwargs):
            raise docker_engine.DockerError(403, "endpoint already exists in network")

        monkeypatch.setattr(docker_engine, "_request", fake_request)
        assert await docker_engine.connect_network("logos-agent-net", "cid") is True
