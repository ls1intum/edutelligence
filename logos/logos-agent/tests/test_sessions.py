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

    async def test_a_settle_racing_the_cancel_loses_to_it(self, monkeypatch, tmp_path):
        # While the cancel's stop is in flight the supervisor can observe
        # the exit and settle it. The cancel must own the row before any
        # container I/O, so the settle's terminal transition loses and the
        # session ends CANCELLED — no succeeded event, no deploy, no
        # screenshots for a session the operator just cancelled.
        from app import sessions

        monkeypatch.setattr(
            sessions,
            "settings",
            replace(sessions.settings, artifact_root=str(tmp_path), deploy_enabled=True),
        )
        row = {
            "status": "running",
            "container_id": "cid-7",
            "deploy_to_dev": True,
            "branch_name": "agent/feature-work/session-7",
            "screenshot_paths": ["/dashboard"],
        }
        order: list = []
        removed: list = []
        dispatched: list = []
        events: list = []
        claimed: dict = {}

        async def fake_transition(sid, target, **_fields):
            order.append(("transition", target))
            # The atomic gate: the row moves once, to whatever claims it
            # first; every later transition loses.
            if sid in claimed:
                return False
            claimed[sid] = target
            return True

        async def fake_stop(_cid, **_kwargs):
            order.append("stop")
            # The supervisor settles the exit it observes while the stop is
            # in flight.
            await sessions.manager._settle(7, exit_code=0, error=None)

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        async def fake_dispatch(**kwargs):
            dispatched.append(kwargs)
            return "https://github.com/ls1intum/edutelligence/actions/runs/1"

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", self._async_value(row))
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "unpause_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", fake_stop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)

        moved = await sessions.manager.cancel(7)

        assert moved is True
        # The claim comes first: CANCELLED before the stop, and the
        # settle's SUCCEEDED attempt loses the race to it.
        assert order == [("transition", SessionStatus.CANCELLED), "stop", ("transition", SessionStatus.SUCCEEDED)]
        assert dispatched == []
        assert events == [(EventKind.STATUS, {"status": "cancelled"})]
        assert removed.count("cid-7") >= 1


class TestOverlappingAdmission:
    """Admission under overlapping scheduler passes.

    Every session creation schedules a pass, so passes overlap. The room
    must be computed from counts read inside the admission lock, after any
    earlier pass has launched its batch — otherwise each pass admits a full
    batch from the same stale snapshot and the parallel ceiling is exceeded.
    """

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    async def test_overlapping_passes_cannot_exceed_the_parallel_ceiling(self, monkeypatch, tmp_path):
        from app import capacity, sessions

        monkeypatch.setattr(
            sessions,
            "settings",
            replace(sessions.settings, artifact_root=str(tmp_path), max_parallel_sessions=2),
        )
        reading = capacity.Reading(load=0.0, busy_slots=0, total_slots=1, queue_total=0, ok=True)
        states = {sid: "queued" for sid in (1, 2, 3, 4)}
        queue = [{"id": sid, "workspace_id": sid} for sid in states]
        launched: list = []

        async def fake_in_status(status):
            # Always a fresh read, like the database: whatever is true now.
            return [{"id": sid, "workspace_id": sid} for sid, state in states.items() if state == status.value]

        async def fake_claim(limit):
            claimed = []
            while limit > 0 and queue:
                session = queue.pop(0)
                states[session["id"]] = "starting"
                claimed.append(session)
                limit -= 1
            return claimed

        async def fake_launch(_self, session):
            # Like the real launch, the row becomes running while the
            # admission lock is still held.
            await asyncio.sleep(0)
            states[session["id"]] = "running"
            launched.append(session["id"])

        async def fake_event(_sid, _kind, _payload):
            return None

        monkeypatch.setattr(sessions.capacity, "read_load", self._async_value(reading))
        monkeypatch.setattr(sessions.db, "sessions_in_status", fake_in_status)
        monkeypatch.setattr(sessions.db, "claim_queued_sessions", fake_claim)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.SessionManager, "_launch", fake_launch)

        await asyncio.gather(sessions.manager.scheduler_pass(), sessions.manager.scheduler_pass())

        # The ceiling is two: the second pass must see the first one's
        # launches and find no room, not admit another full batch.
        assert sorted(launched) == [1, 2]

    async def test_one_fresh_reading_admits_at_most_one_session(self, monkeypatch, tmp_path):
        # A single below-threshold reading must not claim every open slot:
        # a whole batch admitted at once would move a small fleet from zero
        # load to occupying (or queueing for) every loaded slot before the
        # next observation can notice. One fresh reading admits one
        # session; the rest wait for the next pass's own observation.
        from app import capacity, sessions

        monkeypatch.setattr(
            sessions,
            "settings",
            replace(sessions.settings, artifact_root=str(tmp_path), max_parallel_sessions=4),
        )
        reading = capacity.Reading(load=0.0, busy_slots=0, total_slots=1, queue_total=0, ok=True)
        states = {sid: "queued" for sid in (1, 2, 3, 4)}
        queue = [{"id": sid, "workspace_id": sid} for sid in states]
        launched: list = []

        async def fake_in_status(status):
            return [{"id": sid, "workspace_id": sid} for sid, state in states.items() if state == status.value]

        async def fake_claim(limit):
            claimed = []
            while limit > 0 and queue:
                session = queue.pop(0)
                states[session["id"]] = "starting"
                claimed.append(session)
                limit -= 1
            return claimed

        async def fake_launch(_self, session):
            # Like the real launch, the row becomes running while the
            # admission lock is still held.
            await asyncio.sleep(0)
            states[session["id"]] = "running"
            launched.append(session["id"])

        async def fake_event(_sid, _kind, _payload):
            return None

        monkeypatch.setattr(sessions.capacity, "read_load", self._async_value(reading))
        monkeypatch.setattr(sessions.db, "sessions_in_status", fake_in_status)
        monkeypatch.setattr(sessions.db, "claim_queued_sessions", fake_claim)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.SessionManager, "_launch", fake_launch)

        await sessions.manager.scheduler_pass()

        # One fresh reading, one admission: the other three stay queued for
        # the next pass's own capacity observation.
        assert launched == [1]
        assert [sid for sid, state in states.items() if state == "queued"] == [2, 3, 4]


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
        wait_calls: list = []

        async def fake_build_wait(_branch, **_kwargs):
            return "success", "build ended: success"

        async def fake_marker():
            order.append("marker")
            return 40

        async def fake_dispatch(**_kwargs):
            order.append("dispatch")
            return "https://github.com/ls1intum/edutelligence/actions/runs/41"

        async def fake_wait(**kwargs):
            order.append("wait")
            wait_calls.append(kwargs)
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
        monkeypatch.setattr(sessions.github, "latest_dev_deploy_run_id", fake_marker)
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
        # The marker is recorded before the dispatch — the run the dispatch
        # creates is the one that turns out newer than it.
        assert order == ["marker", "dispatch", "wait", "ready", "screenshot"]
        # The wait is handed the marker: it may settle only a run of the
        # deploy workflow newer than what existed before the dispatch, never
        # a deploy that predates it.
        assert wait_calls == [{"after_run_id": 40}]
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

        async def fake_marker():
            return 40

        async def fake_dispatch(**_kwargs):
            return "https://github.com/ls1intum/edutelligence/actions/runs/41"

        async def fake_wait(**_kwargs):
            return "timeout", "still running after 1200s"

        async def fake_create(**kwargs):
            created.append(kwargs)
            return "cid-shot"

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)
        monkeypatch.setattr(sessions.github, "latest_dev_deploy_run_id", fake_marker)
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

    async def test_concurrent_deploys_do_not_interleave_the_environment_sequence(self, monkeypatch, tmp_path):
        # The dev environment is shared by every session on the runner, so
        # the sequences that change it and then observe it — dispatch, wait
        # for the run that dispatch created, wait for the environment to
        # serve, take the photos — must not interleave across sessions: an
        # interleaved pair would each settle against the other's run and
        # photograph the other's revision.
        from app import sessions

        self._patch_base(monkeypatch, tmp_path, deploy_enabled=True)
        for sid in (7, 8):
            directory = tmp_path / str(sid)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "result.json").write_text(
                json.dumps({"pr_url": f"https://github.com/ls1intum/edutelligence/pull/{sid}"})
            )
        order: list = []

        async def fake_get_session(_sid):
            return {
                "container_id": "cid-x",
                "deploy_to_dev": True,
                "branch_name": "agent/feature-work/session",
                "screenshot_paths": ["/dashboard"],
            }

        async def fake_build_wait(_branch, **_kwargs):
            return "success", "build ended: success"

        async def fake_marker():
            return 40

        async def fake_dispatch(**_kwargs):
            order.append("dispatch")
            # Yield so the other settling session can run while this one is
            # inside the environment sequence — only the lock keeps it out.
            await asyncio.sleep(0)
            return "https://github.com/ls1intum/edutelligence/actions/runs/41"

        async def fake_wait(**_kwargs):
            order.append("wait")
            await asyncio.sleep(0)
            return "success", "run ended: success"

        async def fake_ready(_self):
            order.append("ready")
            await asyncio.sleep(0)
            return True

        async def fake_create(**_kwargs):
            order.append("screenshot")
            await asyncio.sleep(0)
            return "cid-shot"

        async def fake_transition(_sid, _target, **_fields):
            return True

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", fake_get_session)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", noop)
        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)
        monkeypatch.setattr(sessions.github, "latest_dev_deploy_run_id", fake_marker)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)
        monkeypatch.setattr(sessions.github, "wait_for_dev_deploy", fake_wait)
        monkeypatch.setattr(sessions.SessionManager, "_wait_dev_ready", fake_ready)
        monkeypatch.setattr(sessions.docker_engine, "create_screenshot_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", self._async_value(0))
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)

        await asyncio.gather(
            sessions.manager._settle(7, exit_code=0, error=None),
            sessions.manager._settle(8, exit_code=0, error=None),
        )

        # One dispatch-to-screenshot block per session, and the blocks do not
        # interleave: each sequence ran to completion before the next began.
        assert order == ["dispatch", "wait", "ready", "screenshot"] * 2

    async def test_screenshots_are_skipped_when_the_requested_deploy_did_not_land(self, monkeypatch, tmp_path):
        # The session asked for a deploy and it did not land (here: refused,
        # because no pull request was opened and no image of the branch
        # exists). The environment still serves the previous revision, so a
        # photo attributed to this session would document the old code.
        sessions = self._patch_base(monkeypatch, tmp_path, deploy_enabled=True)
        row = {**self.SESSION_ROW, "deploy_to_dev": True}
        events: list = []
        created: list = []

        async def fake_create(**kwargs):
            created.append(kwargs)
            return "cid-shot"

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def fake_dispatch(**kwargs):
            raise AssertionError("no image exists to dispatch a deploy of")

        async def fake_build_wait(_branch, **_kwargs):
            raise AssertionError("no image exists to wait for")

        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", self._async_value(row))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "create_screenshot_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)
        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)

        # No result file, hence no pull request: the deploy is refused and
        # the photos are skipped with it.
        await sessions.manager._settle(7, exit_code=0, error=None)

        assert created == []
        skipped = [p for k, p in events if k == EventKind.SCREENSHOT and p.get("status") == "skipped"]
        assert len(skipped) == 1
        assert "did not land" in skipped[0]["reason"]


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
        marker_at: list = []

        async def fake_build_wait(branch, **_kwargs):
            order.append(("build_wait", branch))
            return "success", "build ended: success"

        async def fake_marker():
            # Position in `order` when the marker is recorded: after the
            # build wait, before the dispatch entry exists.
            marker_at.append(len(order))
            return 40

        async def fake_dispatch(**kwargs):
            order.append(("dispatch", kwargs))
            dispatched.append(kwargs)
            return "https://github.com/ls1intum/edutelligence/actions/runs/41"

        async def fake_event(_sid, kind, payload):
            order.append((kind, payload))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.SESSION_ROW))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)
        monkeypatch.setattr(sessions.github, "latest_dev_deploy_run_id", fake_marker)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)

        await sessions.manager._settle(7, exit_code=0, error=None)

        # The dispatch receives the prebuilt image tag and nothing branch-derived:
        # the workflow runs on a fixed trusted ref, so the session's agent-editable
        # branch never reaches the dev host.
        assert dispatched == [{"image_tag": "pr-772"}]
        # The build wait happens first, then the pre-dispatch marker — the
        # marker must see the runs as they stood before this dispatch's own
        # run exists — and only then the dispatch; the dispatched event
        # records the tag the environment now serves.
        build_idx = order.index(("build_wait", "agent/feature-work/session-7"))
        dispatch_idx = next(i for i, item in enumerate(order) if item[0] == "dispatch")
        assert build_idx < marker_at[0] <= dispatch_idx
        deploy_events = [p for k, p in order if k == EventKind.DEPLOY and p.get("status") == "dispatched"]
        assert deploy_events == [
            {
                "status": "dispatched",
                "environment": "logos-dev",
                "url": "https://github.com/ls1intum/edutelligence/actions/runs/41",
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
    # What re-adoption must persist, and only as part of a successful
    # transition.
    META = {"container_id": "cid-x", "branch_name": branch_for(7, "feature-work")}

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

        async def fake_transition(sid, target, **fields):
            transitions.append((target, fields))
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

        # The id and branch ride on the transition that claims running — not
        # on a separate write — so the row can never carry them without also
        # being the owner of the container, and never on a terminal row.
        assert transitions == [(SessionStatus.RUNNING, self.META)]
        assert updated == []
        assert supervised == [(7, "cid-x")]
        # The matched container is not an orphan: it is supervised, not removed.
        assert removed == []

    async def test_a_recovered_row_is_not_requeried_after_its_own_transition(self, monkeypatch, tmp_path):
        # The status queries see the committed state, like the real database:
        # a STARTING row this reconciliation moves to RUNNING is in the
        # RUNNING result set by the time that status is queried. The
        # occupying rows must be snapshotted before any of the transitions
        # are committed — otherwise the recovered session's container is
        # already out of the live list when the second query returns the row,
        # and the active, supervised session is settled as vanished.
        sessions = self._patch_base(monkeypatch, tmp_path)
        states = {7: "starting"}
        transitions: list = []
        supervised: list = []
        settled: list = []

        async def fake_in_status(status):
            # A fresh read on every call, like the database: whatever has
            # been committed by now.
            return [self.STARTING_ROW] if states[7] == status.value else []

        async def fake_transition(sid, target, **fields):
            transitions.append((target, fields))
            # A validated transition, like the database: only legal edges,
            # and the row really moves, so a later query sees it there.
            if not can_transition(SessionStatus(states[sid]), target):
                return False
            states[sid] = target.value
            return True

        def fake_supervise(_self, sid, cid):
            supervised.append((sid, cid))

        async def fake_settle(_self, sid, **kwargs):
            settled.append((sid, kwargs))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([self.CONTAINER]))
        monkeypatch.setattr(sessions.db, "sessions_in_status", fake_in_status)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.SessionManager, "_supervise", fake_supervise)
        monkeypatch.setattr(sessions.SessionManager, "_settle", fake_settle)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)

        await sessions.manager._reconcile()

        # The recovered session is re-adopted and supervised — and not
        # settled again from the RUNNING query that, against the committed
        # state, also returns it with its container already popped.
        assert transitions == [(SessionStatus.RUNNING, self.META)]
        assert supervised == [(7, "cid-x")]
        assert settled == []
        assert states[7] == "running"

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

        async def fake_transition(sid, target, **fields):
            transitions.append((target, fields))
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

        assert updated == []
        # The id and branch ride on the normalizing transition; starting has
        # no edge to succeeded, so settlement's terminal transition is the
        # second.
        assert transitions[0] == (SessionStatus.RUNNING, self.META)
        assert [target for target, _ in transitions] == [SessionStatus.RUNNING, SessionStatus.SUCCEEDED]
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

        async def fake_transition(sid, target, **fields):
            transitions.append((target, fields))
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

        # The metadata rides on the normalizing transition; the second hop
        # to paused carries none.
        assert transitions == [(SessionStatus.RUNNING, self.META), (SessionStatus.PAUSED, {})]
        assert updated == []
        assert supervised == [(7, "cid-x")]

    async def test_created_container_from_a_starting_row_is_started_not_settled(self, monkeypatch, tmp_path):
        # The runner restarted between creating and starting the container.
        # Docker reports it 'created' with exit code 0 — settling that would
        # record a success for an agent that never ran. A 'starting' row
        # continues what the launch began: start the container and supervise
        # it.
        sessions = self._patch_base(monkeypatch, tmp_path)
        container = {**self.CONTAINER, "State": "created"}
        updated: list = []
        transitions: list = []
        started: list = []
        supervised: list = []
        settled: list = []

        async def fake_update(sid, **fields):
            updated.append((sid, fields))

        async def fake_transition(sid, target, **fields):
            transitions.append((target, fields))
            return True

        async def fake_start(cid):
            started.append(cid)

        def fake_supervise(_self, sid, cid):
            supervised.append((sid, cid))

        async def fake_settle(_self, sid, **kwargs):
            settled.append((sid, kwargs))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([container]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.STARTING: [self.STARTING_ROW]})
        monkeypatch.setattr(sessions.db, "update_session", fake_update)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.docker_engine, "start_container", fake_start)
        monkeypatch.setattr(sessions.SessionManager, "_supervise", fake_supervise)
        monkeypatch.setattr(sessions.SessionManager, "_settle", fake_settle)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)

        await sessions.manager._reconcile()

        # No settle: a created container has no exit, however green, and no
        # orphan removal: the container is put to work. The id and branch
        # ride on the transition that claims running.
        assert settled == []
        assert started == ["cid-x"]
        assert transitions == [(SessionStatus.RUNNING, self.META)]
        assert supervised == [(7, "cid-x")]
        assert updated == []

    async def test_created_container_with_an_occupying_row_is_failed_and_removed(self, monkeypatch, tmp_path):
        # The container id is only stored once the start succeeded, so a
        # running row with a created container is inconsistent: it is failed
        # with a visible reason and removed, never trusted to run the
        # session.
        sessions = self._patch_base(monkeypatch, tmp_path)
        container = {**self.CONTAINER, "State": "created"}
        running_row = {
            **self.STARTING_ROW,
            "container_id": "cid-x",
            "branch_name": "agent/feature-work/session-7",
        }
        transitions: list = []
        started: list = []
        removed: list = []
        events: list = []

        async def fake_transition(sid, target, **_fields):
            transitions.append(target)
            return True

        async def fake_start(cid):
            started.append(cid)

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([container]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.RUNNING: [running_row]})
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.docker_engine, "start_container", fake_start)
        monkeypatch.setattr(
            sessions.db,
            "get_session",
            self._async_value({**running_row, "deploy_to_dev": False, "screenshot_paths": []}),
        )
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)

        await sessions.manager._reconcile()

        assert started == []
        # Settled with an error: straight to FAILED from running, no
        # normalization through states the session never had.
        assert transitions == [SessionStatus.FAILED]
        assert removed == ["cid-x"]
        failed = [p for k, p in events if k == EventKind.STATUS]
        assert len(failed) == 1
        assert "never started" in failed[0]["error"]

    async def test_cancel_winning_re_adoption_stops_and_removes_the_container(self, monkeypatch, tmp_path):
        # A cancel that lands in the restart window moves the 'starting'
        # row to 'cancelled' before re-adoption's transition can claim it —
        # and, seeing no container id in the row yet, it stops nothing. The
        # transition must lose, and reconciliation must give the container
        # back by the id Docker told it about: no supervision, and no id
        # written into the now-terminal row.
        sessions = self._patch_base(monkeypatch, tmp_path)
        updated: list = []
        transitions: list = []
        supervised: list = []
        stopped: list = []
        removed: list = []

        async def fake_update(sid, **fields):
            updated.append((sid, fields))

        async def fake_transition(sid, target, **_fields):
            transitions.append(target)
            # The cancel claimed the row first: every reconciliation
            # transition loses.
            return False

        def fake_supervise(_self, sid, cid):
            supervised.append((sid, cid))

        async def fake_stop(cid, **_kwargs):
            stopped.append(cid)

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([self.CONTAINER]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.STARTING: [self.STARTING_ROW]})
        monkeypatch.setattr(sessions.db, "update_session", fake_update)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.SessionManager, "_supervise", fake_supervise)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", fake_stop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)

        await sessions.manager._reconcile()

        # One transition attempt, lost to the cancel — and the
        # credential-bearing container is given back: stopped and removed,
        # never supervised, and the row is left untouched.
        assert transitions == [SessionStatus.RUNNING]
        assert stopped == ["cid-x"]
        assert removed == ["cid-x"]
        assert supervised == []
        assert updated == []

    async def test_cancel_winning_re_adoption_of_a_started_created_container_stops_it(self, monkeypatch, tmp_path):
        # The same race on the created path: the container is started, then
        # the transition to running loses to a cancel that landed in the
        # restart window. The just-started, credential-bearing agent must be
        # stopped and removed, not supervised.
        sessions = self._patch_base(monkeypatch, tmp_path)
        container = {**self.CONTAINER, "State": "created"}
        transitions: list = []
        started: list = []
        supervised: list = []
        stopped: list = []
        removed: list = []

        async def fake_transition(sid, target, **_fields):
            transitions.append(target)
            return False

        async def fake_start(cid):
            started.append(cid)

        def fake_supervise(_self, sid, cid):
            supervised.append((sid, cid))

        async def fake_stop(cid, **_kwargs):
            stopped.append(cid)

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([container]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.STARTING: [self.STARTING_ROW]})
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.docker_engine, "start_container", fake_start)
        monkeypatch.setattr(sessions.SessionManager, "_supervise", fake_supervise)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", fake_stop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)

        await sessions.manager._reconcile()

        # Lost the race after the start: the agent is stopped and removed.
        assert started == ["cid-x"]
        assert transitions == [SessionStatus.RUNNING]
        assert stopped == ["cid-x"]
        assert removed == ["cid-x"]
        assert supervised == []
