"""Tests for the session state machine and the naming rules around it.

The branch derivation is security-relevant — it is what stops a session
pushing to a protected branch — so it is tested against hostile workspace
names, not just ordinary ones.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import replace

import pytest
from app.config import settings
from app.schemas import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    EventKind,
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
        monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)
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
        # The bind source *is* the session's output directory, so the session
        # writes into /artifacts itself — a per-session prefix here would put
        # its output one directory too deep.
        assert created["env"]["LOGOS_ARTIFACT_DIR"] == "/artifacts"

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

    async def test_a_cancel_racing_the_launch_stops_and_removes_the_container(self, monkeypatch, tmp_path):
        # If an operator cancels while the container is being created or
        # started, the row leaves 'starting' before the launch can claim
        # 'running'. The launch must give up the container it just started —
        # no running event, no supervision, no settlement, none of the
        # completion side effects that a live, credentialed container would
        # otherwise still be allowed to perform.
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)
        stopped: list = []
        removed: list = []
        events: list = []
        transitions: list = []

        async def fake_transition(sid, target, **fields):
            transitions.append(target)
            return False

        async def fake_stop(cid, **kwargs):
            stopped.append(cid)

        async def fake_remove(cid, **kwargs):
            removed.append(cid)

        async def fake_event(sid, kind, payload):
            events.append((kind, payload))

        async def fake_create(**kwargs):
            return "cid-7"

        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "ensure_volume", noop)
        monkeypatch.setattr(sessions.docker_engine, "volume_mountpoint", self._async_value("/vol/data"))
        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", fake_stop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        monkeypatch.setattr(sessions.db, "get_workspace", self._async_value(self.WORKSPACE))
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)

        await sessions.manager._launch(self.SESSION)

        assert stopped == ["cid-7"]
        assert removed == ["cid-7"]
        # One transition attempt (to running), and no settlement afterwards:
        # the row belongs to the cancel, not to this launch.
        assert transitions == [SessionStatus.RUNNING]
        assert events == []
        assert not sessions.manager._supervisors


class TestScreenshotOrchestration:
    """Where and when the requested dev pages get photographed.

    The screenshots must show the revision the session just deployed, so they
    are taken by the runner during settlement — after the deploy dispatch and
    only once the environment serves again — never from inside the session
    container, which exits before any of that happens.
    """

    SESSION_ROW = {
        "container_id": "cid-7",
        "deploy_to_dev": False,
        "branch_name": "agent/feature-work/session-7",
        "screenshot_paths": ["/dashboard", "/models"],
    }

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    def _patch_base(self, monkeypatch, tmp_path, *, deploy_enabled=False):
        from app import sessions

        monkeypatch.setattr(
            sessions,
            "settings",
            replace(sessions.settings, artifact_root=str(tmp_path), deploy_enabled=deploy_enabled),
        )
        monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)
        monkeypatch.setattr(sessions.docker_engine, "volume_mountpoint", self._async_value("/vol/data"))
        monkeypatch.setattr(sessions.db, "update_session", self._async_value(None))
        return sessions

    async def test_screenshots_are_captured_in_settlement_without_a_deploy(self, monkeypatch, tmp_path):
        from app import sessions

        self._patch_base(monkeypatch, tmp_path)
        created: list = []
        removed: list = []
        events: list = []

        async def fake_create(**kwargs):
            created.append(kwargs)
            return f"cid-shot-{len(created)}"

        async def fake_wait(_cid, **_kwargs):
            return 0

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        async def fake_start(_cid):
            return None

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        monkeypatch.setattr(sessions.docker_engine, "create_screenshot_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", fake_start)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", fake_wait)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.SESSION_ROW))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)

        await sessions.manager._settle(7, exit_code=0, error=None)

        base = sessions.settings.dev_base_url.rstrip("/")
        # One one-shot container per requested page, pointed at the session's
        # own artefact directory, and each removed afterwards.
        assert [c["url"] for c in created] == [f"{base}/dashboard", f"{base}/models"]
        assert [c["output_path"] for c in created] == [
            "/artifacts/screenshots/00-dashboard.png",
            "/artifacts/screenshots/01-models.png",
        ]
        assert all(c["artifact_host_path"] == "/vol/data/7" for c in created)
        assert removed == ["cid-7", "cid-shot-1", "cid-shot-2"]
        names = [p["name"] for k, p in events if k == EventKind.SCREENSHOT]
        assert names == ["00-dashboard.png", "01-models.png"]

    async def test_screenshots_wait_for_a_dispatched_deploy_to_finish(self, monkeypatch, tmp_path):
        from app import sessions

        self._patch_base(monkeypatch, tmp_path, deploy_enabled=True)
        row = {**self.SESSION_ROW, "deploy_to_dev": True, "screenshot_paths": ["/dashboard"]}
        result = tmp_path / "7"
        result.mkdir(parents=True, exist_ok=True)
        (result / "result.json").write_text(
            json.dumps({"pr_url": "https://github.com/ls1intum/edutelligence/pull/772"})
        )
        order: list = []
        created: list = []

        async def fake_build_wait(_branch, **_kwargs):
            return "success", "build ended: success"

        async def fake_dispatch(**_kwargs):
            order.append("dispatch")
            return "https://github.com/ls1intum/edutelligence/actions/runs/1"

        async def fake_wait(ref, **_kwargs):
            order.append("wait")
            return "success", "run ended: success"

        async def fake_ready(_self):
            order.append("ready")
            return True

        async def fake_create(**kwargs):
            order.append("screenshot")
            created.append(kwargs)
            return "cid-shot"

        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)
        monkeypatch.setattr(sessions.github, "wait_for_dev_deploy", fake_wait)
        monkeypatch.setattr(sessions.SessionManager, "_wait_dev_ready", fake_ready)
        monkeypatch.setattr(sessions.docker_engine, "create_screenshot_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", self._async_value(0))
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.db, "get_session", self._async_value(row))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", noop)

        await sessions.manager._settle(7, exit_code=0, error=None)

        # The strict point of this fix: the photo comes only after the deploy
        # has been dispatched, waited out, and the environment serves again.
        assert order == ["dispatch", "wait", "ready", "screenshot"]
        assert created[0]["url"].endswith("/dashboard")

    async def test_screenshots_are_skipped_when_the_deploy_does_not_succeed(self, monkeypatch, tmp_path):
        from app import sessions

        self._patch_base(monkeypatch, tmp_path, deploy_enabled=True)
        row = {**self.SESSION_ROW, "deploy_to_dev": True}
        result = tmp_path / "7"
        result.mkdir(parents=True, exist_ok=True)
        (result / "result.json").write_text(
            json.dumps({"pr_url": "https://github.com/ls1intum/edutelligence/pull/772"})
        )
        events: list = []
        created: list = []

        async def fake_build_wait(_branch, **_kwargs):
            return "success", "build ended: success"

        async def fake_dispatch(**_kwargs):
            return "https://github.com/ls1intum/edutelligence/actions/runs/1"

        async def fake_wait(_ref, **_kwargs):
            return "timeout", "still running after 1200s"

        async def fake_create(**kwargs):
            created.append(kwargs)
            return "cid-shot"

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)
        monkeypatch.setattr(sessions.github, "wait_for_dev_deploy", fake_wait)
        monkeypatch.setattr(sessions.docker_engine, "create_screenshot_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.db, "get_session", self._async_value(row))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)

        await sessions.manager._settle(7, exit_code=0, error=None)

        # A deploy that did not succeed means nothing was deployed; a photo
        # of the old revision would be worse than no photo.
        assert created == []
        skipped = [p for k, p in events if k == EventKind.SCREENSHOT and p.get("status") == "skipped"]
        assert len(skipped) == 1
        assert "did not succeed" in skipped[0]["reason"]


class TestSettlementRaceAndDeployTag:
    """Settlement against a lost transition, and the tag a deploy pulls.

    Two races the state machine has to lose cleanly: a cancel that reaches
    the terminal row before settlement does, and a dispatch that would pull
    ``latest`` — which still points at main — instead of the pull request
    build that actually contains the session's code.
    """

    SESSION_ROW = {
        "container_id": "cid-7",
        "deploy_to_dev": True,
        "branch_name": "agent/feature-work/session-7",
        "screenshot_paths": [],
    }

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    def _patch_base(self, monkeypatch, tmp_path):
        from app import sessions

        monkeypatch.setattr(
            sessions,
            "settings",
            replace(sessions.settings, artifact_root=str(tmp_path), deploy_enabled=True),
        )
        monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)
        monkeypatch.setattr(sessions.db, "update_session", self._async_value(None))
        return sessions

    def _write_result(self, tmp_path, **payload):
        directory = tmp_path / "7"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "result.json").write_text(json.dumps(payload))

    async def test_settlement_losing_to_a_cancel_runs_no_side_effects(self, monkeypatch, tmp_path):
        # An operator can cancel while restart reconciliation settles an
        # exited container. The cancel moves the row to CANCELLED first, so
        # the settlement's terminal transition returns False: it must still
        # remove the container, but must not emit a status event, dispatch a
        # deploy, or take screenshots for a session that is already final.
        sessions = self._patch_base(monkeypatch, tmp_path)
        self._write_result(tmp_path, pr_url="https://github.com/ls1intum/edutelligence/pull/772")
        removed: list = []
        events: list = []
        dispatched: list = []
        build_waits: list = []

        async def fake_transition(_sid, _target, **_fields):
            return False

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def fake_dispatch(**kwargs):
            dispatched.append(kwargs)
            return "https://github.com/ls1intum/edutelligence/actions/runs/1"

        async def fake_build_wait(branch, **_kwargs):
            build_waits.append(branch)
            return "success", "build ended: success"

        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.SESSION_ROW))
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)
        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)

        await sessions.manager._settle(7, exit_code=0, error=None)

        # The container is given back, but the row belongs to the cancel:
        # no succeeded/failed event, no deploy, no build wait — even though
        # the result file carries a pull request.
        assert removed == ["cid-7"]
        assert events == []
        assert dispatched == []
        assert build_waits == []

    async def test_deploy_waits_for_the_pr_build_and_uses_its_tag(self, monkeypatch, tmp_path):
        # The result carries the PR URL, so the deploy must wait for the
        # pr-<n> build to succeed and dispatch with exactly that tag — never
        # latest, which still points at main.
        sessions = self._patch_base(monkeypatch, tmp_path)
        self._write_result(tmp_path, pr_url="https://github.com/ls1intum/edutelligence/pull/772")
        order: list = []
        dispatched: list = []

        async def fake_build_wait(branch, **_kwargs):
            order.append(("build_wait", branch))
            return "success", "build ended: success"

        async def fake_dispatch(**kwargs):
            order.append(("dispatch", kwargs))
            dispatched.append(kwargs)
            return "https://github.com/ls1intum/edutelligence/actions/runs/1"

        async def fake_event(_sid, kind, payload):
            order.append((kind, payload))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.SESSION_ROW))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)

        await sessions.manager._settle(7, exit_code=0, error=None)

        assert dispatched == [{"ref": "agent/feature-work/session-7", "image_tag": "pr-772"}]
        # The build wait happens before the dispatch, and the dispatched
        # event records the tag the environment now serves.
        build_idx = order.index(("build_wait", "agent/feature-work/session-7"))
        dispatch_idx = next(i for i, item in enumerate(order) if item[0] == "dispatch")
        assert build_idx < dispatch_idx
        deploy_events = [p for k, p in order if k == EventKind.DEPLOY and p.get("status") == "dispatched"]
        assert deploy_events == [
            {
                "status": "dispatched",
                "environment": "logos-dev",
                "url": "https://github.com/ls1intum/edutelligence/actions/runs/1",
                "image_tag": "pr-772",
            }
        ]

    async def test_deploy_is_aborted_when_the_pr_build_fails(self, monkeypatch, tmp_path):
        # A build that failed (or never ran) means the session's code is not
        # in any image; dispatching would deploy the old revision, so the
        # deploy is recorded as failed and nothing is dispatched.
        sessions = self._patch_base(monkeypatch, tmp_path)
        self._write_result(tmp_path, pr_url="https://github.com/ls1intum/edutelligence/pull/772")
        dispatched: list = []
        events: list = []

        async def fake_build_wait(_branch, **_kwargs):
            return "failed", "build ended: failure"

        async def fake_dispatch(**kwargs):
            dispatched.append(kwargs)
            return "https://github.com/ls1intum/edutelligence/actions/runs/1"

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.SESSION_ROW))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)

        await sessions.manager._settle(7, exit_code=0, error=None)

        assert dispatched == []
        failed = [p for k, p in events if k == EventKind.DEPLOY and p.get("status") == "failed"]
        assert len(failed) == 1
        assert "image builds did not succeed" in failed[0]["error"]

    async def test_deploy_is_refused_when_the_session_opened_no_pull_request(self, monkeypatch, tmp_path):
        # The API allows deploy_to_dev without open_pull_request. Without a
        # pull request no image of the branch exists — the build workflow
        # only runs for PRs — and the only tags the registry carries are
        # main's. The deploy must be refused with a visible reason, never
        # silently dispatched against the stale latest images.
        sessions = self._patch_base(monkeypatch, tmp_path)
        # No result file: the session opened no pull request.
        events: list = []
        dispatched: list = []
        build_waits: list = []

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def fake_dispatch(**kwargs):
            dispatched.append(kwargs)
            return "https://github.com/ls1intum/edutelligence/actions/runs/1"

        async def fake_build_wait(branch, **_kwargs):
            build_waits.append(branch)
            return "success", "build ended: success"

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.SESSION_ROW))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)
        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)

        await sessions.manager._settle(7, exit_code=0, error=None)

        assert dispatched == []
        assert build_waits == []
        failed = [p for k, p in events if k == EventKind.DEPLOY and p.get("status") == "failed"]
        assert len(failed) == 1
        assert "no pull request" in failed[0]["error"]


class TestRestartReconciliation:
    """Re-attaching to containers that outran the database after a restart.

    The runner can restart after a container is created and started but
    before the RUNNING transition stores its id. Such a row must be
    re-adopted — container id and derived branch persisted into the row —
    and moved only through valid state transitions, so a cancel that landed
    in the restart window is never overwritten and the credential-bearing
    container is never left unmanaged.
    """

    STARTING_ROW = {
        "id": 7,
        "workspace_name": "feature-work",
        "container_id": None,
        "branch_name": None,
    }
    CONTAINER = {
        "Id": "cid-x",
        "Labels": {"logos.agent.session": "7", "logos.agent.managed": "true"},
        "State": "running",
    }

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    def _patch_base(self, monkeypatch, tmp_path):
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)
        return sessions

    def _patch_rows(self, monkeypatch, sessions, rows_by_status):
        async def fake_in_status(status):
            return rows_by_status.get(status, [])

        monkeypatch.setattr(sessions.db, "sessions_in_status", fake_in_status)

    async def test_running_container_is_readopted_into_a_starting_row(self, monkeypatch, tmp_path):
        # The row still says 'starting' and knows no container id: the runner
        # restarted between the container start and the RUNNING transition.
        # Reconciliation must persist the id and the derived branch, move the
        # row to running, and hand the container to a supervisor.
        sessions = self._patch_base(monkeypatch, tmp_path)
        updated: list = []
        transitions: list = []
        supervised: list = []
        removed: list = []

        async def fake_update(sid, **fields):
            updated.append((sid, fields))

        async def fake_transition(sid, target, **_fields):
            transitions.append(target)
            return True

        def fake_supervise(_self, sid, cid):
            supervised.append((sid, cid))

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([self.CONTAINER]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.STARTING: [self.STARTING_ROW]})
        monkeypatch.setattr(sessions.db, "update_session", fake_update)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.SessionManager, "_supervise", fake_supervise)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)

        await sessions.manager._reconcile()

        assert updated == [(7, {"container_id": "cid-x", "branch_name": branch_for(7, "feature-work")})]
        assert transitions == [SessionStatus.RUNNING]
        assert supervised == [(7, "cid-x")]
        # The matched container is not an orphan: it is supervised, not removed.
        assert removed == []

    async def test_exited_container_from_a_starting_row_settles_through_running(self, monkeypatch, tmp_path):
        # The container exited while the runner was down, but the row never
        # left 'starting' — a state with no direct edge to a terminal state.
        # Reconciliation must normalize it through running so settlement's
        # transition is valid, then settle it as succeeded and remove the
        # container by the id it just re-adopted.
        sessions = self._patch_base(monkeypatch, tmp_path)
        container = {**self.CONTAINER, "State": "exited"}
        updated: list = []
        transitions: list = []
        events: list = []
        removed: list = []

        async def fake_update(sid, **fields):
            updated.append((sid, fields))

        async def fake_transition(sid, target, **_fields):
            transitions.append(target)
            return True

        async def fake_state(_cid):
            return "exited", 0

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([container]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.STARTING: [self.STARTING_ROW]})
        monkeypatch.setattr(sessions.db, "update_session", fake_update)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(
            sessions.db,
            "get_session",
            # The row as it stands after the re-adoption above: the cleanup
            # below can only find the container because the id is in there.
            self._async_value(
                {**self.STARTING_ROW, "container_id": "cid-x", "deploy_to_dev": False, "screenshot_paths": []}
            ),
        )
        monkeypatch.setattr(sessions.docker_engine, "container_state", fake_state)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)

        await sessions.manager._reconcile()

        assert updated == [(7, {"container_id": "cid-x", "branch_name": branch_for(7, "feature-work")})]
        # starting has no edge to succeeded: the row is normalized through
        # running first, and settlement's terminal transition is the second.
        assert transitions == [SessionStatus.RUNNING, SessionStatus.SUCCEEDED]
        assert removed == ["cid-x"]
        assert events == [(EventKind.STATUS, {"status": "succeeded", "exit_code": 0, "error": None})]

    async def test_paused_container_from_a_starting_row_normalizes_through_running(self, monkeypatch, tmp_path):
        # The platform paused the container inside the start window, before
        # the row ever reached 'running'. starting -> paused is not an edge,
        # so the row takes the only path that is: a later resume still has a
        # valid edge to leave from.
        sessions = self._patch_base(monkeypatch, tmp_path)
        container = {**self.CONTAINER, "State": "paused"}
        updated: list = []
        transitions: list = []
        supervised: list = []

        async def fake_update(sid, **fields):
            updated.append((sid, fields))

        async def fake_transition(sid, target, **_fields):
            transitions.append(target)
            return True

        def fake_supervise(_self, sid, cid):
            supervised.append((sid, cid))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([container]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.STARTING: [self.STARTING_ROW]})
        monkeypatch.setattr(sessions.db, "update_session", fake_update)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.SessionManager, "_supervise", fake_supervise)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)

        await sessions.manager._reconcile()

        assert updated == [(7, {"container_id": "cid-x", "branch_name": branch_for(7, "feature-work")})]
        assert transitions == [SessionStatus.RUNNING, SessionStatus.PAUSED]
        assert supervised == [(7, "cid-x")]
