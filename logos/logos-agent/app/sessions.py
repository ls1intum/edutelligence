"""Session lifecycle: start, supervise, pause, resume, finish.

One session is one agent run in one container. The manager here owns three
concerns that have to stay together to be correct:

1. **Admission.** Queued sessions start only while the platform has spare
   serving capacity (see :mod:`capacity`), and never more than the configured
   number in parallel.
2. **Yielding.** Running sessions are paused the moment user traffic needs the
   GPUs back, and resume when it does not. Pausing freezes the process tree,
   so a session resumes mid-task rather than starting over.
3. **Settlement.** When a container exits, its result file is read, the
   outcome recorded, a pull request and a dev deploy triggered if asked for,
   and the container removed.

The scheduler loop is a single task; per-session supervision runs as one task
each, so a slow session cannot hold up admission of the others.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from . import capacity, db, docker_engine, github
from .config import settings
from .schemas import EventKind, SessionStatus

logger = logging.getLogger(__name__)

# Container names must be unique and stable so a restarted service can find
# the container belonging to a session again.
_CONTAINER_PREFIX = "logos-agent-session-"

# Deliberately excludes "." and "/": a workspace name is one path segment of
# the branch, and allowing either would let a name like "a/../../main" walk out
# of the prefix. The API sanitises names on the way in as well; this is the
# check that has to hold even if that one is changed.
_BRANCH_SAFE = re.compile(r"[^a-zA-Z0-9_-]")


def container_name(session_id: int) -> str:
    return f"{_CONTAINER_PREFIX}{session_id}"


def branch_for(session_id: int, workspace_name: str) -> str:
    """The only branch a session is permitted to push.

    Derived from the session id rather than from anything the agent chooses,
    so two sessions can never collide and a session cannot aim its push at a
    protected branch.
    """
    safe_ws = _BRANCH_SAFE.sub("-", workspace_name)[:40].strip("-") or "workspace"
    return f"{settings.branch_prefix}{safe_ws}/session-{session_id}"


def artifact_dir(session_id: int) -> Path:
    return Path(settings.artifact_root) / str(session_id)


def _give_to_session_user(path: Path) -> None:
    """Hand a host-side artefact path to the unprivileged session user.

    This service runs as root and creates the directories; the containers
    that write into them (sessions and screenshot containers) do not. Without
    the handover a session cannot create its own output at all. A failure is
    logged, not fatal: on a development machine the service itself runs
    unprivileged and the chown cannot work there.
    """
    try:
        os.chown(path, settings.session_uid, settings.session_uid)
    except OSError as exc:
        logger.warning("could not hand %s to session uid %s: %s", path, settings.session_uid, exc)


class SessionManager:
    def __init__(self) -> None:
        self._supervisors: dict[int, asyncio.Task] = {}
        self._scheduler_task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        # Serialises admission so two scheduler passes cannot both decide there
        # is room for the last slot.
        self._admission_lock = asyncio.Lock()
        self._last_reading: capacity.Reading = capacity.UNKNOWN

    # --- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        await docker_engine.ensure_network(settings.session_network)
        await docker_engine.ensure_volume(settings.artifact_volume, labels={"logos.agent": "artifacts"})
        await self._reconcile()
        self._scheduler_task = asyncio.create_task(self._scheduler_loop(), name="agent-scheduler")

    async def stop(self) -> None:
        self._stopping.set()
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        for task in list(self._supervisors.values()):
            task.cancel()
        await db.dispose()

    async def _reconcile(self) -> None:
        """Re-attach to reality after a restart.

        Sessions the database believes are running may have exited while the
        service was down, and containers may exist for sessions that were
        cancelled. Both leave the UI lying, so both are fixed here.
        """
        live: dict[int, dict[str, Any]] = {}
        try:
            for container in await docker_engine.list_managed_containers():
                label = (container.get("Labels") or {}).get("logos.agent.session")
                if label and label.isdigit():
                    live[int(label)] = container
        except Exception as exc:
            logger.warning("could not list managed containers during reconcile: %s", exc)
            return

        for status in (SessionStatus.STARTING, SessionStatus.RUNNING, SessionStatus.PAUSED):
            for session in await db.sessions_in_status(status):
                sid = session["id"]
                container = live.pop(sid, None)
                if container is None:
                    await self._settle(sid, exit_code=None, error="container vanished during restart")
                    continue
                state = (container.get("State") or "").lower()
                if state in ("running", "paused"):
                    target = SessionStatus.PAUSED if state == "paused" else SessionStatus.RUNNING
                    if status != target:
                        await db.update_session(sid, status=target.value)
                    self._supervise(sid, container.get("Id", ""))
                else:
                    _, exit_code = await docker_engine.container_state(container.get("Id", ""))
                    await self._settle(sid, exit_code=exit_code, error=None)

        # Containers with no live session row: leftovers, remove them.
        for sid, container in live.items():
            logger.info("removing orphaned container for session %s", sid)
            await docker_engine.remove_container(container.get("Id", ""))

    # --- scheduling -------------------------------------------------------

    @property
    def last_reading(self) -> capacity.Reading:
        return self._last_reading

    async def _scheduler_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.scheduler_pass()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler pass failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=settings.scheduler_interval_s)
            except asyncio.TimeoutError:
                pass

    async def scheduler_pass(self) -> None:
        reading = await capacity.read_load()
        self._last_reading = reading

        running = await db.sessions_in_status(SessionStatus.RUNNING)
        paused = await db.sessions_in_status(SessionStatus.PAUSED)

        # 1. Give capacity back first. Yielding always takes precedence over
        #    admitting, so a burst of user traffic is never met by the runner
        #    starting another session in the same pass.
        should_pause, why = capacity.pause_decision(reading)
        if should_pause and running:
            for session in running:
                await self._pause(session, why)
            return

        # 2. Resume what was paused, oldest first.
        if paused:
            may_resume, why = capacity.resume_decision(reading)
            if may_resume:
                for session in paused:
                    await self._resume(session, why)
                    reading = await capacity.read_load()
                    self._last_reading = reading
                    if not capacity.resume_decision(reading)[0]:
                        break
            return  # resume before admitting anything new

        # 3. Admit queued work into whatever room is left.
        async with self._admission_lock:
            may_start, why = capacity.start_decision(reading, running=len(running), paused=len(paused))
            if not may_start:
                return
            room = settings.max_parallel_sessions - len(running) - len(paused)
            for session in await db.claim_queued_sessions(room):
                await db.add_event(session["id"], EventKind.CAPACITY, {"decision": "start", "reason": why})
                await self._launch(session)

    # --- transitions ------------------------------------------------------

    async def _pause(self, session: dict[str, Any], reason: str) -> None:
        sid, container_id = session["id"], session.get("container_id")
        if not container_id:
            return
        await docker_engine.pause_container(container_id)
        if await db.transition_session(sid, SessionStatus.PAUSED):
            await db.add_event(sid, EventKind.CAPACITY, {"decision": "pause", "reason": reason})
            logger.info("paused session %s: %s", sid, reason)

    async def _resume(self, session: dict[str, Any], reason: str) -> None:
        sid, container_id = session["id"], session.get("container_id")
        if not container_id:
            return
        await docker_engine.unpause_container(container_id)
        if await db.transition_session(sid, SessionStatus.RUNNING):
            await db.add_event(sid, EventKind.CAPACITY, {"decision": "resume", "reason": reason})
            logger.info("resumed session %s: %s", sid, reason)

    async def _launch(self, session: dict[str, Any]) -> None:
        sid = session["id"]
        workspace = await db.get_workspace(session["workspace_id"])
        if workspace is None:
            await self._settle(sid, exit_code=None, error="workspace disappeared")
            return

        branch = branch_for(sid, workspace["name"])
        if branch.rsplit("/", 1)[-1] in settings.protected_branches or not branch.startswith(settings.branch_prefix):
            # Cannot happen with the derivation above, but the check is cheap
            # and this is the one place where a bug would push to main.
            await self._settle(sid, exit_code=None, error=f"refusing branch '{branch}'")
            return

        container_id: str | None = None
        try:
            await docker_engine.ensure_volume(
                workspace["volume_name"], labels={"logos.agent.workspace": workspace["name"]}
            )
            # The per-session artefact directory, resolved to the host path of
            # the volume it lives in: the session sees exactly this directory
            # at /artifacts, never the shared volume around it.
            directory = artifact_dir(sid)
            directory.mkdir(parents=True, exist_ok=True)
            _give_to_session_user(directory)
            artifact_host_path = str(Path(await docker_engine.volume_mountpoint(settings.artifact_volume)) / str(sid))

            container_id = await docker_engine.create_session_container(
                name=container_name(sid),
                image=settings.workspace_image,
                env=self._session_env(session, workspace, branch),
                workspace_volume=workspace["volume_name"],
                artifact_host_path=artifact_host_path,
                session_id=sid,
            )
            await docker_engine.start_container(container_id)
        except Exception as exc:
            logger.exception("failed to launch session %s", sid)
            # Settlement removes the container by the id stored in the
            # database, which is still null on a failed start — remove the
            # created container here or it survives until a reconcile.
            if container_id:
                try:
                    await docker_engine.remove_container(container_id)
                except Exception:
                    logger.warning("could not remove container for session %s after failed launch", sid)
            await self._settle(sid, exit_code=None, error=f"launch failed: {exc}")
            return

        if not await db.transition_session(
            sid,
            SessionStatus.RUNNING,
            container_id=container_id,
            branch_name=branch,
            started_at=datetime.now(timezone.utc),
        ):
            # A cancel that raced the launch already moved the row out of
            # 'starting'. The session is no longer ours to run: stop and
            # remove the container we just started, and do nothing else — no
            # running event, no supervision, no settlement side effects.
            logger.warning("session %s was cancelled during launch; removing its container", sid)
            try:
                await docker_engine.stop_container(container_id, timeout_s=5)
                await docker_engine.remove_container(container_id)
            except Exception:
                logger.warning("could not remove the container of cancelled session %s", sid)
            return

        await db.add_event(sid, EventKind.STATUS, {"status": "running", "branch": branch})
        self._supervise(sid, container_id)

    def _session_env(self, session: dict[str, Any], workspace: dict[str, Any], branch: str) -> dict[str, str]:
        """The environment a session container runs with.

        Everything the agent needs to reach Logos, and nothing that would let
        it reach anything else: no workflow-scoped token, no production URL,
        no internal secret.
        """
        model = session.get("model") or settings.default_model
        env = {
            # The agent's model traffic goes to Logos itself, so it is
            # authenticated, policy-checked, and billed like any other caller.
            # It is pointed at the gateway, not at the orchestrator: the
            # session network must reach only the /v1 model surface, never
            # the orchestrator's full internal API.
            "ANTHROPIC_BASE_URL": settings.session_model_url,
            "ANTHROPIC_AUTH_TOKEN": settings.agent_api_key,
            "ANTHROPIC_API_KEY": "",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "LOGOS_SESSION_ID": str(session["id"]),
            "LOGOS_SESSION_TASK": session["task"],
            "LOGOS_SESSION_BRANCH": branch,
            "LOGOS_SESSION_BASE_BRANCH": workspace["base_branch"],
            "LOGOS_SESSION_OPEN_PR": "1" if session.get("open_pull_request") else "0",
            "LOGOS_REPO_URL": settings.repo_url,
            "LOGOS_REPO_SLUG": settings.repo_slug,
            # The bind source *is* this session's artefact directory, so
            # /artifacts is its output root; there is no per-session prefix
            # to get wrong.
            "LOGOS_ARTIFACT_DIR": "/artifacts",
        }
        if model:
            for key in (
                "ANTHROPIC_MODEL",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL",
                "ANTHROPIC_DEFAULT_OPUS_MODEL",
            ):
                env[key] = model
        if settings.session_github_token:
            env["GITHUB_TOKEN"] = settings.session_github_token
            env["GH_TOKEN"] = settings.session_github_token
        return env

    # --- supervision ------------------------------------------------------

    def _supervise(self, session_id: int, container_id: str) -> None:
        if session_id in self._supervisors and not self._supervisors[session_id].done():
            return
        task = asyncio.create_task(
            self._supervise_session(session_id, container_id), name=f"agent-session-{session_id}"
        )
        self._supervisors[session_id] = task
        task.add_done_callback(lambda _t: self._supervisors.pop(session_id, None))

    async def _supervise_session(self, session_id: int, container_id: str) -> None:
        """Follow a container to its end, persisting its output as it goes.

        Time spent paused does not count against the wall-clock budget: the
        deadline is extended by every paused interval, so a session that
        yields while the platform is busy resumes with the time it had,
        instead of being killed for the hours it spent standing by.
        """
        log_task = asyncio.create_task(self._collect_logs(session_id, container_id))
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + settings.session_timeout_s
            paused_since: float | None = None
            exit_code: int | None = None
            while True:
                now = loop.time()
                if paused_since is not None:
                    deadline += now - paused_since
                    paused_since = None
                remaining = deadline - now
                if remaining <= 0:
                    await db.add_event(
                        session_id,
                        EventKind.ERROR,
                        {"message": f"session exceeded {settings.session_timeout_s}s, stopping"},
                    )
                    await docker_engine.stop_container(container_id)
                    exit_code = -1
                    break
                state, code = await docker_engine.container_state(container_id)
                if state == "paused" and paused_since is None:
                    paused_since = now
                if state == "gone":
                    break
                if state == "exited":
                    exit_code = code
                    break
                # A paused container never exits; poll rather than block on
                # /wait so the pause/resume cycle stays observable.
                await asyncio.sleep(min(5.0, max(1.0, remaining)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("supervision of session %s failed", session_id)
            await self._settle(session_id, exit_code=None, error=str(exc))
            return
        finally:
            log_task.cancel()

        await self._settle(session_id, exit_code=exit_code, error=None)

    async def _collect_logs(self, session_id: int, container_id: str) -> None:
        """Persist the container's output as events so the UI can replay it."""
        try:
            batch: list[str] = []
            async for line in docker_engine.stream_logs(container_id, follow=True):
                batch.append(line)
                # Batching keeps a chatty agent from writing one row per line
                # while still surfacing progress within a couple of seconds.
                if len(batch) >= 20:
                    await db.add_event(session_id, EventKind.LOG, {"lines": batch})
                    batch = []
            if batch:
                await db.add_event(session_id, EventKind.LOG, {"lines": batch})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("log collection for session %s stopped: %s", session_id, exc)

    # --- settlement -------------------------------------------------------

    async def _settle(self, session_id: int, *, exit_code: int | None, error: str | None) -> None:
        """Record the outcome of a finished session and clean up after it."""
        result = self._read_result(session_id)
        succeeded = exit_code == 0 and not error

        fields: dict[str, Any] = {
            "finished_at": datetime.now(timezone.utc),
            "exit_code": exit_code,
        }
        if error:
            fields["error"] = error[:4000]
        elif result.get("error"):
            fields["error"] = str(result["error"])[:4000]
        for key in ("tokens_in", "tokens_out"):
            if isinstance(result.get(key), int):
                fields[key] = result[key]
        if isinstance(result.get("cost_eur"), (int, float)):
            fields["cost_eur"] = float(result["cost_eur"])
        if result.get("pr_url"):
            fields["pr_url"] = str(result["pr_url"])

        await db.transition_session(
            session_id,
            SessionStatus.SUCCEEDED if succeeded else SessionStatus.FAILED,
            **fields,
        )
        await db.add_event(
            session_id,
            EventKind.STATUS,
            {
                "status": "succeeded" if succeeded else "failed",
                "exit_code": exit_code,
                "error": fields.get("error"),
            },
        )

        if result.get("pr_url"):
            await db.add_event(session_id, EventKind.PULL_REQUEST, {"url": result["pr_url"]})

        deploy: str | None = None
        if succeeded:
            deploy = await self._maybe_deploy(session_id, result)

        # Give the container back before the post-deploy wait: a deploy can
        # take minutes, and the capacity a session holds is worth reclaiming
        # without waiting for its screenshots.
        await self._cleanup_container(session_id)

        if succeeded:
            await self._capture_screenshots(session_id, deploy)

    def _read_result(self, session_id: int) -> dict[str, Any]:
        """Read the result file the container writes before it exits.

        Missing or malformed output is not an error in itself: a session killed
        for taking too long never gets to write one, and the exit code already
        tells us what happened.
        """
        path = artifact_dir(session_id) / "result.json"
        try:
            if path.is_file():
                return json.loads(path.read_text())
        except Exception as exc:
            logger.warning("unreadable result file for session %s: %s", session_id, exc)
        return {}

    async def _maybe_deploy(self, session_id: int, result: dict[str, Any]) -> str | None:
        """Dispatch the dev deploy if the session asked for one.

        Returns what happened — ``"dispatched"``, ``"skipped"``, ``"failed"`` —
        or ``None`` when the session did not request a deploy. Callers that
        have to happen *after* the deploy (the screenshots) key off this.
        """
        session = await db.get_session(session_id)
        if not session or not session.get("deploy_to_dev"):
            return None
        if not settings.deploy_enabled:
            await db.add_event(
                session_id,
                EventKind.DEPLOY,
                {"status": "skipped", "reason": "deploys are disabled on this runner"},
            )
            return "skipped"
        try:
            # Dispatched from here, never from the container: the workflow-scoped
            # token stays in this service, and the workflow itself is pinned to
            # the dev environment.
            run_url = await github.dispatch_dev_deploy(ref=session.get("branch_name") or "main")
            await db.update_session(session_id, deployed_at=datetime.now(timezone.utc))
            await db.add_event(
                session_id,
                EventKind.DEPLOY,
                {"status": "dispatched", "environment": settings.allowed_environment, "url": run_url},
            )
            return "dispatched"
        except Exception as exc:
            logger.warning("dev deploy for session %s failed: %s", session_id, exc)
            await db.add_event(session_id, EventKind.DEPLOY, {"status": "failed", "error": str(exc)})
            return "failed"

    async def _capture_screenshots(self, session_id: int, deploy: str | None) -> None:
        """Capture the session's requested dev pages, after everything else.

        Running this in settlement — and only after a requested dev deploy has
        finished and the environment serves again — is what makes the photos
        show the revision the session just deployed. A session container would
        see the previous revision: it exits long before the deploy dispatch
        is even made.
        """
        session = await db.get_session(session_id)
        paths = (session or {}).get("screenshot_paths") or []
        if not paths:
            return

        if deploy == "dispatched":
            status, detail = await github.wait_for_dev_deploy((session or {}).get("branch_name") or "main")
            if status != "success":
                await db.add_event(
                    session_id,
                    EventKind.SCREENSHOT,
                    {"status": "skipped", "reason": f"dev deploy did not succeed ({status}): {detail}"},
                )
                return
            if not await self._wait_dev_ready():
                await db.add_event(
                    session_id,
                    EventKind.SCREENSHOT,
                    {"status": "skipped", "reason": "dev environment was not serving after the deploy"},
                )
                return

        for name in await self._take_screenshots(session_id, paths):
            await db.add_event(session_id, EventKind.SCREENSHOT, {"name": name})

    async def _wait_dev_ready(self, *, timeout_s: float = 5 * 60, poll_s: float = 5.0) -> bool:
        """Wait until the dev environment serves the freshly deployed revision.

        The deploy workflow ends as soon as compose has started the stack, so
        the first moments after it are a half-started deployment. Any answer
        from the dev host means the new revision is up and serving; whether
        the models behind it have finished loading is a matter of what the
        page shows, not of whether it is the new one.
        """
        url = settings.dev_base_url.rstrip("/") + "/"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while True:
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    response = await client.get(url)
                if response.status_code < 400:
                    return True
            except Exception:
                pass
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(poll_s)

    async def _take_screenshots(self, session_id: int, paths: list[str]) -> list[str]:
        """Render each requested page in its own one-shot container.

        One container per page keeps a single slow or hung page from burning
        the budget of the ones after it, and each container is removed as
        soon as it is done.
        """
        base = settings.dev_base_url.rstrip("/")
        directory = artifact_dir(session_id) / "screenshots"
        directory.mkdir(parents=True, exist_ok=True)
        _give_to_session_user(directory)
        artifact_host_path = str(
            Path(await docker_engine.volume_mountpoint(settings.artifact_volume)) / str(session_id)
        )

        taken: list[str] = []
        for index, path in enumerate(paths[:10]):
            name = f"{index:02d}-{re.sub(r'[^a-zA-Z0-9]+', '-', path).strip('-') or 'page'}.png"
            container_id: str | None = None
            try:
                container_id = await docker_engine.create_screenshot_container(
                    name=f"logos-agent-screenshot-{session_id}-{index}",
                    image=settings.workspace_image,
                    url=f"{base}{path}",
                    output_path=f"/artifacts/screenshots/{name}",
                    artifact_host_path=artifact_host_path,
                    session_id=session_id,
                )
                await docker_engine.start_container(container_id)
                exit_code = await docker_engine.wait_container(container_id, timeout_s=180)
                if exit_code == 0:
                    taken.append(name)
                else:
                    logger.warning("screenshot of %s%s failed (exit %s)", base, path, exit_code)
            except Exception as exc:
                logger.warning("screenshot of %s%s failed: %s", base, path, exc)
            finally:
                if container_id:
                    try:
                        await docker_engine.remove_container(container_id)
                    except Exception:
                        logger.warning("could not remove the screenshot container for session %s", session_id)
        return taken

    async def _cleanup_container(self, session_id: int) -> None:
        session = await db.get_session(session_id)
        container_id = (session or {}).get("container_id")
        if container_id:
            await docker_engine.remove_container(container_id)

    # --- operator actions -------------------------------------------------

    async def cancel(self, session_id: int) -> bool:
        session = await db.get_session(session_id)
        if session is None:
            return False
        status = SessionStatus(session["status"])
        if status in (SessionStatus.SUCCEEDED, SessionStatus.FAILED, SessionStatus.CANCELLED):
            return False

        container_id = session.get("container_id")
        if container_id:
            # Unpause first: a paused container cannot process the stop signal,
            # and Docker would otherwise wait out the full grace period.
            await docker_engine.unpause_container(container_id)
            await docker_engine.stop_container(container_id, timeout_s=5)

        moved = await db.transition_session(session_id, SessionStatus.CANCELLED, finished_at=datetime.now(timezone.utc))
        if moved:
            await db.add_event(session_id, EventKind.STATUS, {"status": "cancelled"})
            task = self._supervisors.pop(session_id, None)
            if task:
                task.cancel()
            if container_id:
                await docker_engine.remove_container(container_id)
        return moved


manager = SessionManager()
