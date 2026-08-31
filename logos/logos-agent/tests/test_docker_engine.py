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
