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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from . import capacity, controls, db, docker_engine, github, model_policy
from .config import REPLY_FILE, settings
from .schemas import EventKind, SessionStatus

logger = logging.getLogger(__name__)

# How long output may wait before it is written, and how much of it goes into
# one row. Half a second is below what a person notices between the agent
# printing a line and the line appearing; twenty lines keeps a burst from
# writing a row each.
LOG_FLUSH_S = 0.5
LOG_BATCH_LINES = 20
# How many lines may wait to be written before the reader is made to wait.
# Twenty flushes' worth: enough to absorb a burst, small enough that a
# runaway session cannot grow it into a memory problem.
LOG_QUEUE_MAX = 2000

# How long shutdown may spend freezing running sessions. Below the stop
# grace period the compose file gives this service, so the work finishes
# before Docker stops waiting.
STAND_DOWN_S = 20.0

# What the agent phase prints when it wants its spending known — the only
# channel it has, holding no credential and reaching nothing but the model
# gateway.
_USAGE_LINE = re.compile(r"^\[usage\]\s+in=(?P<tin>\d+)\s+out=(?P<tout>\d+)")

# Container names must be unique and stable so a restarted service can find
# the container belonging to a session again.
_CONTAINER_PREFIX = "logos-agent-session-"

# Deliberately excludes "." and "/": a workspace name is one path segment of
# the branch, and allowing either would let a name like "a/../../main" walk out
# of the prefix. The API sanitises names on the way in as well; this is the
# check that has to hold even if that one is changed.
_BRANCH_SAFE = re.compile(r"[^a-zA-Z0-9_-]")

# How long a cancel waits for an in-flight launch to settle. Long enough for
# a stopped helper container to be reaped, short enough that a wedged Docker
# call cannot hold the cancel API open.
_CANCEL_LAUNCH_WAIT_S = 60.0

# GitHub rejects a comment body longer than 65536 characters; the margin
# leaves room for the truncation note.
_MAX_REPLY_CHARS = 60000

# How often an undelivered answer is retried before it is left alone.
_MAX_REPLY_ATTEMPTS = 5

# How long a workspace the runner created must have existed before it may be
# swept away. It covers the gap between a session being queued into a fresh
# workspace and being claimed, in which neither is active yet.
_WORKSPACE_IDLE_GRACE = timedelta(minutes=10)


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


class _Helper:
    """One session's trusted helper container, while it is being run.

    The record exists before the create request is even awaited, so a
    cancel can never report success for a session whose credential-bearing
    container is about to exist. ``created`` is set when the create has
    settled — it returned an id, stored in ``container_id``, or raised,
    leaving it None. ``started`` is set when the start phase has resolved:
    the start returned or raised, or was skipped because a cancel landed
    during the create. Cancels wait on these in turn, so a stop always
    runs against a container whose state is known — never the 304 no-op of
    stopping something that is not running yet, and never for a container
    that has not been created at all.
    """

    def __init__(self) -> None:
        self.container_id: str | None = None
        self.created = asyncio.Event()
        self.started = asyncio.Event()


class _Launch:
    """One session's launch, from before its first await until it settles.

    The helper record above covers a container that is being created; this
    one covers the stretch *before* any container exists — resolving the
    workspace, ensuring its volume, resolving the artefact mountpoint. A
    cancel landing in there used to find nothing tracked at all, report a
    clean cancellation, and leave the resumed launch to run the
    credential-bearing prepare helper and start the agent anyway.

    So the launch registers itself synchronously before its first await.
    A cancel marks ``cancelled`` and waits for ``settled``; the launch
    checks the flag at every phase boundary — before the prepare helper,
    before creating the agent container, before starting it — and gives
    back whatever it had created. Cancellation is therefore observed by
    the launch itself rather than raced against its final transition.
    """

    def __init__(self) -> None:
        self.cancelled = False
        self.settled = asyncio.Event()


class SessionManager:
    def __init__(self) -> None:
        self._supervisors: dict[int, asyncio.Task] = {}
        # The trusted helper container per session (prepare, finalize), while
        # it is running. Unlike the supervisor task it survives restart
        # reconciliation, where the finalizer runs without a supervisor at
        # all — and a cancel must be able to reach the credential-bearing
        # helper on that path too, not just the one the supervisor is in.
        self._helpers: dict[int, _Helper] = {}
        # The launch in flight per session, from before its first await. A
        # cancel that lands before any container exists is observed here.
        self._launches: dict[int, _Launch] = {}
        self._scheduler_task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        # Serialises admission so two scheduler passes cannot both decide there
        # is room for the last slot.
        self._admission_lock = asyncio.Lock()
        # The dev environment is shared by every session on this runner, so
        # the sequence that changes it and then observes it — dispatch a
        # deploy, wait for the run the dispatch created, wait for the
        # environment to serve, take the screenshots — must not interleave
        # across sessions: an interleaved pair would each settle against the
        # other's run and photograph the other's revision.
        self._deploy_screenshot_lock = asyncio.Lock()
        self._last_reading: capacity.Reading = capacity.UNKNOWN
        # Set once the session image has been seen on this host.
        self._image_present = False

    # --- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        # The session network is internal: no external egress at all, so the
        # only peer an agent container can reach is the model gateway that
        # sits on the same network. The egress network exists for the
        # trusted helper containers (prepare, finalize, screenshots).
        await docker_engine.ensure_network(settings.session_network, internal=True)
        await docker_engine.ensure_network(settings.session_egress_network)
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
        await self._stand_down()
        for task in list(self._supervisors.values()):
            task.cancel()
        await db.dispose()

    async def _stand_down(self) -> None:
        """Freeze what is running before this process goes away.

        A deploy replaces the runner and the model gateway together, and a
        session left running keeps talking to a gateway that is being
        restarted underneath it — losing the turn it was in the middle of.
        Frozen first it loses nothing: the container survives the deploy
        (sessions are not part of the compose stack), the row stays paused,
        the new runner adopts it, and the scheduler resumes it as soon as
        there is capacity. Pausing is not cancelling; the work continues
        mid-task.

        Bounded by the grace period Docker gives us. Whatever cannot be
        frozen in time is left running, which is exactly what happened
        before this existed.
        """
        if not self._supervisors:
            # Nothing of ours is running: no session to freeze, and no
            # reason to ask a database that may be going away with us.
            return
        try:
            await asyncio.wait_for(self._freeze_running(), timeout=STAND_DOWN_S)
        except (TimeoutError, asyncio.TimeoutError):
            logger.warning("ran out of time pausing sessions; the rest keep running through the restart")
        except Exception as exc:
            # Shutdown continues whatever happens here. A session that could
            # not be frozen is a session that runs through the restart,
            # which is what it did before this existed.
            logger.warning("could not stand down cleanly: %s", exc)

    async def _freeze_running(self) -> None:
        running = await db.sessions_in_status(SessionStatus.RUNNING)
        if not running:
            return
        logger.info("standing down: pausing %s running session(s)", len(running))
        await asyncio.gather(
            *(self._pause(session, "the runner is restarting") for session in running),
            return_exceptions=True,
        )

    async def _reconcile(self) -> None:
        """Re-attach to reality after a restart.

        Sessions the database believes are running may have exited while the
        service was down, and containers may exist for sessions that were
        cancelled. Both leave the UI lying, so both are fixed here. A
        container that outran its row — the runner restarted between the
        container start and the RUNNING transition — is re-adopted: its id
        and derived branch are persisted into the row before supervision or
        settlement, so a later cancel or cleanup can still reach the
        credential-bearing agent.
        """
        live: dict[int, dict[str, Any]] = {}
        try:
            for container in await docker_engine.list_managed_containers():
                labels = container.get("Labels") or {}
                if labels.get("logos.agent.helper"):
                    # A transient prepare/finalize container: never the
                    # supervised session container. A restart mid-helper is
                    # the only way one survives this far, so remove it
                    # instead of re-adopting it as a session.
                    await docker_engine.remove_container(container.get("Id", ""))
                    continue
                label = labels.get("logos.agent.session")
                if label and label.isdigit():
                    live[int(label)] = container
        except Exception as exc:
            logger.warning("could not list managed containers during reconcile: %s", exc)
            return

        # Snapshot the occupying rows before committing any of the
        # transitions: the status queries must see the state as it was at
        # startup, not the state this reconciliation writes. A STARTING row
        # that is normalized to RUNNING here would otherwise be returned by
        # the RUNNING query again — its container is already out of ``live``
        # by then, and the recovered session would be settled as vanished
        # while its supervisor keeps running it.
        occupying: list[tuple[SessionStatus, dict[str, Any]]] = []
        for status in (SessionStatus.STARTING, SessionStatus.RUNNING, SessionStatus.PAUSED, SessionStatus.FINALIZING):
            for session in await db.sessions_in_status(status):
                occupying.append((status, session))

        for status, session in occupying:
            sid = session["id"]
            container = live.pop(sid, None)
            if container is None:
                if status is SessionStatus.FINALIZING:
                    # The agent already exited cleanly — finalizing is only
                    # ever claimed on a clean exit — and the restart killed
                    # the first finalizer (its container is swept above by
                    # the helper label). The working copy is intact on the
                    # volume, and the finalizer is idempotent, so settling
                    # through a fresh run either completes the push or
                    # records a real failure; settling it as a vanished
                    # container instead would fail sessions whose work had
                    # in fact landed.
                    await self._settle(sid, exit_code=0, error=None)
                else:
                    await self._settle(sid, exit_code=None, error="container vanished during restart")
                continue
            container_id = container.get("Id", "")
            # Re-adopt the container's identity into the row, but by the
            # same atomic move that claims the state: the id and the
            # derived branch are stored as fields of the transition, so
            # a cancel that lands in the restart window either wins
            # before the id is stored (the transition then loses, and
            # the container is given back below by the id Docker told us
            # about) or reads the stored id and stops it itself. Neither
            # an id written into a terminal row nor a supervisor on a
            # row that is no longer ours is acceptable for a
            # credential-bearing agent.
            fields: dict[str, Any] = {}
            if session.get("container_id") != container_id:
                fields["container_id"] = container_id
            if not session.get("branch_name"):
                fields["branch_name"] = branch_for(sid, session["workspace_name"])
            state = (container.get("State") or "").lower()
            if state == "created":
                # The runner restarted between creating and starting the
                # container: the agent never ran, so there is no exit to
                # settle — settling it would record a success for work
                # that never happened. A 'starting' row continues what
                # the launch began; any other row is inconsistent (the id
                # is only stored once the start succeeded) and is failed
                # instead of trusted.
                if status is SessionStatus.STARTING:
                    try:
                        await docker_engine.start_container(container_id)
                    except Exception as exc:
                        await self._settle(sid, exit_code=None, error=f"could not start recovered container: {exc}")
                        # The start failed before the transition below,
                        # so the id is not in the row and settlement's
                        # cleanup cannot reach the container; remove it
                        # by the id Docker told us about.
                        await self._relinquish_container(container_id)
                    else:
                        if not await db.transition_session(sid, SessionStatus.RUNNING, **fields):
                            # A cancel that landed in the restart window
                            # owns the row; the agent must not keep
                            # running.
                            await self._relinquish_container(container_id)
                        else:
                            self._supervise(sid, container_id)
                else:
                    await self._settle(sid, exit_code=None, error="container was created but never started")
                continue
            if state in ("running", "paused"):
                target = SessionStatus.PAUSED if state == "paused" else SessionStatus.RUNNING
                if status is SessionStatus.STARTING and target is SessionStatus.PAUSED:
                    # starting -> paused is not an edge: a container the
                    # platform paused inside the start window normalizes
                    # through running first.
                    if not await db.transition_session(sid, SessionStatus.RUNNING, **fields):
                        await self._relinquish_container(container_id)
                        continue
                    fields = {}
                    if not await db.transition_session(sid, SessionStatus.PAUSED):
                        await self._relinquish_container(container_id)
                        continue
                elif status != target:
                    # A validated transition, not a raw update: a cancel
                    # that landed inside the restart window must not be
                    # overwritten with running/paused.
                    if not await db.transition_session(sid, target, **fields):
                        await self._relinquish_container(container_id)
                        continue
                self._supervise(sid, container_id)
            else:
                if status is SessionStatus.STARTING:
                    # An exited container found while the row is still
                    # 'starting' has no direct edge to a terminal state;
                    # normalize through running so settlement's
                    # transition is valid and can record the outcome.
                    if not await db.transition_session(sid, SessionStatus.RUNNING, **fields):
                        # A cancel that landed in the restart window owns
                        # the row and saw no container id yet; the
                        # exited container is removed here, by the id
                        # Docker told us about.
                        await self._relinquish_container(container_id)
                        continue
                    fields = {}
                # A finalizing row can also land here (the exited agent
                # container survives the restart until cleanup): settlement
                # re-runs the idempotent finalizer and settles from the
                # finalizing edge.
                _, exit_code = await docker_engine.container_state(container_id)
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
                # Answers that did not reach GitHub when their session
                # settled. Beside the pass rather than inside it: a pass is
                # about admitting and yielding, and every session creation
                # schedules one of those.
                await self.deliver_pending_replies()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("retrying undelivered answers failed")
            try:
                await self.sweep_workspaces()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("removing finished workspaces failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=settings.scheduler_interval_s)
            except asyncio.TimeoutError:
                pass

    async def scheduler_pass(self) -> None:
        # Measured on the lane these sessions are served by, not on the
        # whole fleet: an embedding model being idle says nothing about
        # whether another agent session is safe to start.
        reading = await capacity.read_load(models=model_policy.current().local_models)
        self._last_reading = reading
        # What an operator has asked for right now — the kill switch and the
        # ceiling they set — read before anything is decided.
        control = await controls.current()

        running = await db.sessions_in_status(SessionStatus.RUNNING)
        paused = await db.sessions_in_status(SessionStatus.PAUSED)

        if control.paused:
            # The hard half of the kill switch: hand the platform back
            # everything the runner holds. Paused, not cancelled — the work
            # survives, and releasing the switch resumes it mid-task.
            # Draining is the other half and deliberately does none of this:
            # it lets what is running finish and only stops admission.
            for session in running:
                await self._pause(session, control.admission_block())
            return

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
            if may_resume and not control.may_resume():
                may_resume, why = False, control.admission_block()
            if may_resume:
                # Room is counted per session, not once for the batch: with
                # four paused sessions and a ceiling of two, checking only
                # before the loop would resume all four and put the runner
                # over the ceiling an operator just set.
                live = len(running)
                for session in paused:
                    if live >= control.max_parallel:
                        logger.info(
                            "not resuming session %s: %s sessions is the ceiling in force",
                            session["id"],
                            control.max_parallel,
                        )
                        break
                    await self._resume(session, why)
                    live += 1
                    reading = await capacity.read_load(models=model_policy.current().local_models)
                    self._last_reading = reading
                    if not capacity.resume_decision(reading)[0]:
                        break
            return  # resume before admitting anything new

        # 3. Admit queued work — at most one session per fresh capacity
        #    reading, taken *inside* the admission lock. A session creation
        #    schedules a pass of its own, so passes overlap: one that
        #    sampled the load before an earlier pass's launch would admit
        #    against a reading the launch predates, and a burst of
        #    creation-triggered passes could each claim one session from
        #    the same pre-launch sample until the ceiling is full without a
        #    single observation made after any of the launches. Re-reading
        #    under the lock makes every claim pay for its own observation;
        #    the backlog drains at one fresh reading per admission.
        async with self._admission_lock:
            reading = await capacity.read_load(models=model_policy.current().local_models)
            self._last_reading = reading
            # Permissions are data: the agent key can be granted a cloud
            # provider long after this service started, so the local-only
            # policy is re-established on the pass that would spend it, not
            # once at startup.
            policy = await model_policy.refresh()
            if not policy.ok:
                return
            running = await db.sessions_in_status(SessionStatus.RUNNING)
            paused = await db.sessions_in_status(SessionStatus.PAUSED)
            blocked = control.admission_block()
            if blocked:
                # Draining, paused, or a ceiling of zero: nothing new starts.
                return
            may_start, why = capacity.start_decision(
                reading,
                running=len(running),
                paused=len(paused),
                max_parallel=control.max_parallel,
            )
            if not may_start:
                return
            claimed = await db.claim_queued_sessions(1)
            # The claim is what makes these rows this pass's to launch, so
            # the launch record is taken here rather than inside _launch:
            # the event write below is an await, and a cancel landing in it
            # would otherwise find nothing tracked, report success, and be
            # overtaken by a launch that never learned of it. Registration
            # is synchronous, so nothing runs between the claim and it.
            for session in claimed:
                self._register_launch(session["id"])
            for session in claimed:
                await db.add_event(session["id"], EventKind.CAPACITY, {"decision": "start", "reason": why})
                await self._launch(session)

    # --- transitions ------------------------------------------------------

    async def _pause(self, session: dict[str, Any], reason: str) -> None:
        sid, container_id = session["id"], session.get("container_id")
        if not container_id:
            return
        if not await docker_engine.pause_container(container_id):
            # Docker had nothing to freeze: the agent exited between the
            # scheduler's reading and this call. Leaving the row alone is
            # what lets its supervisor settle the exit — a row moved to
            # 'paused' around a container that is gone can never reach a
            # terminal state and would sit there until someone cancels it.
            logger.info("session %s could not be paused; its container is not running", sid)
            return
        # Freezing stops the agent, not the generation it already started:
        # that request runs on upstream capacity, and a frozen client neither
        # cancels it nor closes its socket. Cutting the container off the
        # session network ends the connection, so the slot this pause is
        # meant to return is actually returned. The agent sees a network
        # error on resume and retries, which is the cheapest possible way to
        # lose an in-flight answer.
        await self._detach_from_model_gateway(sid, container_id)
        if await db.transition_session(sid, SessionStatus.PAUSED):
            await db.add_event(sid, EventKind.CAPACITY, {"decision": "pause", "reason": reason})
            logger.info("paused session %s: %s", sid, reason)

    async def _detach_from_model_gateway(self, session_id: int, container_id: str) -> None:
        try:
            await docker_engine.disconnect_network(settings.session_network, container_id)
        except Exception as exc:
            # Not fatal: the session is frozen either way, and the slot is
            # released when the upstream request finishes on its own.
            logger.warning("could not detach paused session %s from the session network: %s", session_id, exc)

    async def _resume(self, session: dict[str, Any], reason: str) -> None:
        sid, container_id = session["id"], session.get("container_id")
        if not container_id:
            return
        # Attach first: a session thawed without its network would fail on
        # its next model call, which is worse than staying paused one more
        # tick.
        try:
            attached = await docker_engine.connect_network(settings.session_network, container_id)
        except Exception as exc:
            logger.error("could not reattach session %s to the session network: %s", sid, exc)
            return
        if not attached:
            logger.error("session %s could not be reattached to the session network; leaving it paused", sid)
            return
        if not await docker_engine.unpause_container(container_id):
            logger.info("session %s could not be resumed; its container is not running", sid)
            return
        if await db.transition_session(sid, SessionStatus.RUNNING):
            await db.add_event(sid, EventKind.CAPACITY, {"decision": "resume", "reason": reason})
            logger.info("resumed session %s: %s", sid, reason)

    def _register_launch(self, session_id: int) -> _Launch:
        """Take (or find) the launch record for a session.

        Idempotent, and deliberately never replaces an existing record: a
        cancel that already marked one must not be forgotten by a launch
        that starts afterwards. Synchronous, so a caller can claim a row and
        register its launch with no await in between.
        """
        launch = self._launches.get(session_id)
        if launch is None:
            launch = _Launch()
            self._launches[session_id] = launch
        return launch

    async def _launch(self, session: dict[str, Any]) -> None:
        sid = session["id"]
        # Registered before the first await, so a cancel arriving during the
        # workspace and volume lookups below is seen by this launch rather
        # than by nothing at all. The scheduler registers it earlier still,
        # at the moment it claims the row.
        launch = self._register_launch(sid)
        try:
            if launch.cancelled:
                # Cancelled between the claim and here: the row is already
                # terminal and nothing of this session may start.
                logger.info("session %s was cancelled before its launch began", sid)
                return
            await self._launch_tracked(session, launch)
        finally:
            # Whatever happened — success, failure, or an observed cancel —
            # the launch is over, and a cancel waiting on it may proceed.
            self._launches.pop(sid, None)
            launch.settled.set()

    async def _launch_tracked(self, session: dict[str, Any], launch: _Launch) -> None:
        sid = session["id"]
        workspace = await db.get_workspace(session["workspace_id"])
        if workspace is None:
            await self._settle(sid, exit_code=None, error="workspace disappeared")
            return

        # A session queued against an existing branch — a review answered, or
        # a pull request handed over — carries it on the row and keeps that
        # name: renaming somebody's branch would abandon the pull request it
        # belongs to. Everything else gets the branch derived from the
        # session id, under the runner's own prefix.
        taken_over = str(session.get("branch_name") or "")
        branch = taken_over or branch_for(sid, workspace["name"])
        if branch in settings.protected_branches or branch.rsplit("/", 1)[-1] in settings.protected_branches:
            # This is the one place where a bug would push to main.
            await self._settle(sid, exit_code=None, error=f"refusing branch '{branch}'")
            return
        if not taken_over and not branch.startswith(settings.branch_prefix):
            # The prefix binds branches the runner creates; it says nothing
            # about one it was handed.
            await self._settle(sid, exit_code=None, error=f"refusing branch '{branch}'")
            return

        # The image every phase of this session runs. It is published by the
        # build of the default branch, so a deployment can be a few minutes
        # ahead of its registry — and a session that dies with a bare
        # `404: No such image` looks like a broken runner rather than an
        # artefact that is not there yet.
        if not await self._workspace_image_present():
            await self._settle(
                sid,
                exit_code=None,
                error=(
                    f"the session image '{settings.workspace_image}' is not available on this host. "
                    f"It is published by the build of the default branch — wait for that build, or "
                    f"pull the image — and queue the session again."
                ),
            )
            return

        # The model is checked again here, against the policy this pass
        # established: a session queued while its model was local must not
        # start after that model gained a cloud deployment. This is the last
        # point before a container is given the gateway's address.
        policy = model_policy.current()
        if not policy.allows(session.get("model")):
            await self._settle(sid, exit_code=None, error=policy.refusal(session.get("model")))
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

            # Boundary: the next step hands a GitHub token to a container.
            # A cancel that arrived during the awaits above has already
            # reported the session cancelled, so nothing credential-bearing
            # may start for it. The row is re-read as well as the flag
            # checked: the flag covers a cancel this process saw, the row
            # covers everything else — another replica, a manual database
            # change, or any await added between the claim and here in the
            # future.
            if launch.cancelled or not await self._still_ours(sid):
                logger.info("session %s is no longer ours to launch; not starting its checkout helper", sid)
                return

            # Phase one, trusted: the working copy is prepared by a helper
            # container with egress and the scoped push token. The agent
            # phase that follows has neither — it runs on the internal
            # network with no credentials at all.
            await self._prepare_checkout(session, workspace, branch, artifact_host_path)

            # Boundary: the agent container is next. A cancel during the
            # prepare helper stops that helper; the launch must not go on to
            # start the agent for a session the API reported cancelled.
            if launch.cancelled:
                logger.info("session %s was cancelled during checkout preparation; not starting the agent", sid)
                return

            container_id = await docker_engine.create_session_container(
                name=container_name(sid),
                image=settings.workspace_image,
                env=self._session_env(session, branch),
                workspace_volume=workspace["volume_name"],
                artifact_host_path=artifact_host_path,
                session_id=sid,
            )
            # Boundary: the container exists but has not run. Give it back
            # rather than starting an agent for a cancelled session.
            if launch.cancelled:
                logger.info("session %s was cancelled before its agent started; removing its container", sid)
                await self._relinquish_container(container_id)
                return
            await docker_engine.start_container(container_id)
        except Exception as exc:
            if launch.cancelled:
                # The failure is the cancellation working: the helper was
                # stopped under the launch. The row is already terminal, so
                # settling it again would only record a spurious error.
                logger.info("launch of cancelled session %s ended: %s", sid, exc)
                if container_id:
                    await self._relinquish_container(container_id)
                return
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

        if launch.cancelled:
            # The cancel landed between the start and the transition below.
            # The transition would lose anyway, but stopping here keeps the
            # started container from living until that check.
            logger.info("session %s was cancelled as its agent started; removing its container", sid)
            await self._relinquish_container(container_id)
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
        # The queue acknowledged the request; this says it is being worked
        # on now — the difference a person on the other end of a comment
        # actually wants to know.
        await self._react(session, github.REACTION_RUNNING)

    async def _workspace_image_present(self) -> bool:
        """Whether the session image is on this host, remembered once it is.

        Checked per launch until it succeeds: an image does not vanish, so
        one positive answer stands for the life of the process, while a
        negative one is worth re-asking every time — that is the state that
        changes when the registry catches up.
        """
        if self._image_present:
            return True
        try:
            self._image_present = await docker_engine.image_present(settings.workspace_image)
        except Exception as exc:
            logger.warning("could not check for the session image: %s", exc)
            return True  # let the launch try and report the real error
        return self._image_present

    async def _still_ours(self, session_id: int) -> bool:
        """Whether the row is still the 'starting' one this launch claimed."""
        return await db.session_is_starting(session_id)

    def _session_env(self, session: dict[str, Any], branch: str) -> dict[str, str]:
        """The environment the untrusted agent phase runs with.

        Nothing reusable: no GitHub token (the helper phases do the
        authenticated work), no model credential (the gateway injects it —
        the placeholder only keeps the CLI from refusing to start without a
        token). No workflow scope, no production URL, no internal secret.
        """
        # The policy resolves what "no model named" means — the configured
        # default, or the single local model of a one-model deployment — and
        # it has already refused anything that is not served locally.
        model = model_policy.current().resolve(session.get("model"))
        env = {
            "LOGOS_SESSION_PHASE": "agent",
            # The agent's model traffic goes to Logos itself, so it is
            # authenticated, policy-checked, and billed like any other
            # caller. It is pointed at the gateway, not at the orchestrator:
            # the internal session network reaches only the gateway, and the
            # gateway replaces whatever credential the container sends with
            # the real one — the container holds none.
            "ANTHROPIC_BASE_URL": settings.session_model_url,
            "ANTHROPIC_AUTH_TOKEN": "injected-by-logos-agent-gateway",
            "ANTHROPIC_API_KEY": "",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "LOGOS_SESSION_ID": str(session["id"]),
            "LOGOS_SESSION_TASK": session["task"],
            "LOGOS_SESSION_BRANCH": branch,
            # The bind source *is* this session's artefact directory, so
            # /artifacts is its output root; there is no per-session prefix
            # to get wrong.
            "LOGOS_ARTIFACT_DIR": "/artifacts",
            # Where an answer goes when the session was asked something. The
            # task text names the same file; this is what makes it available
            # to anything else in the container that wants it.
            "LOGOS_SESSION_REPLY_FILE": f"/artifacts/{REPLY_FILE}",
        }
        if model:
            for key in (
                "ANTHROPIC_MODEL",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL",
                "ANTHROPIC_DEFAULT_OPUS_MODEL",
            ):
                env[key] = model
        return env

    async def _run_helper(
        self,
        *,
        phase: str,
        session_id: int,
        env: dict[str, str],
        workspace_volume: str,
        artifact_host_path: str,
    ) -> int | None:
        """Run one trusted one-shot helper container to completion, remove it.

        The helper phases (checkout preparation, finalization) are
        runner-owned containers, never supervised sessions: a fixed
        entrypoint, a short budget, and the exit code is the whole protocol.
        They run on the egress network, the one network a container with
        credentials is allowed to have.
        """
        # Tracked before the create is even awaited: a cancel that lands
        # while the create request is in flight must find the record here
        # and wait for it — not report a clean cancellation for a helper
        # that is about to hold the credential. The assignment is
        # synchronous, so no other coroutine can run between the
        # registration and the create that follows it.
        helper = _Helper()
        self._helpers[session_id] = helper
        try:
            try:
                container_id = await docker_engine.create_session_container(
                    name=f"logos-agent-{phase}-{session_id}",
                    image=settings.workspace_image,
                    env=env,
                    workspace_volume=workspace_volume,
                    artifact_host_path=artifact_host_path,
                    session_id=session_id,
                    network=settings.session_egress_network,
                    labels={"logos.agent.helper": phase},
                )
                helper.container_id = container_id
            finally:
                # The create has settled: from here on the container either
                # exists, with its id stored in the record, or it does not
                # because the create raised.
                helper.created.set()
            if self._helpers.get(session_id) is not helper:
                # A cancel landed while the create was in flight: it has
                # popped the record and is waiting for the container's fate
                # to settle. The container now exists and holds the
                # credential, but it must never be started for a session
                # the API already reported cancelled; the cancel stops and
                # removes it.
                helper.started.set()
                return 137
            try:
                await docker_engine.start_container(container_id)
            finally:
                # The start has settled: from here on a stop is a real
                # stop, not a 304 against a container that is not running
                # yet.
                helper.started.set()
            code = await docker_engine.wait_container(container_id, timeout_s=settings.helper_timeout_s)
            if code is None:
                logger.warning("helper %s for session %s timed out; stopping it", phase, session_id)
                await docker_engine.stop_container(container_id)
                code = 124
            return code
        finally:
            self._helpers.pop(session_id, None)
            if helper.container_id:
                try:
                    await docker_engine.remove_container(helper.container_id)
                except Exception:
                    logger.warning("could not remove %s helper container for session %s", phase, session_id)

    async def _prepare_checkout(
        self, session: dict[str, Any], workspace: dict[str, Any], branch: str, artifact_host_path: str
    ) -> None:
        """Phase one: the helper that makes the working copy trustworthy."""
        env = {
            "LOGOS_SESSION_PHASE": "prepare",
            "LOGOS_SESSION_ID": str(session["id"]),
            "LOGOS_SESSION_BRANCH": branch,
            "LOGOS_SESSION_BASE_BRANCH": workspace["base_branch"],
            "LOGOS_REPO_URL": settings.repo_url,
            "LOGOS_ARTIFACT_DIR": "/artifacts",
            # The account the session's commits belong to. The helper
            # configures git with it, and the finalizer refuses to push if
            # the token turns out to be somebody else's.
            "LOGOS_AGENT_GITHUB_LOGIN": settings.github_login,
        }
        if settings.session_github_token:
            env["GITHUB_TOKEN"] = settings.session_github_token
        code = await self._run_helper(
            phase="prepare",
            session_id=session["id"],
            env=env,
            workspace_volume=workspace["volume_name"],
            artifact_host_path=artifact_host_path,
        )
        if code != 0:
            raise RuntimeError(f"checkout preparation failed (exit {code})")

    async def _finalize(self, session_id: int) -> bool:
        """Phase three: commit, push, and open the pull request, if asked.

        The agent phase carried no GitHub credential, so the authenticated
        work happens here — in a runner-owned container that gets the scoped
        token and egress, after the agent has exited. A failure means the
        work did not reach the repository, and the session is failed rather
        than settled as a success with a deploy attached.
        """
        session = await db.get_session(session_id)
        if not session or not session.get("branch_name"):
            logger.warning("no branch recorded for session %s; cannot finalize", session_id)
            return False
        workspace = await db.get_workspace(session["workspace_id"])
        if workspace is None:
            logger.warning("workspace of session %s is gone; cannot finalize", session_id)
            return False
        env = {
            "LOGOS_SESSION_PHASE": "finalize",
            "LOGOS_SESSION_ID": str(session_id),
            "LOGOS_SESSION_BRANCH": session["branch_name"],
            "LOGOS_SESSION_BASE_BRANCH": workspace["base_branch"],
            "LOGOS_SESSION_TASK": str(session.get("task") or ""),
            "LOGOS_SESSION_OPEN_PR": "1" if session.get("open_pull_request") else "0",
            "LOGOS_REPO_URL": settings.repo_url,
            "LOGOS_REPO_SLUG": settings.repo_slug,
            "LOGOS_ARTIFACT_DIR": "/artifacts",
            "LOGOS_AGENT_GITHUB_LOGIN": settings.github_login,
            # Whether this session's work may include CI workflow files. With
            # a separate session token GitHub decides — a token without
            # `workflow` scope simply cannot push them. With the fallback the
            # token *does* have the scope, so the finalizer refuses instead:
            # a workflow file the agent wrote would otherwise run with the
            # repository's secrets as soon as its pull request opened.
            "LOGOS_AGENT_WORKFLOW_CHANGES": ("deny" if settings.session_token_is_runner_token else "allow"),
        }
        if settings.session_github_token:
            env["GITHUB_TOKEN"] = settings.session_github_token
            env["GH_TOKEN"] = settings.session_github_token
        code = await self._run_helper(
            phase="finalize",
            session_id=session_id,
            env=env,
            workspace_volume=workspace["volume_name"],
            artifact_host_path=str(
                Path(await docker_engine.volume_mountpoint(settings.artifact_volume)) / str(session_id)
            ),
        )
        return code == 0

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
        """Persist the container's output as events so the UI can follow it.

        Batched by size *and* by time. Size alone was the bug worth naming:
        an agent that prints a handful of lines a minute — which is what
        reading code and running tests looks like — filled a batch of twenty
        only after several minutes, so a session that was working perfectly
        well looked like a session that had hung. Whatever has arrived is
        written within a couple of seconds, and a chatty agent still gets
        one row per twenty lines rather than one per line.
        """
        # Bounded: a session that prints faster than the database accepts
        # rows must slow its reader down, not grow a queue until the runner
        # runs out of memory. The reader blocking is the backpressure — the
        # container's own log buffer is where the surplus waits, which is
        # what it is for.
        lines: asyncio.Queue[str | None] = asyncio.Queue(maxsize=LOG_QUEUE_MAX)

        async def read() -> None:
            # The stream is followed in its own task so the writer below can
            # wake on a timeout: awaiting the iterator directly would block
            # until the next line, which is exactly the line that is late.
            try:
                async for line in docker_engine.stream_logs(container_id, follow=True):
                    await lines.put(line)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("log collection for session %s stopped: %s", session_id, exc)
            finally:
                # Never blocking on a full queue: the end-of-stream marker
                # is what lets the writer finish, and waiting for room in a
                # queue nobody is draining any more would hang the task
                # that is trying to end.
                try:
                    lines.put_nowait(None)
                except asyncio.QueueFull:
                    pass

        reader = asyncio.create_task(read())
        batch: list[str] = []

        async def flush() -> None:
            nonlocal batch
            if not batch:
                return
            await db.add_event(session_id, EventKind.LOG, {"lines": batch})
            await self._note_usage(session_id, batch)
            batch = []

        try:
            while True:
                try:
                    line = await asyncio.wait_for(lines.get(), timeout=LOG_FLUSH_S)
                except (TimeoutError, asyncio.TimeoutError):
                    await flush()
                    continue
                if line is None:
                    await flush()
                    return
                batch.append(line)
                if len(batch) >= LOG_BATCH_LINES:
                    await flush()
        except asyncio.CancelledError:
            raise
        finally:
            reader.cancel()

    async def _note_usage(self, session_id: int, lines: list[str]) -> None:
        """Carry the usage the agent reports into the session row.

        The authoritative numbers arrive with the result file at the end. A
        session that runs for an hour should not show zero for that hour, so
        the agent reports what it has spent so far on its own transcript and
        the newest of those lines updates the row as it goes.
        """
        for line in reversed(lines):
            match = _USAGE_LINE.match(line)
            if match is None:
                continue
            try:
                await db.update_session_usage(
                    session_id,
                    tokens_in=int(match.group("tin")),
                    tokens_out=int(match.group("tout")),
                )
            except Exception as exc:
                logger.debug("could not record the usage of session %s: %s", session_id, exc)
            return

    # --- settlement -------------------------------------------------------

    async def _react(self, session: dict[str, Any] | None, content: str) -> None:
        """Show on the thread how far this session's work has got.

        Best effort in both directions: a reaction that does not appear
        costs nothing, and one that is already there is answered with a 200,
        so a resumed or re-settled session leaves no duplicates.
        """
        target = str((session or {}).get("reaction_target") or "")
        if not target:
            return
        try:
            await github.react(target, content)
        except Exception as exc:
            logger.info("could not react on %s: %s", target, exc)

    async def _settle(self, session_id: int, *, exit_code: int | None, error: str | None) -> None:
        """Record the outcome of a finished session and clean up after it."""
        if exit_code == 0 and not error:
            # A clean agent exit is not yet a finished session: the agent
            # phase carried no GitHub credential, so the trusted finalizer
            # performs the authenticated work (commit, push, pull request)
            # and updates the result file before settlement reads it.
            status = ((await db.get_session(session_id)) or {}).get("status")
            if status not in (SessionStatus.RUNNING.value, SessionStatus.FINALIZING.value):
                # A competing actor (a cancel, a second settlement) reached
                # the row first: it is no longer ours to finish. Give the
                # container back and record nothing.
                logger.warning("settlement of session %s found the row in %r; only cleaning up", session_id, status)
                await self._cleanup_container(session_id)
                return
            if status == SessionStatus.RUNNING.value:
                # Claim the non-pausable finalizing state *before* the
                # helper starts: while the row is still running, a
                # scheduler pass can move it to paused — but the agent
                # container is already gone, so Docker ignores the pause
                # (409), and a later resume would return the row to running
                # with no supervisor left to finish it. The claim is the
                # same atomic move the terminal transition is: a cancel
                # that wins it owns the row, and this settlement records
                # nothing.
                if not await db.transition_session(session_id, SessionStatus.FINALIZING):
                    logger.warning(
                        "session %s was claimed by another actor before finalization; only cleaning up",
                        session_id,
                    )
                    await self._cleanup_container(session_id)
                    return
            # The row is already finalizing: a restart interrupted the first
            # finalizer. The finalizer is idempotent — it re-fetches the
            # base, re-commits the same tree, and force-pushes — so running
            # it again either completes the work or reports a real failure.
            # A finalizer that fails fails the session — nothing landed, and
            # a deploy must not be dispatched behind it.
            if not await self._finalize(session_id):
                error = "finalization failed: the agent's work did not reach the repository"
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
        if isinstance(result.get("cost_usd"), (int, float)):
            fields["cost_usd"] = float(result["cost_usd"])
        if result.get("pr_url"):
            fields["pr_url"] = str(result["pr_url"])

        moved = await db.transition_session(
            session_id,
            SessionStatus.SUCCEEDED if succeeded else SessionStatus.FAILED,
            **fields,
        )
        if not moved:
            # A competing actor reached the terminal row first — most often a
            # cancel winning against a settlement that restart reconciliation
            # kicks off for an exited container. The session already belongs
            # to that actor: give the container back, but emit no status
            # event, dispatch no deploy, and take no screenshots for a
            # session whose state is already final.
            logger.warning(
                "settlement of session %s lost the race to another transition; only cleaning up",
                session_id,
            )
            await self._cleanup_container(session_id)
            return
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

        if not succeeded:
            # Somebody is looking at a thread that has been marked as picked
            # up and started. Saying that it did not work out belongs there
            # too — an answer that never comes is the worst of the three.
            await self._react(await db.get_session(session_id), github.REACTION_FAILED)

        # Somebody asked this session a question. The agent phase holds no
        # GitHub credential, so it wrote the answer into its artefact
        # directory and this is where the answer is posted — by the process
        # that does hold the token. Posted even for a failed session: a
        # partial answer beats silence on a thread where a person is
        # waiting.
        await self._post_reply(session_id)

        deploy: str | None = None
        after_run_id: int | None = None
        if succeeded:
            # Hold the shared-environment lock across the whole
            # dispatch-to-screenshot sequence, so a second settling session
            # cannot dispatch in the middle of this one's wait or photograph
            # this one's deploy (see the lock in __init__).
            async with self._deploy_screenshot_lock:
                deploy, after_run_id = await self._maybe_deploy(session_id, result)

                # Give the container back before the post-deploy wait: a
                # deploy can take minutes, and the capacity a session holds
                # is worth reclaiming without waiting for its screenshots.
                await self._cleanup_container(session_id)

                await self._capture_screenshots(session_id, deploy, after_run_id)
        else:
            await self._cleanup_container(session_id)

    async def sweep_workspaces(self) -> None:
        """Remove the workspaces the runner made for work that is finished.

        A workspace is a Docker volume holding a working copy. One created
        for a piece of triggered work has no meaning once that work is done,
        and left behind they fill the parallel ceiling with checkouts nobody
        is using — the ceiling counts workspaces, not sessions. Operators'
        workspaces are never touched: they made them, they keep them.

        The idle grace is what keeps this from deleting a workspace out from
        under the session it was just created for: between queueing and
        claiming, that session is not active yet either.
        """
        cutoff = datetime.now(timezone.utc) - _WORKSPACE_IDLE_GRACE
        try:
            disposable = await db.disposable_workspaces(cutoff)
        except Exception as exc:
            logger.warning("could not look for finished workspaces: %s", exc)
            return
        for workspace in disposable:
            name, volume = workspace.get("name"), workspace.get("volume_name")
            # The volume goes first, the row is retired second: a failure in
            # between leaves the workspace un-archived, so the next sweep
            # finds it again and tries the volume once more. Retiring first
            # would leave a volume nothing knows about.
            try:
                await docker_engine.remove_volume(str(volume), force=True)
            except Exception as exc:
                logger.warning("could not remove the volume of finished workspace '%s': %s", name, exc)
                continue
            if await db.archive_workspace(int(workspace["id"])):
                logger.info("retired finished workspace '%s' and reclaimed its volume", name)

    async def deliver_pending_replies(self) -> None:
        """Try again for answers that did not reach GitHub the first time.

        Delivery happens once when a session settles, and a timeout or a 5xx
        at that moment would otherwise lose the answer for good: the trigger
        reference counts as handled, so nothing looks at it again. Every
        scheduler pass gives the few outstanding ones another go, until they
        land or the attempts run out.
        """
        try:
            owing = await db.sessions_owing_a_reply(_MAX_REPLY_ATTEMPTS)
        except Exception as exc:
            logger.warning("could not look for undelivered answers: %s", exc)
            return
        for row in owing:
            await self._post_reply(int(row["id"]))

    async def _post_reply(self, session_id: int) -> None:
        """Post the answer a session wrote, if it was asked for one."""
        session = await db.get_session(session_id)
        target = str((session or {}).get("reply_target") or "")
        if not target:
            return
        if (session or {}).get("reply_posted_at"):
            return
        path = artifact_dir(session_id) / REPLY_FILE
        try:
            body = path.read_text().strip()
        except FileNotFoundError:
            body = ""
        except OSError as exc:
            # A mount that is not there yet, a permission, a read error: the
            # file may well exist and be readable on the next pass, so this
            # counts as an attempt rather than as an answer that was never
            # written. Only a file that is genuinely absent is final.
            await db.record_reply_attempt(session_id, delivered=False)
            logger.warning("could not read the answer of session %s (will retry): %s", session_id, exc)
            return
        if not body:
            # The session is over and its artefacts are final: no later pass
            # will find an answer that is not there. Asked again every few
            # seconds otherwise, for the life of the deployment. The 😕 the
            # settlement leaves is what the thread gets instead.
            logger.info("session %s was asked a question but wrote no answer", session_id)
            await db.abandon_reply(session_id, attempts=_MAX_REPLY_ATTEMPTS)
            return
        if len(body) > _MAX_REPLY_CHARS:
            # GitHub refuses a comment above its length limit outright, and
            # an answer nobody receives is worse than a shortened one on a
            # thread where somebody is waiting.
            body = body[:_MAX_REPLY_CHARS].rstrip() + "\n\n_[answer truncated]_"
            logger.info("the answer of session %s was truncated to fit a GitHub comment", session_id)
        try:
            url = await self._send_reply(target, body)
        except Exception as exc:
            # Counted, not given up on: the next scheduler pass tries again
            # until it lands or the attempts run out.
            await db.record_reply_attempt(session_id, delivered=False)
            logger.warning("could not post the answer of session %s (will retry): %s", session_id, exc)
            await db.add_event(session_id, EventKind.ERROR, {"error": f"could not post the reply: {exc}"})
            return
        await db.record_reply_attempt(session_id, delivered=True)
        await db.add_event(session_id, EventKind.PULL_REQUEST, {"url": url, "reply": True})
        logger.info("session %s answered at %s", session_id, url)

    @staticmethod
    async def _send_reply(target: str, body: str) -> str:
        """Post one answer where its question was asked.

        ``target`` is what the trigger recorded: ``issue:<n>`` for a thread,
        or ``review_comment:<n>:<id>`` to answer inside an inline review
        thread — where the question was asked, and where its author is
        looking.
        """
        kind, _, rest = target.partition(":")
        if kind == "issue":
            return await github.post_issue_comment(int(rest), body)
        if kind == "review_comment":
            number, _, comment_id = rest.partition(":")
            return await github.reply_to_review_comment(int(number), int(comment_id), body)
        raise ValueError(f"unknown reply target '{target}'")

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

    async def _maybe_deploy(self, session_id: int, result: dict[str, Any]) -> tuple[str | None, int | None]:
        """Dispatch the dev deploy if the session asked for one.

        Returns ``(outcome, pre_dispatch_run_id)``. The outcome is
        ``"dispatched"``, ``"skipped"``, ``"failed"``, or ``None`` when the
        session did not request a deploy — callers that have to happen
        *after* the deploy (the screenshots) key off it. The
        ``pre_dispatch_run_id`` is the newest run of the deploy workflow
        that existed *before* the dispatch; the screenshots wait for a run
        newer than it, so a deploy that predates this dispatch — or one of
        a session that dispatched earlier — cannot be settled as this
        session's.
        """
        session = await db.get_session(session_id)
        if not session or not session.get("deploy_to_dev"):
            return None, None
        if not settings.deploy_enabled:
            await db.add_event(
                session_id,
                EventKind.DEPLOY,
                {"status": "skipped", "reason": "deploys are disabled on this runner"},
            )
            return "skipped", None
        try:
            # Dispatched from here, never from the container: the workflow-scoped
            # token stays in this service, and the workflow itself is pinned to
            # the dev environment. The dispatch carries the prebuilt image tag
            # and nothing else branch-derived: the workflow checks out the
            # repository to copy the compose file to the dev host, so it runs
            # on a fixed trusted ref, never the session's agent-editable
            # branch. The tag is the pull request build's, never latest:
            # branch pushes never build, and latest still points at main, so
            # a latest dispatch would deploy the old revision.
            image_tag = await self._wait_for_session_image(session_id, result, session.get("branch_name") or "main")
            if image_tag is None:
                return "failed", None
            # The pre-dispatch marker: whatever run exists on the trusted
            # ref right now is older than the one this dispatch creates.
            after_run_id = await github.latest_dev_deploy_run_id()
            run_url = await github.dispatch_dev_deploy(image_tag=image_tag)
            await db.update_session(session_id, deployed_at=datetime.now(timezone.utc))
            await db.add_event(
                session_id,
                EventKind.DEPLOY,
                {
                    "status": "dispatched",
                    "environment": settings.allowed_environment,
                    "url": run_url,
                    "image_tag": image_tag,
                },
            )
            return "dispatched", after_run_id
        except Exception as exc:
            logger.warning("dev deploy for session %s failed: %s", session_id, exc)
            await db.add_event(session_id, EventKind.DEPLOY, {"status": "failed", "error": str(exc)})
            return "failed", None

    async def _wait_for_session_image(self, session_id: int, result: dict[str, Any], branch: str) -> str | None:
        """The image tag a deploy of this session must pull — or None.

        The build workflow only runs when the session's pull request opens,
        and PR builds publish ``pr-<number>`` images, never ``latest``. A
        deploy of the session's own code therefore waits for that run and
        uses the exact tag it published. Without a pull request no image of
        the branch exists at all, so the deploy is refused with a visible
        reason instead of falling back to main's stale ``latest`` images —
        which would report the session's work deployed while serving the
        old revision.
        """
        pr_number = github.pr_number_from_url(result.get("pr_url") or "")
        if pr_number is None:
            await db.add_event(
                session_id,
                EventKind.DEPLOY,
                {
                    "status": "failed",
                    "error": "session opened no pull request, so no image of its branch exists to deploy",
                },
            )
            return None
        pushed_sha = str(result.get("pushed_sha") or "").strip()
        if not pushed_sha:
            # Without the pushed commit the build could not be pinned to a
            # revision: the branch may carry an earlier, already-built
            # commit, and the run of that commit would be mistaken for the
            # build of this session's work.
            await db.add_event(
                session_id,
                EventKind.DEPLOY,
                {"status": "failed", "error": "the finalizer recorded no pushed commit, so the build cannot be pinned"},
            )
            return None
        status, detail = await github.wait_for_pr_builds(branch, pushed_sha)
        if status != "success":
            await db.add_event(
                session_id,
                EventKind.DEPLOY,
                {"status": "failed", "error": f"image builds did not succeed ({status}): {detail}"},
            )
            return None
        return f"pr-{pr_number}"

    async def _capture_screenshots(self, session_id: int, deploy: str | None, after_run_id: int | None = None) -> None:
        """Capture the session's requested dev pages, after everything else.

        Running this in settlement — and only after a requested dev deploy has
        finished and the environment serves again — is what makes the photos
        show the revision the session just deployed. A session container would
        see the previous revision: it exits long before the deploy dispatch
        is even made. A requested deploy that failed or was skipped skips the
        photos too, for the same reason: the environment would still be
        serving the previous revision.

        ``after_run_id`` is the pre-dispatch run marker the dispatch
        recorded: the wait accepts only a run of the deploy workflow newer
        than it, so a completed deploy from before this dispatch cannot end
        the wait and make the photos pass for the revision this session put
        in the environment.
        """
        session = await db.get_session(session_id)
        paths = (session or {}).get("screenshot_paths") or []
        if not paths:
            return

        if deploy == "dispatched":
            status, detail = await github.wait_for_dev_deploy(after_run_id=after_run_id)
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
        elif deploy in ("failed", "skipped"):
            # The session asked for a deploy that did not land (the dispatch
            # failed, the build did not succeed, or deploys are disabled):
            # the pages would show the old revision under this session's name.
            await db.add_event(
                session_id,
                EventKind.SCREENSHOT,
                {"status": "skipped", "reason": f"requested dev deploy did not land ({deploy})"},
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
            try:
                await docker_engine.remove_container(container_id)
            except Exception:
                # Another actor (usually the cancel this cleanup races) may
                # already have removed it.
                logger.debug("could not remove the container of session %s", session_id)

    async def _relinquish_container(self, container_id: str) -> None:
        """Give a container back that a lost transition no longer owns.

        Called when restart reconciliation loses a recovered session's
        state transition — most often to a cancel that landed in the
        restart window and, seeing no container id in the row yet, could
        not stop it itself. The id Docker told us about is all we have, so
        the stop-and-remove happens here: a credential-bearing agent must
        not outlive the row that manages it.
        """
        try:
            await docker_engine.stop_container(container_id)
        except Exception:
            # Already exited or removed: only the removal below can still
            # matter.
            pass
        try:
            await docker_engine.remove_container(container_id)
        except Exception:
            logger.warning("could not remove the relinquished container %s", container_id)

    # --- operator actions -------------------------------------------------

    async def cancel(self, session_id: int) -> bool:
        session = await db.get_session(session_id)
        if session is None:
            return False
        status = SessionStatus(session["status"])
        if status in (SessionStatus.SUCCEEDED, SessionStatus.FAILED, SessionStatus.CANCELLED):
            return False

        container_id = session.get("container_id")
        # Claim the terminal state before any container I/O: stopping the
        # container is what produces the exit the supervisor settles, and
        # that settle must lose this race — otherwise the cancellation lands
        # as FAILED or SUCCEEDED, complete with the deploy and screenshot
        # side effects of a finished session.
        moved = await db.transition_session(session_id, SessionStatus.CANCELLED, finished_at=datetime.now(timezone.utc))
        if not moved:
            return False

        # Mark an in-flight launch in the same step as the transition, before
        # any further await: from here on the launch observes the
        # cancellation at its next phase boundary and starts nothing. Every
        # await between the transition and this line would be another
        # scheduling point in which a racing launch could still reach a
        # container. Marked, not removed, because a launch that has not
        # started yet has to find this record rather than take a fresh,
        # uncancelled one — its own cleanup removes it, and so does the wait
        # below.
        launch = self._launches.get(session_id)
        if launch is not None:
            launch.cancelled = True
        await db.add_event(session_id, EventKind.STATUS, {"status": "cancelled"})
        # The credential-bearing helper first: a finalizer mid-push would
        # otherwise keep committing, pushing, or opening a pull request after
        # the API has already reported the session cancelled. It is tracked
        # per session rather than read from the supervisor because restart
        # reconciliation finalizes without one.
        helper = self._helpers.pop(session_id, None)
        if helper is not None:
            # Wait for the create to settle before anything else: a cancel
            # that lands while the create request is in flight must not
            # report success before the credential-bearing container is
            # known to exist — and the helper must never start one.
            await helper.created.wait()
            if helper.container_id is not None:
                # Wait for the in-flight start to settle before stopping: a
                # stop that lands first is a 304 no-op, and the pending
                # start would complete after this returns — a
                # credential-bearing container, running, with no one left
                # to stop it. Settled, the stop is a real stop (or a 304
                # for a container the helper was cancelled before starting,
                # which is the desired state), and the force-remove after
                # it makes the cancellation final, so a success here can
                # never be followed by a running helper. The helper's own
                # cleanup removes the container as well; it tolerates the
                # one that is already gone.
                await helper.started.wait()
                try:
                    await docker_engine.stop_container(helper.container_id, timeout_s=5)
                except Exception:
                    logger.warning("could not stop the helper of cancelled session %s", session_id)
                try:
                    await docker_engine.remove_container(helper.container_id)
                except Exception:
                    logger.warning("could not remove the helper of cancelled session %s", session_id)
        if launch is not None:
            # The helper (if any) has been stopped, so the launch reaches its
            # next boundary promptly. Waiting for it is what makes the
            # cancellation true rather than merely reported: when this
            # returns, no phase of the launch is still on its way to starting
            # something for this session. The wait is bounded so a wedged
            # Docker call cannot hang the API — the flag is checked at every
            # boundary regardless, so a launch that outlives the wait still
            # starts nothing and gives back what it created.
            try:
                await asyncio.wait_for(launch.settled.wait(), timeout=_CANCEL_LAUNCH_WAIT_S)
            except asyncio.TimeoutError:
                logger.error(
                    "launch of cancelled session %s did not settle within %ss; " "it will stop at its next boundary",
                    session_id,
                    _CANCEL_LAUNCH_WAIT_S,
                )
            finally:
                # The row is terminal, so no launch can legitimately follow:
                # the record has done its work either way.
                self._launches.pop(session_id, None)
        task = self._supervisors.pop(session_id, None)
        if task:
            task.cancel()
        if container_id:
            try:
                # Unpause first: a paused container cannot process the stop
                # signal, and Docker would otherwise wait out the full grace
                # period.
                await docker_engine.unpause_container(container_id)
                await docker_engine.stop_container(container_id, timeout_s=5)
            except Exception:
                logger.warning("could not stop the container of cancelled session %s", session_id)
            try:
                # A supervisor settling the same exit may remove it first.
                await docker_engine.remove_container(container_id)
            except Exception:
                logger.warning("could not remove the container of cancelled session %s", session_id)
        return True


manager = SessionManager()
