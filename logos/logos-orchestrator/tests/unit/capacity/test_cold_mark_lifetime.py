"""The cold mark only covers a lane while the planner takes it out of service.

A sleep or stop marks its lane cold before the drain, so the scheduler stops
routing new requests to a lane that is about to go away. Once the action has
ended, the worker's own runtime state keeps a sleeping or removed lane out of
the rotation, so the mark has nothing left to do. A mark that outlives the
action is never read again until something clears it, and only a confirmed
planner wake does. Every other way back to an awake lane, such as the panel's
wake button, the worker restarting the engine, or a wake confirmed only after
its poll gave up, leaves a lane that the worker reports as loaded and idle
but the scheduler never picks, while its sibling lane takes the entire load.

The one case where the mark outlives the action is an action that ends before
the worker has answered its command, because it was cancelled or the command
timed out. The worker still carries the command out, possibly only after
other commands queued ahead of it, so the lane stays out of the rotation until
the worker answers or its session ends.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from logos import CapacityPlanner, LogosNodeRuntimeRegistry
from logos.sdi.models import CapacityPlanAction

PROVIDER_ID = 7
MODEL = "Qwen/Qwen3-Reranker-8B"
BUSY_LANE = "planner-Qwen_Qwen3-Reranker-8B"
IDLE_LANE = "planner-Qwen_Qwen3-Reranker-8B-2"


def _lane(lane_id: str, runtime_state: str, sleep_state: str, queue_waiting: float) -> dict:
    return {
        "lane_id": lane_id,
        "model": MODEL,
        "runtime_state": runtime_state,
        "sleep_state": sleep_state,
        "active_requests": 0,
        "backend_metrics": {"queue_waiting": queue_waiting, "requests_running": 1.0 if queue_waiting else 0.0},
    }


class _Worker:
    """The worker end of the session: carries out lane commands and answers them.

    With ``answering`` off, commands queue up unanswered, the way they wait on
    a worker that runs one command at a time; ``finish`` then carries out and
    answers the oldest one.
    """

    def __init__(self) -> None:
        self.registry = LogosNodeRuntimeRegistry()
        self.lanes = {
            BUSY_LANE: _lane(BUSY_LANE, "running", "awake", queue_waiting=453.0),
            IDLE_LANE: _lane(IDLE_LANE, "loaded", "awake", queue_waiting=0.0),
        }
        self.answering = True
        self.queued: list[dict] = []
        # The lane manager's lifecycle revision, bumped by every lane change.
        self.revision = 0
        # When set, a frame handed to send_json is not written until it is.
        self.send_gate: asyncio.Event | None = None

    async def connect(self) -> None:
        ticket = await self.registry.consume_ticket(await self.registry.issue_ticket(PROVIDER_ID, "worker-a", [MODEL]))
        assert ticket is not None
        await self.registry.attach_session(ticket, self)
        await self.publish()

    async def publish(self, lanes: list[dict] | None = None, revision: int | None = None) -> None:
        """Send a status: the current lanes, or a sample taken earlier at ``revision``."""
        if lanes is None:
            lanes, revision = self.sample()
        runtime = {"lanes": lanes, "lifecycle_revision": revision}
        await self.registry.update_runtime(provider_id=PROVIDER_ID, runtime=runtime)

    def sample(self) -> tuple[list[dict], int]:
        """The lanes as a status collects them, with the revision taken first."""
        return [dict(lane) for lane in self.lanes.values()], self.revision

    async def send_json(self, message: dict) -> None:
        if message.get("type") != "command" or message.get("action") == "cancel_command":
            return
        self.queued.append(message)
        if self.send_gate is not None:
            await self.send_gate.wait()
        if self.answering:
            asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(self.finish()))

    async def close(self) -> None:
        return None

    async def finish(self, *, skip_sleep: bool = False, status: bool = True, answer_first: bool = False) -> None:
        """Carry out and answer the oldest command.

        The worker sends its answer and its status separately, so either can
        arrive first; ``status=False`` leaves the status for a later publish.
        """
        message = self.queued.pop(0)
        lane = self.lanes[message["params"]["lane_id"]]
        if message["action"] == "sleep_lane" and not skip_sleep:
            lane.update(runtime_state="sleeping", sleep_state="sleeping")
        elif message["action"] == "wake_lane":
            lane.update(runtime_state="loaded", sleep_state="awake")
        self.revision += 1
        if status and not answer_first:
            await self.publish()
        await self.registry.on_command_result(
            PROVIDER_ID,
            {"cmd_id": message["cmd_id"], "success": True, "result": {"ok": True}, "lifecycle_revision": self.revision},
        )
        if status and answer_first:
            await self.publish()

    async def wake_from_the_panel(self) -> None:
        """What the panel's wake button does: the worker wakes the lane, the planner is not involved."""
        self.lanes[IDLE_LANE].update(runtime_state="loaded", sleep_state="awake")
        self.revision += 1
        await self.publish()

    async def selected(self) -> str:
        return (await self.registry.select_lane_for_model(PROVIDER_ID, MODEL))["lane_id"]

    def cold(self) -> bool:
        return self.registry.is_lane_cold_marked(PROVIDER_ID, IDLE_LANE)


def _planner(worker: _Worker) -> CapacityPlanner:
    """A planner running the real executor against the real registry."""
    planner = CapacityPlanner.__new__(CapacityPlanner)
    planner._registry = worker.registry
    planner._facade = MagicMock()
    planner._facade.get_provider_name.return_value = "worker-a"
    planner._marked_cold_lanes = set()
    planner._lane_action_locks = {}
    planner._lane_sleep_since = {}
    planner._lane_sleep_level = {}
    planner._lane_idle_since = {}
    planner._lane_loaded_at = {}
    planner._drain_timestamps = {}
    planner._safe_get_profiles = MagicMock(return_value={})
    planner._safe_get_capacity = MagicMock(return_value=None)
    planner._lane_gpu_devices_str = MagicMock(return_value=None)
    planner._get_per_gpu_free = MagicMock(return_value=None)
    planner._release_vram = MagicMock()
    planner._check_host_ram_headroom_for_sleep = MagicMock(return_value=(True, 100_000.0, 1_000.0))
    planner._drain_lane = AsyncMock(return_value=True)
    planner._on_state_change = None
    planner._pending_capacity = {}
    planner._lifecycle_commands_sent = {}
    planner._cold_mark_holds = {}
    planner._cold_mark_settlers = set()
    planner._mark_wake_failure = MagicMock()
    planner._lane_wake_failure_until = {}
    planner._lane_was_cold_loaded = {}
    planner._lane_load_failure_until = {}
    return planner


@pytest.fixture(autouse=True)
def _fast_confirmation_poll(monkeypatch):
    """The confirmation poll waits 2 s between reads; the simulated worker is instant."""
    real_sleep = asyncio.sleep

    async def no_wait(_seconds, *args, **kwargs):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", no_wait)


@pytest.fixture
async def worker() -> _Worker:
    worker = _Worker()
    await worker.connect()
    return worker


def _action(kind: str) -> CapacityPlanAction:
    return CapacityPlanAction(
        action=kind,
        provider_id=PROVIDER_ID,
        lane_id=IDLE_LANE,
        model_name=MODEL,
        reason="Evicted for wake of another model",
    )


async def _settled() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


# ── the mark ends with the action ───────────────────────────────────────────


async def test_a_lane_woken_outside_the_planner_takes_requests_again(worker):
    planner = _planner(worker)

    assert await planner._execute_action_with_confirmation(_action("sleep_l1"), timeout_seconds=10.0)
    assert await worker.selected() == BUSY_LANE  # the sleeping sibling is not routable

    await worker.wake_from_the_panel()

    assert await worker.selected() == IDLE_LANE
    assert not worker.cold()


async def test_a_sleep_cancelled_mid_drain_does_not_leave_the_lane_cold(worker):
    planner = _planner(worker)
    planner._drain_lane = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await planner._execute_action_with_confirmation(_action("sleep_l1"), timeout_seconds=10.0)

    assert await worker.selected() == IDLE_LANE
    assert not worker.cold()


async def test_the_lane_stays_cold_while_the_sleep_is_in_flight(worker):
    planner = _planner(worker)
    seen_during_drain: list[str] = []

    async def drain(provider_id, lane_id, timeout_seconds=30.0):  # noqa: ARG001
        seen_during_drain.append(await worker.selected())
        return True

    planner._drain_lane = drain

    assert await planner._execute_action_with_confirmation(_action("sleep_l1"), timeout_seconds=10.0)
    assert seen_during_drain == [BUSY_LANE]


# ── an action that ends before the worker has answered ─────────────────────


async def _sleep_the_worker_has_not_answered(planner, worker, *, cancel: bool) -> None:
    """Run a sleep whose command waits on the worker, and end it by cancelling or timing out."""
    worker.answering = False
    task = asyncio.create_task(planner._execute_action_with_confirmation(_action("sleep_l1"), timeout_seconds=1.0))
    for _ in range(50):
        if worker.queued:
            break
        await asyncio.sleep(0)
    assert worker.queued, "the sleep command never reached the worker"
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await asyncio.wait_for(task, timeout=5)  # the command times out after 1 s


@pytest.mark.parametrize("cancel", [True, False], ids=["cancelled", "command timed out"])
async def test_a_lane_stays_cold_until_the_worker_answers_the_sleep(worker, cancel):
    planner = _planner(worker)

    await _sleep_the_worker_has_not_answered(planner, worker, cancel=cancel)

    # The worker has not even reported a step yet: the command waits behind
    # another one. However long that takes, the lane gets no requests.
    assert worker.cold()
    assert await worker.selected() == BUSY_LANE

    await worker.finish()
    await _settled()

    assert not worker.cold()
    assert await worker.selected() == BUSY_LANE  # asleep now
    await worker.wake_from_the_panel()
    assert await worker.selected() == IDLE_LANE


async def test_a_sleep_the_worker_skipped_restores_routing_once_it_answers(worker):
    planner = _planner(worker)
    await _sleep_the_worker_has_not_answered(planner, worker, cancel=True)

    # A request arrived during the worker's drain, so it kept the lane awake.
    await worker.finish(skip_sleep=True, answer_first=True)
    await _settled()

    assert not worker.cold()
    assert await worker.selected() == IDLE_LANE


async def test_an_answer_that_arrives_before_the_status_keeps_the_lane_cold(worker):
    planner = _planner(worker)
    await _sleep_the_worker_has_not_answered(planner, worker, cancel=True)

    # The lane is asleep on the worker, but the status saying so is still on its way.
    await worker.finish(status=False)
    await _settled()
    assert worker.cold()
    assert await worker.selected() == BUSY_LANE

    await worker.publish()
    await _settled()
    assert not worker.cold()
    assert await worker.selected() == BUSY_LANE  # asleep


async def test_a_newer_sleep_aborted_before_dispatch_keeps_the_older_sleep_holding(worker):
    planner = _planner(worker)
    await _sleep_the_worker_has_not_answered(planner, worker, cancel=True)

    planner._drain_lane = AsyncMock(return_value=False)  # the newer sleep gives up during its drain
    assert not await planner._execute_action_with_confirmation(_action("sleep_l1"), timeout_seconds=10.0)

    assert worker.cold()
    assert await worker.selected() == BUSY_LANE

    await worker.finish(skip_sleep=True, answer_first=True)
    await _settled()
    assert not worker.cold()
    assert await worker.selected() == IDLE_LANE


async def test_a_replaced_session_ends_the_wait_for_the_answer(worker):
    planner = _planner(worker)
    await _sleep_the_worker_has_not_answered(planner, worker, cancel=True)

    # The worker reconnects before the old handler has detached; its new
    # session reports the lane awake, and the old command is gone with the old session.
    ticket = await worker.registry.consume_ticket(await worker.registry.issue_ticket(PROVIDER_ID, "worker-a", [MODEL]))
    await worker.registry.attach_session(ticket, _Worker())
    await worker.publish()
    await _settled()

    assert not worker.cold()
    assert await worker.selected() == IDLE_LANE


async def test_a_lost_session_ends_the_wait_for_the_answer(worker):
    planner = _planner(worker)
    await _sleep_the_worker_has_not_answered(planner, worker, cancel=True)

    await worker.registry.detach_session(PROVIDER_ID)
    await _settled()

    assert not worker.cold()


async def test_a_failed_wake_keeps_the_mark_of_an_unanswered_sleep(worker):
    planner = _planner(worker)
    await _sleep_the_worker_has_not_answered(planner, worker, cancel=True)

    # The wake queues behind the sleep and times out without an answer.
    assert not await planner._execute_action_with_confirmation(_action("wake"), timeout_seconds=1.0)

    assert worker.cold()
    assert await worker.selected() == BUSY_LANE


async def test_a_confirmed_wake_retires_the_mark_of_an_unanswered_sleep(worker):
    planner = _planner(worker)
    await _sleep_the_worker_has_not_answered(planner, worker, cancel=True)

    wake = asyncio.create_task(planner._execute_action_with_confirmation(_action("wake"), timeout_seconds=10.0))
    for _ in range(50):
        if len(worker.queued) == 2:
            break
        await asyncio.sleep(0)
    await worker.finish()  # the sleep queued ahead of the wake
    await worker.finish()  # the wake
    assert await wake

    assert not worker.cold()
    assert await worker.selected() == IDLE_LANE


async def test_a_newer_sleep_keeps_its_own_mark_when_the_older_one_is_answered(worker):
    planner = _planner(worker)
    await _sleep_the_worker_has_not_answered(planner, worker, cancel=True)

    seen_during_drain: list[bool] = []

    async def drain(provider_id, lane_id, timeout_seconds=30.0):  # noqa: ARG001
        await worker.finish(skip_sleep=True)  # the older sleep is answered mid-drain
        await _settled()
        seen_during_drain.append(worker.cold())
        return True

    planner._drain_lane = drain
    worker.answering = True
    assert await planner._execute_action_with_confirmation(_action("sleep_l1"), timeout_seconds=10.0)

    assert seen_during_drain == [True]
    assert not worker.cold()


# ── routing and publishing ──────────────────────────────────────────────────


async def test_a_lane_the_worker_is_taking_down_gets_no_requests(worker):
    worker.lanes[IDLE_LANE]["transition"] = "falling_asleep"
    await worker.publish()

    assert await worker.selected() == BUSY_LANE

    worker.lanes[IDLE_LANE]["transition"] = "waking"
    await worker.publish()
    assert await worker.selected() == IDLE_LANE


def test_the_registry_publishes_a_cold_mark_change_once():
    registry = LogosNodeRuntimeRegistry()
    published: list[int] = []
    registry.on_cold_mark_changed = published.append

    registry.mark_lane_cold(PROVIDER_ID, IDLE_LANE)
    registry.mark_lane_cold(PROVIDER_ID, IDLE_LANE)
    registry.unmark_lane_cold(PROVIDER_ID, IDLE_LANE)
    registry.unmark_lane_cold(PROVIDER_ID, IDLE_LANE)

    assert published == [PROVIDER_ID, PROVIDER_ID]


async def test_a_status_sampled_before_the_command_does_not_release_the_lane(worker):
    planner = _planner(worker)
    await _sleep_the_worker_has_not_answered(planner, worker, cancel=True)
    # A status collection starts before the worker gets to the sleep ...
    early_lanes, early_revision = worker.sample()

    await worker.finish(skip_sleep=True, status=False)
    # ... and is delivered only after the answer.
    await worker.publish(early_lanes, early_revision)
    await _settled()
    assert worker.cold()
    assert await worker.selected() == BUSY_LANE

    await worker.publish()
    await _settled()
    assert not worker.cold()
    assert await worker.selected() == IDLE_LANE


async def test_a_sleep_cancelled_while_its_command_is_being_sent_keeps_the_lane_cold(worker):
    planner = _planner(worker)
    worker.answering = False
    worker.send_gate = asyncio.Event()
    task = asyncio.create_task(planner._execute_action_with_confirmation(_action("sleep_l1"), timeout_seconds=1.0))
    for _ in range(50):
        if worker.queued:
            break
        await asyncio.sleep(0)
    assert worker.queued, "the frame never reached the websocket"

    task.cancel()  # the frame is handed off, the send has not returned
    with pytest.raises(asyncio.CancelledError):
        await task
    worker.send_gate.set()
    await _settled()
    assert worker.cold()

    await worker.finish()
    await _settled()
    assert not worker.cold()


async def test_a_manual_drain_keeps_its_mark_when_an_older_sleep_settles(worker):
    planner = _planner(worker)
    await _sleep_the_worker_has_not_answered(planner, worker, cancel=True)
    seen_during_drain: list[bool] = []

    async def drain(provider_id, lane_id, timeout_seconds=30.0):  # noqa: ARG001
        await worker.finish(skip_sleep=True, answer_first=True)  # the older sleep settles mid-drain
        await _settled()
        seen_during_drain.append(worker.cold())
        return False  # the lane does not drain in time

    planner._drain_lane = drain
    result = await planner.drain_lane_manually(PROVIDER_ID, IDLE_LANE)

    assert result["status"] == "drain_timeout"
    assert seen_during_drain == [True]
    assert not worker.cold()


async def test_a_sleep_cancelled_before_its_command_is_sent_releases_the_lane(worker):
    """Another command holds the session's send lock; the sleep is cancelled
    while waiting for it, so the worker never gets the sleep."""
    planner = _planner(worker)
    send_lock = worker.registry._sessions[PROVIDER_ID].send_lock  # noqa: SLF001
    await send_lock.acquire()
    try:
        task = asyncio.create_task(planner._execute_action_with_confirmation(_action("sleep_l1"), timeout_seconds=10.0))
        await _settled()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        send_lock.release()
    await _settled()

    assert worker.queued == []
    assert worker.registry._sessions[PROVIDER_ID].pending_commands == {}  # noqa: SLF001
    assert not worker.cold()
    assert await worker.selected() == IDLE_LANE
