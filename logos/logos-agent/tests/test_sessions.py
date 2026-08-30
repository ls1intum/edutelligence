"""Tests for the session state machine and the naming rules around it.

The branch derivation is security-relevant — it is what stops a session
pushing to a protected branch — so it is tested against hostile workspace
names, not just ordinary ones.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace

import pytest
from app.config import settings
from app.schemas import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    SessionCreate,
    SessionStatus,
    WorkspaceCreate,
    can_transition,
)
from app.sessions import branch_for, container_name


class TestStateMachine:
    def test_normal_path(self):
        assert can_transition(SessionStatus.QUEUED, SessionStatus.STARTING)
        assert can_transition(SessionStatus.STARTING, SessionStatus.RUNNING)
        assert can_transition(SessionStatus.RUNNING, SessionStatus.SUCCEEDED)

    def test_pause_and_resume(self):
        assert can_transition(SessionStatus.RUNNING, SessionStatus.PAUSED)
        assert can_transition(SessionStatus.PAUSED, SessionStatus.RUNNING)

    def test_paused_never_returns_to_starting(self):
        # Re-running setup would wipe the working copy the pause preserved.
        assert not can_transition(SessionStatus.PAUSED, SessionStatus.STARTING)

    def test_terminal_states_are_final(self):
        for status in TERMINAL_STATUSES:
            for target in SessionStatus:
                assert not can_transition(status, target), f"{status} -> {target}"

    def test_every_active_state_can_be_cancelled(self):
        for status in ACTIVE_STATUSES:
            assert can_transition(status, SessionStatus.CANCELLED)

    def test_queued_cannot_jump_straight_to_running(self):
        # Running means a container exists; skipping starting would leave the
        # row claiming a container that was never created.
        assert not can_transition(SessionStatus.QUEUED, SessionStatus.RUNNING)


class TestBranchDerivation:
    def test_branch_carries_the_configured_prefix(self):
        branch = branch_for(7, "feature-work")
        assert branch.startswith(settings.branch_prefix)
        assert branch.endswith("session-7")

    def test_two_sessions_never_share_a_branch(self):
        assert branch_for(1, "same") != branch_for(2, "same")

    @pytest.mark.parametrize(
        "hostile",
        ["../../main", "main", "..", "a/../../../etc", "with space", "sem;icolon"],
    )
    def test_hostile_workspace_names_cannot_escape_the_prefix(self, hostile):
        branch = branch_for(3, hostile)
        assert branch.startswith(settings.branch_prefix)
        assert ".." not in branch
        # Whatever the name was, the branch still ends in this session's own
        # segment, so it cannot resolve to a protected branch.
        assert branch.endswith("session-3")
        assert branch.rsplit("/", 1)[-1] not in settings.protected_branches

    def test_empty_name_still_produces_a_usable_branch(self):
        branch = branch_for(4, "")
        assert branch.startswith(settings.branch_prefix)
        assert "//" not in branch.removeprefix(settings.branch_prefix)


class TestContainerNaming:
    def test_name_is_derived_from_the_session_id(self):
        assert container_name(12) != container_name(13)
        assert "12" in container_name(12)


class TestRequestValidation:
    def test_workspace_name_is_reduced_to_safe_characters(self):
        assert WorkspaceCreate(name="My Feature!").name == "my-feature-"

    def test_workspace_name_must_contain_something_usable(self):
        with pytest.raises(ValueError):
            WorkspaceCreate(name="   ---   ")

    def test_task_must_not_be_trivial(self):
        with pytest.raises(ValueError):
            SessionCreate(workspace_id=1, task="fix")

    def test_screenshot_paths_must_be_absolute_paths(self):
        with pytest.raises(ValueError):
            SessionCreate(
                workspace_id=1,
                task="a long enough task description",
                screenshot_paths=["https://example.com/evil"],
            )

    def test_protocol_relative_paths_are_refused(self):
        # "//evil.example" would resolve to another host once joined to the
        # dev base URL, taking the screenshot off-platform.
        with pytest.raises(ValueError):
            SessionCreate(
                workspace_id=1,
                task="a long enough task description",
                screenshot_paths=["//evil.example/page"],
            )

    def test_ordinary_paths_pass(self):
        body = SessionCreate(
            workspace_id=1,
            task="a long enough task description",
            screenshot_paths=["/dashboard", "/models"],
        )
        assert body.screenshot_paths == ["/dashboard", "/models"]


class TestLaunchAndSupervision:
    """What the manager decides to do with a container.

    These run against fakes of the Docker engine and the database, so they pin
    down the decisions — what gets bound into a session, what gets removed
    when a start fails, and how the wall-clock budget treats paused time —
    without needing a daemon.
    """

    SESSION = {
        "id": 7,
        "workspace_id": 1,
        "task": "a long enough task description",
        "model": None,
        "open_pull_request": False,
        "screenshot_paths": [],
    }
    WORKSPACE = {
        "id": 1,
        "name": "feature-work",
        "base_branch": "main",
        "volume_name": "logos-agent-ws-1",
    }

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    async def test_failed_launch_removes_its_container_and_binds_its_own_artifacts(self, monkeypatch, tmp_path):
        # A start that fails after the container exists must not leak it:
        # settlement removes the container by the id in the database, which is
        # still null at that point. And the artefact bind must be this
        # session's own directory on the host, not the shared volume.
        from app import sessions

        patched = replace(sessions.settings, artifact_root=str(tmp_path))
        monkeypatch.setattr(sessions, "settings", patched)
        created: dict = {}
        removed: list = []

        async def fake_create(**kwargs):
            created.update(kwargs)
            return "cid-7"

        async def fake_start(_cid):
            raise RuntimeError("start failed")

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "ensure_volume", noop)
        monkeypatch.setattr(
            sessions.docker_engine,
            "volume_mountpoint",
            self._async_value("/var/lib/docker/volumes/logos_agent_artifacts/_data"),
        )
        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", fake_start)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        monkeypatch.setattr(sessions.db, "get_workspace", self._async_value(self.WORKSPACE))
        monkeypatch.setattr(
            sessions.db, "get_session", self._async_value({"container_id": None, "deploy_to_dev": False})
        )
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", noop)

        await sessions.manager._launch(self.SESSION)

        assert removed == ["cid-7"]
        assert created["artifact_host_path"] == "/var/lib/docker/volumes/logos_agent_artifacts/_data/7"
        # Model traffic is pointed at the gateway, not at the orchestrator's
        # internal API: the session network must not reach the orchestrator.
        assert created["env"]["ANTHROPIC_BASE_URL"] == patched.session_model_url
        assert created["env"]["ANTHROPIC_BASE_URL"] != patched.orchestrator_url

    async def test_paused_time_does_not_count_towards_the_session_timeout(self, monkeypatch, tmp_path):
        # A session that yields while the platform is busy must not burn its
        # wall-clock budget standing by: the deadline is frozen for as long as
        # the container is paused, and enforced again once it runs.
        from app import sessions

        monkeypatch.setattr(
            sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path), session_timeout_s=1)
        )
        states = {"state": "paused"}
        stopped: list = []
        events: list = []

        async def fake_state(_cid):
            return states["state"], None

        async def fake_stop(cid, **_kwargs):
            stopped.append(cid)

        async def fake_remove(_cid, **_kwargs):
            return None

        async def fake_stream(_cid, **_kwargs):
            while True:
                await asyncio.sleep(3600)
                yield ""

        async def fake_event(_sid, _kind, payload):
            events.append(payload)

        monkeypatch.setattr(sessions.docker_engine, "container_state", fake_state)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", fake_stop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        monkeypatch.setattr(sessions.docker_engine, "stream_logs", fake_stream)
        monkeypatch.setattr(
            sessions.db, "get_session", self._async_value({"container_id": "cid-9", "deploy_to_dev": False})
        )
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)

        supervisor = asyncio.create_task(sessions.manager._supervise_session(9, "cid-9"))
        try:
            # Paused well past the one-second budget: standing by must not spend it.
            await asyncio.sleep(2.5)
            assert stopped == []
            assert not supervisor.done()

            # Back to work: the remaining budget now runs down and is enforced.
            states["state"] = "running"
            for _ in range(20):
                if stopped:
                    break
                await asyncio.sleep(0.25)
            assert stopped == ["cid-9"]
            await supervisor
        finally:
            if not supervisor.done():
                supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await supervisor

        assert any("exceeded" in str(payload.get("message", "")) for payload in events)
