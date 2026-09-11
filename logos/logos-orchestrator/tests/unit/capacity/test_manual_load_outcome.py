"""The recorded outcome of a manual load — what the statistics UI can ask for.

``lanes/add`` answers 202 and runs the load in the background, so a refusal in
there (no room on the worker, the worker rejected the command, the
confirmation timed out) leaves the UI's "Loading …" note hanging forever —
the refusal was a log line. The planner therefore records the outcome of the
most recent manual load per (provider, model); the internal load_status
endpoint hands it to Spring, and the UI polls it while the note is up.
"""

from __future__ import annotations

import asyncio
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from logos.capacity.capacity_planner import CapacityPlanner
from logos.sdi.models import CapacityPlanAction

# logos/__init__ aliases itself to logos.main, which breaks the plain
# `import logos.capacity...` attribute chain; the module object comes from
# the import above.
planner_mod = sys.modules["logos.capacity.capacity_planner"]

# Stands in for a real calibrated ModelProfile — load_lane_manually's own
# calibration gate only ever reads .residency_source.
_CALIBRATED_PROFILE = SimpleNamespace(residency_source="calibrated")


def _planner(*, calibrating=False, has_status=True, capacity=object(), profiles=None) -> CapacityPlanner:
    planner = CapacityPlanner.__new__(CapacityPlanner)
    registry = MagicMock()
    registry.is_calibrating.return_value = calibrating
    registry.has_received_first_status.return_value = has_status
    planner._registry = registry
    facade = MagicMock()
    facade.get_capacity_info.return_value = capacity
    facade.get_provider_name.return_value = "worker-a"
    facade.get_model_profiles.return_value = profiles if profiles is not None else {"org/model-a": _CALIBRATED_PROFILE}
    planner._facade = facade
    planner._lane_action_locks = {}
    # A fresh worker: no lane to collide with, so loads reach the executor.
    planner._lane_exists_in_runtime = MagicMock(return_value=False)
    return planner


# ── the outcome store ─────────────────────────────────────────────────────


def test_record_and_read_back_the_outcome():
    planner = _planner()
    before = time.time()
    planner.record_manual_load_outcome(
        1, "org/model-a", "failed", lane_id="planner-org_model-a-2", reason="not enough free VRAM"
    )
    after = time.time()

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome is not None
    assert outcome["status"] == "failed"
    assert outcome["reason"] == "not enough free VRAM"
    assert outcome["lane_id"] == "planner-org_model-a-2"
    assert before <= outcome["updated_at"] <= after


def test_unknown_pair_reads_as_no_outcome():
    """None must stay distinguishable from "failed": the UI must not render
    "no manual load is known" as a refusal."""
    planner = _planner()
    assert planner.get_manual_load_outcome(1, "org/never-loaded") is None
    planner.record_manual_load_outcome(1, "org/model-a", "running")
    assert planner.get_manual_load_outcome(2, "org/model-a") is None
    assert planner.get_manual_load_outcome(1, "org/model-b") is None


def test_a_retry_supersedes_the_previous_outcome():
    planner = _planner()
    planner.record_manual_load_outcome(1, "org/model-a", "failed", reason="first try denied")
    planner.record_manual_load_outcome(1, "org/model-a", "running")

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "running"
    assert "reason" not in outcome
    assert "lane_id" not in outcome


def test_get_returns_a_copy_not_the_stored_entry():
    planner = _planner()
    planner.record_manual_load_outcome(1, "org/model-a", "running")
    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    outcome["status"] = "tampered"
    assert planner.get_manual_load_outcome(1, "org/model-a")["status"] == "running"


def test_expired_outcome_reads_as_unknown_and_is_dropped(monkeypatch):
    planner = _planner()
    now = [1000.0]
    monkeypatch.setattr(planner_mod.time, "time", lambda: now[0])
    planner.record_manual_load_outcome(1, "org/model-a", "failed", reason="old attempt")

    now[0] += CapacityPlanner.MANUAL_LOAD_OUTCOME_TTL_SECONDS + 1
    assert planner.get_manual_load_outcome(1, "org/model-a") is None
    assert planner._manual_load_outcomes == {}


def test_recording_purges_other_expired_entries(monkeypatch):
    planner = _planner()
    now = [1000.0]
    monkeypatch.setattr(planner_mod.time, "time", lambda: now[0])
    planner.record_manual_load_outcome(1, "org/stale", "failed", reason="stale")

    now[0] += CapacityPlanner.MANUAL_LOAD_OUTCOME_TTL_SECONDS + 1
    planner.record_manual_load_outcome(2, "org/fresh", "running")

    assert (1, "org/stale") not in planner._manual_load_outcomes
    assert (2, "org/fresh") in planner._manual_load_outcomes


# ── load_lane_manually records the outcome on every exit ─────────────────


def test_pre_rejection_records_a_failed_outcome():
    planner = _planner(calibrating=True)
    planner._execute_action_with_confirmation = MagicMock()

    assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False
    planner._execute_action_with_confirmation.assert_not_called()

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "failed"
    assert "calibrating" in outcome["reason"]


def test_capacity_gone_at_dispatch_records_a_failed_outcome():
    """The snapshot can go away between the pre-check and the dispatch."""
    planner = _planner()
    planner._execute_action_with_confirmation = MagicMock()
    planner._facade.get_capacity_info.side_effect = [object(), None]

    assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False
    planner._execute_action_with_confirmation.assert_not_called()

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "failed"
    assert "capacity" in outcome["reason"]


def test_confirmed_load_records_succeeded_with_the_lane():
    planner = _planner()
    planner._build_load_params = MagicMock(return_value={})

    async def confirm(action, timeout_seconds=None):
        return True

    planner._execute_action_with_confirmation = confirm

    assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is True

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "succeeded"
    assert outcome["lane_id"] == "planner-org_model-a"


def test_running_is_recorded_before_the_executor_runs():
    """The endpoint records "running" when it answers 202, but a planner-initiated
    path has no such caller — the planner itself must leave the UI something to
    poll while the minutes-long load is in flight."""
    planner = _planner()
    planner._build_load_params = MagicMock(return_value={})
    seen: dict = {}

    async def execute(action, timeout_seconds=None):
        seen["during"] = planner.get_manual_load_outcome(1, "org/model-a")
        return True

    planner._execute_action_with_confirmation = execute
    asyncio.run(planner.load_lane_manually(1, "org/model-a"))

    assert seen["during"]["status"] == "running"
    assert seen["during"]["lane_id"] == "planner-org_model-a"


def test_denied_load_records_the_executors_reason():
    """The executor fails for reasons the manual path cannot know on its own;
    it hands them over per lane and the outcome must carry them — this is the
    "not enough VRAM" refusal the operator needs to see."""
    planner = _planner()
    planner._build_load_params = MagicMock(return_value={})
    reason = (
        "not enough free VRAM for this model: it needs ~48.4 GB in total, "
        "but only 0.8 GB are effectively free on the worker (GPU 0: 838MB, GPU 1: 838MB)."
    )

    async def deny(action, timeout_seconds=None):
        planner.record_lane_action_failure(action.provider_id, action.lane_id, reason)
        return False

    planner._execute_action_with_confirmation = deny
    assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "failed"
    assert outcome["reason"] == reason


def test_unconfirmed_load_without_a_recorded_reason_gets_the_fallback():
    planner = _planner()
    planner._build_load_params = MagicMock(return_value={})

    async def deny(action, timeout_seconds=None):
        return False

    planner._execute_action_with_confirmation = deny
    assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "failed"
    assert outcome["reason"] == "the load was not confirmed by the worker"


def test_clear_lane_action_failure_drops_only_that_lane():
    planner = _planner()
    planner.record_lane_action_failure(1, "lane-a", "denied")
    planner.record_lane_action_failure(1, "lane-b", "denied too")

    planner.clear_lane_action_failure(1, "lane-a")

    assert planner.get_lane_action_failure(1, "lane-a") is None
    assert planner.get_lane_action_failure(1, "lane-b") == "denied too"


def test_a_failed_attempt_cannot_inherit_the_previous_reason():
    """A new attempt must not report a stale reason: the previous attempt
    failed on this lane id, the new one enters "running" — which clears the
    recorded failure — and it then fails without the executor recording a
    fresh reason. The outcome must carry the fallback, not the old failure."""
    planner = _planner()
    planner._build_load_params = MagicMock(return_value={})
    planner.record_lane_action_failure(1, "planner-org_model-a", "an older attempt's denial")

    async def deny(action, timeout_seconds=None):
        return False

    planner._execute_action_with_confirmation = deny
    assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "failed"
    assert outcome["reason"] == "the load was not confirmed by the worker"
    assert planner.get_lane_action_failure(1, "planner-org_model-a") is None


def test_lane_already_present_records_success_without_dispatch():
    """The model is already loaded — the operator's goal is met, so the UI note
    resolves as success; the executor must not be reached for it."""
    planner = _planner()
    planner._execute_action_with_confirmation = MagicMock()
    planner._lane_exists_in_runtime = MagicMock(return_value=True)
    planner._runtime_lane_model = MagicMock(return_value="org/model-a")

    assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False
    planner._execute_action_with_confirmation.assert_not_called()

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "succeeded"


def test_second_click_does_not_overwrite_the_inflight_outcome():
    """While the first load is in flight, a second attempt is a no-op — it
    re-asserts the "running" entry on the in-flight lane, which must come out
    identical to the one it waits on: a different status or lane would make
    the UI drop (or mis-attribute) its note while the load is still going."""
    planner = _planner()
    # A live claim of the first replica (owner None counts as live).
    planner._inflight_load_lane_ids = {1: {"planner-org_model-a": ("org/model-a", None)}}
    planner.record_manual_load_outcome(1, "org/model-a", "running", lane_id="planner-org_model-a")

    assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "running"
    assert outcome["lane_id"] == "planner-org_model-a"


def test_lane_exists_no_op_does_not_overwrite_a_running_entry():
    """The report lagged the runtime: the claimed id already holds the model,
    but a concurrent attempt for it may still be executing and owns the final
    state — the no-op must not resolve the UI note early."""
    planner = _planner()
    planner._execute_action_with_confirmation = MagicMock()
    planner._lane_exists_in_runtime = MagicMock(return_value=True)
    planner._runtime_lane_model = MagicMock(return_value="org/model-a")
    planner.record_manual_load_outcome(1, "org/model-a", "running", lane_id="planner-org_model-a")

    assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "running"


# ── admission: atomic before the 202 ─────────────────────────────────────


def test_admission_is_atomic_a_second_click_meets_the_marker():
    planner = _planner()

    assert planner.manual_load_admission_rejection(1, "org/model-a") is None
    # A different model is unaffected by the claim.
    assert planner.manual_load_admission_rejection(1, "org/model-b") is None
    # The second click for the same model is refused while the first is
    # admitted — a 409 the operator reads, not a 202 whose task no-ops later.
    assert planner.manual_load_admission_rejection(1, "org/model-a") == (
        "A load of this model is already in flight on this worker"
    )


def test_admission_refuses_a_planner_inflight_load_of_the_same_model():
    """A load the planner is already bringing up owns the operator's waiting
    time: answering 202 would start a poll with no manual attempt behind it."""
    planner = _planner()
    # A live claim of the second replica by the planner's demand path.
    planner._inflight_load_lane_ids = {1: {"planner-org_model-a-2": ("org/model-a", None)}}

    assert planner.manual_load_admission_rejection(1, "org/model-a") == (
        "A load of this model is already in flight on this worker"
    )
    assert planner.manual_load_admission_rejection(1, "org/model-b") is None


def test_a_settled_attempt_releases_its_admission():
    planner = _planner()
    planner._build_load_params = MagicMock(return_value={})

    async def execute(action, timeout_seconds=None):
        return True

    planner._execute_action_with_confirmation = execute

    assert planner.manual_load_admission_rejection(1, "org/model-a") is None
    assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is True

    # The attempt is over — a retry is admitted again.
    assert planner.manual_load_admission_rejection(1, "org/model-a") is None


# ── the planner-owned failure ────────────────────────────────────────────


def test_a_planner_owned_inflight_failure_reaches_the_manual_outcome():
    """The reported hole: the click is admitted, then the planner starts the
    same model; the background task no-ops into the planner's load. When that
    load fails, the executor's settlement must turn the manual outcome
    terminal — otherwise the operator's poll waits on a failure only the
    planner's log knows about, until the poll's cap.
    """
    planner = _planner()
    planner._build_load_params = MagicMock(return_value={})

    # The click is admitted while nothing is in flight ...
    assert planner.manual_load_admission_rejection(1, "org/model-a") is None
    # ... and the planner starts the same model in the meantime.
    planner._inflight_load_lane_ids = {1: {"planner-org_model-a-2": ("org/model-a", None)}}

    # The background task meets it: a no-op riding the planner's lane.
    assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "running"
    assert outcome["lane_id"] == "planner-org_model-a-2"

    # The planner's load fails; its executor run settles the entry.
    reason = "not enough free VRAM for this model: it needs ~48.4 GB in total."
    planner.record_lane_action_failure(1, "planner-org_model-a-2", reason)
    planner._settle_manual_load_outcome(1, "org/model-a", "planner-org_model-a-2", False)

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "failed"
    assert outcome["reason"] == reason
    assert outcome["lane_id"] == "planner-org_model-a-2"


def _load_action(lane_id: str = "planner-org_model-a") -> CapacityPlanAction:
    return CapacityPlanAction(
        action="load",
        provider_id=1,
        lane_id=lane_id,
        model_name="org/model-a",
        reason="planner demand",
    )


def test_the_executor_settles_a_manual_outcome_riding_on_its_lane():
    """The wrapper around the executor is what publishes the terminal state —
    for a planner-owned load, nothing else ever calls the settlement."""
    planner = _planner()
    planner.record_manual_load_outcome(1, "org/model-a", "running", lane_id="planner-org_model-a")
    reason = "the worker rejected the load: no feasible GPU subset"

    async def core(action, timeout_seconds=60.0):
        planner.record_lane_action_failure(action.provider_id, action.lane_id, reason)
        return False

    planner._execute_action_core = core
    assert asyncio.run(planner._execute_action_with_confirmation(_load_action())) is False

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "failed"
    assert outcome["reason"] == reason


def test_the_executor_settles_a_confirmed_load_as_success():
    planner = _planner()
    planner.record_manual_load_outcome(1, "org/model-a", "running", lane_id="planner-org_model-a")

    async def core(action, timeout_seconds=60.0):
        return True

    planner._execute_action_core = core
    assert asyncio.run(planner._execute_action_with_confirmation(_load_action())) is True

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "succeeded"
    assert outcome["lane_id"] == "planner-org_model-a"


def test_a_load_of_the_same_model_on_another_lane_does_not_settle():
    """The operator's own load may still be waiting for the lane lock while a
    planner copy fails elsewhere: the outcome belongs to its own lane, and
    the other one must not pre-empt it."""
    planner = _planner()
    planner.record_manual_load_outcome(1, "org/model-a", "running", lane_id="planner-org_model-a")

    async def core(action, timeout_seconds=60.0):
        return False

    planner._execute_action_core = core
    asyncio.run(planner._execute_action_with_confirmation(_load_action("planner-org_model-a-2")))

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "running"
    assert outcome["lane_id"] == "planner-org_model-a"


def test_the_lane_less_endpoint_placeholder_is_not_settled_by_any_load():
    """The endpoint records "running" before the attempt knows its lane. That
    placeholder is replaced with the attempt's own lane before dispatch, so a
    load finishing in between must not settle it: the attempt may still be
    on its way to its executor."""
    planner = _planner()
    planner.record_manual_load_outcome(1, "org/model-a", "running")

    async def core(action, timeout_seconds=60.0):
        return False

    planner._execute_action_core = core
    asyncio.run(planner._execute_action_with_confirmation(_load_action()))

    outcome = planner.get_manual_load_outcome(1, "org/model-a")
    assert outcome["status"] == "running"
    assert "lane_id" not in outcome
