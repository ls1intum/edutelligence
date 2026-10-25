"""The drain: the node is cordoned at the orchestrator and its requests finish before the container is replaced.

The orchestrator is scripted (``FakeOrchestrator``): each call gets the next reply of its script, and an exception in a
script is raised from the call. Time is simulated, so the waits cost nothing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace

import pytest
from conftest import BUSY, DRAINED, NEW, NOT_BACK, RECONNECTED, UNHEALTHY, WAIT_FOR_TURN, queued

from logos_node_manager.errors import Interrupted
from logos_node_manager.orchestrator import CordonReply, NodeStatus, OrchestratorUnavailable
from logos_node_manager.state import MAX_EVENTS, FailureKind, Outcome, Phase


def unreachable(*, retryable: bool = True) -> OrchestratorUnavailable:
    return OrchestratorUnavailable("connection refused", retryable=retryable)


def notes(record, phase: str) -> list[str]:
    return [event["note"] for event in record.events if event["phase"] == phase]


def up_calls(docker) -> list[tuple]:
    return [call for call in docker.calls if call[0] == "up"]


# ---------------------------------------------------------------------- The normal way


def test_a_node_that_has_drained_is_replaced_and_the_cordon_is_given_back(
    draining_deployer, orchestrator, docker, store
):
    orchestrator.cordon_replies = [DRAINED]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert record.cordoned_at is not None
    assert record.drained_at is not None
    assert record.cordon_released_at is not None
    assert orchestrator.calls[0] == ("cordon", "run-1")
    assert orchestrator.calls[-1] == ("release", "run-1")
    assert orchestrator.count("release") == 1
    assert docker.container_info.image_id == NEW


def test_the_phases_and_notes_of_a_drained_deployment(draining_deployer, orchestrator, store):
    orchestrator.cordon_replies = [DRAINED]

    record = draining_deployer.process(queued(store, "v2"))

    assert [event["phase"] for event in record.events] == [
        "pulling",
        "draining",
        "draining",
        "draining",
        "swapping",
        "verifying",
        "verifying",
        "done",
    ]
    assert notes(record, "draining")[1:] == ["cordoned the node at the orchestrator", "the node has drained after 0 s"]
    assert notes(record, "swapping") == ["the node has drained; replacing the container"]
    assert notes(record, "verifying")[-1] == "the worker is connected to the orchestrator"


def test_the_container_is_not_replaced_before_the_node_has_drained(draining_deployer, orchestrator, docker, store):
    orchestrator.cordon_replies = [BUSY, BUSY, BUSY, DRAINED]
    asked_before_the_swap: list[int] = []
    original = docker.up

    def spy(*args, **kwargs):
        asked_before_the_swap.append(orchestrator.count("cordon"))
        return original(*args, **kwargs)

    docker.up = spy

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert asked_before_the_swap == [4]


def test_the_session_of_the_old_worker_is_saved_before_the_container_goes(
    draining_deployer, orchestrator, docker, store
):
    orchestrator.cordon_replies = [DRAINED]
    saved_before_the_swap: list[str | None] = []
    original = docker.up

    def spy(*args, **kwargs):
        saved_before_the_swap.append(store.load("run-1").session_before)
        return original(*args, **kwargs)

    docker.up = spy

    draining_deployer.process(queued(store, "v2"))

    assert saved_before_the_swap == ["session-old"]


def test_models_that_no_other_node_serves_are_recorded_and_named(draining_deployer, orchestrator, store):
    orchestrator.cordon_replies = [replace(DRAINED, sole_replica_models=("model-a", "model-b"))]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.sole_replica_models == ["model-a", "model-b"]
    assert any(
        "no other node serves model-a, model-b, so requests for them wait" in note for note in notes(record, "draining")
    )


# ---------------------------------------------------------------------- Waiting


def test_a_node_waits_for_its_turn_while_another_node_is_replaced(draining_deployer, orchestrator, docker, store):
    orchestrator.cordon_replies = [WAIT_FOR_TURN, WAIT_FOR_TURN, DRAINED]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert "waiting for its turn: node-b is being replaced" in notes(record, "draining")
    assert orchestrator.count("cordon") == 3


def test_a_node_that_never_gets_its_turn_fails_and_the_container_is_left_alone(
    draining_deployer, orchestrator, docker, store
):
    orchestrator.cordon_replies = [WAIT_FOR_TURN]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.FAILED
    assert record.failure is FailureKind.DRAIN_BLOCKED
    assert "within 120 s" in record.message
    assert "node-b is being replaced" in record.message
    assert up_calls(docker) == []
    assert docker.container_info.id == "c-old"
    assert orchestrator.count("release") == 0, "a node that never held the cordon has nothing to give back"


def test_a_node_that_runs_a_calibration_waits_and_says_why(draining_deployer, orchestrator, store):
    orchestrator.cordon_replies = [CordonReply(granted=False, reason="calibrating"), DRAINED]

    record = draining_deployer.process(queued(store, "v2"))

    assert "waiting for its turn: the node runs a calibration session" in notes(record, "draining")


def test_the_wait_for_the_drain_does_not_fill_the_record(draining_deployer, orchestrator, store):
    draining_deployer.settings = replace(draining_deployer.settings, drain_timeout_s=100_000)
    # Ten minutes of polling, with a different number of requests on every poll.
    orchestrator.cordon_replies = [replace(BUSY, in_flight_orchestrator=200 - poll) for poll in range(120)] + [DRAINED]

    record = draining_deployer.process(queued(store, "v2"))

    waiting = [note for note in notes(record, "draining") if note.startswith("waiting for the node to drain")]
    assert record.outcome is Outcome.SUCCEEDED
    assert 10 <= len(waiting) <= 21, "about one line per 30 s"
    assert len(record.events) < MAX_EVENTS
    assert waiting[0] == (
        "waiting for the node to drain: 201 request(s) (200 tracked by the orchestrator, 1 on the worker) running"
    )


def test_a_wait_that_does_not_change_is_recorded_once(draining_deployer, orchestrator, store):
    draining_deployer.settings = replace(draining_deployer.settings, drain_timeout_s=100_000)
    orchestrator.cordon_replies = [BUSY] * 100 + [DRAINED]

    record = draining_deployer.process(queued(store, "v2"))

    waiting = [note for note in notes(record, "draining") if note.startswith("waiting for the node to drain")]
    assert len(waiting) == 1


# ---------------------------------------------------------------------- Giving up


def test_a_node_that_does_not_drain_in_time_keeps_its_container_and_gives_the_cordon_back(
    draining_deployer, orchestrator, docker, store
):
    orchestrator.cordon_replies = [BUSY]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.FAILED
    assert record.failure is FailureKind.DRAIN_TIMEOUT
    assert "within 60 s" in record.message
    assert "3 request(s)" in record.message
    assert "running container was not touched" in record.message
    assert up_calls(docker) == []
    assert docker.container_info.id == "c-old"
    assert orchestrator.count("release") == 1
    assert record.cordon_released_at is not None
    assert store.load("run-1").outcome is Outcome.FAILED


def test_a_lost_cordon_is_asked_for_again_and_the_drain_starts_over(draining_deployer, orchestrator, store):
    # Granted, then the orchestrator forgets it (a restart) and another node holds it, then it is granted again.
    orchestrator.cordon_replies = [BUSY, WAIT_FOR_TURN, BUSY, DRAINED]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert "the cordon was lost; waiting for the turn of the node again" in notes(record, "draining")
    assert orchestrator.count("cordon") == 4


# ---------------------------------------------------------------------- An orchestrator that cannot be reached


def test_a_short_outage_of_the_orchestrator_does_not_skip_the_drain(draining_deployer, orchestrator, store):
    orchestrator.cordon_replies = [unreachable(), unreachable(), DRAINED]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert record.cordoned_at is not None
    assert not any("skipped" in note for note in notes(record, "swapping"))


def test_an_orchestrator_that_stays_away_is_given_up_on_and_the_deployment_goes_on(
    draining_deployer, orchestrator, docker, store, caplog
):
    orchestrator.cordon_replies = [unreachable()]

    with caplog.at_level(logging.WARNING):
        record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert notes(record, "swapping") == ["draining skipped: connection refused"]
    assert record.cordoned_at is None
    assert orchestrator.count("cordon") == 5, "asked at 0, 5, 10, 15 and 20 s, then given up on"
    assert orchestrator.count("status") == 0, "without a cordon there is no session to wait for"
    assert orchestrator.count("release") == 0


def test_an_answer_that_asking_again_cannot_change_skips_the_drain_at_once(draining_deployer, orchestrator, store):
    orchestrator.cordon_replies = [unreachable(retryable=False)]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert orchestrator.count("cordon") == 1


def test_an_orchestrator_that_disappears_during_the_drain_does_not_stop_the_deployment(
    draining_deployer, orchestrator, store
):
    orchestrator.cordon_replies = [BUSY, unreachable()]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert record.cordoned_at is not None
    assert notes(record, "swapping") == ["draining skipped: connection refused"]


# ---------------------------------------------------------------------- The cordon is given back on every ending


def test_a_rolled_back_deployment_gives_the_cordon_back_after_the_rollback(
    draining_deployer, orchestrator, docker, store
):
    docker.new_container_timeline = UNHEALTHY
    released_after_calls: list[int] = []
    original_release = orchestrator.release

    def release(deployment_id):
        released_after_calls.append(len(up_calls(docker)))
        original_release(deployment_id)

    orchestrator.release = release

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.ROLLED_BACK
    assert released_after_calls == [2], "the swap and the rollback came first"


def test_a_failed_swap_that_leaves_the_old_container_running_gives_the_cordon_back(
    draining_deployer, orchestrator, docker, store
):
    docker.up_errors = ["could not create container"]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.failure is FailureKind.SWAP_FAILED
    assert orchestrator.count("release") == 1


def test_a_release_that_fails_is_asked_again_and_does_not_change_the_outcome(draining_deployer, orchestrator, store):
    orchestrator.release_replies = [unreachable(), unreachable(), None]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert orchestrator.count("release") == 3
    assert record.cordon_released_at is not None


def test_a_release_that_never_works_is_left_to_expire(draining_deployer, orchestrator, store, caplog):
    orchestrator.release_replies = [unreachable()]

    with caplog.at_level(logging.WARNING):
        record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert "it expires" in caplog.text
    assert record.cordon_released_at is not None


def test_the_cordon_is_given_back_when_the_manager_gives_up_after_internal_errors(
    draining_deployer, orchestrator, store
):
    record = queued(store, "v2")
    record.phase = Phase.DRAINING
    record.cordoned_at = "2026-01-01T00:00:00.000000+00:00"
    record.attempts = 3

    draining_deployer.give_up(record, RuntimeError("docker does not answer"))

    assert record.outcome is Outcome.FAILED
    assert orchestrator.count("release") == 1


# ---------------------------------------------------------------------- Did the new worker come back?


def test_a_worker_that_never_shows_up_at_the_orchestrator_is_rolled_back(
    draining_deployer, orchestrator, docker, store
):
    orchestrator.status_replies = [NOT_BACK]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.ROLLED_BACK
    assert record.failure is FailureKind.VERIFY_FAILED
    assert "did not connect to the orchestrator within 30 s" in record.message
    assert docker.container_info.image_id.endswith("aaaa"), "the previous version runs again"


def test_the_old_session_does_not_count_as_the_new_worker(draining_deployer, orchestrator, store):
    old = NodeStatus(online=True, first_status_received=True, session_id="session-old")
    orchestrator.status_replies = [old, old, RECONNECTED]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert orchestrator.count("status") == 3


def test_a_new_session_without_its_first_status_is_not_enough(draining_deployer, orchestrator, store):
    orchestrator.status_replies = [replace(RECONNECTED, first_status_received=False), RECONNECTED]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert orchestrator.count("status") == 2


def test_any_session_counts_for_a_node_that_was_offline_before_the_swap(draining_deployer, orchestrator, store):
    orchestrator.cordon_replies = [replace(DRAINED, online=False, session_id=None)]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert record.session_before is None


def test_the_connection_check_is_skipped_when_the_orchestrator_cannot_be_asked(draining_deployer, orchestrator, store):
    orchestrator.status_replies = [unreachable(retryable=False)]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert any("was not checked" in note for note in notes(record, "verifying"))


def test_no_connection_check_without_a_cordon(draining_deployer, orchestrator, store):
    orchestrator.cordon_replies = [unreachable(retryable=False)]
    orchestrator.status_replies = [NOT_BACK]

    record = draining_deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert orchestrator.count("status") == 0


# ---------------------------------------------------------------------- A stop and a restart of the manager


def test_a_stop_during_the_wait_leaves_the_record_for_the_next_start(
    make_deployer, drain_settings, orchestrator, store
):
    orchestrator.cordon_replies = [BUSY]
    stop = {"now": False}

    def sleep_then_stop(seconds: float) -> None:
        stop["now"] = True

    first = make_deployer(
        settings=drain_settings, orchestrator=orchestrator, sleep=sleep_then_stop, should_stop=lambda: stop["now"]
    )
    record = queued(store, "v2")

    with pytest.raises(Interrupted):
        first.process(record)

    saved = store.load("run-1")
    assert saved.phase is Phase.DRAINING
    assert saved.cordoned_at is not None
    assert not saved.finished
    assert orchestrator.count("release") == 0, "the cordon stays: the next start goes on with the same deployment"

    orchestrator.cordon_replies = [DRAINED]
    second = make_deployer(settings=drain_settings, orchestrator=orchestrator)
    finished = second.process(store.load("run-1"))

    assert finished.outcome is Outcome.SUCCEEDED
    assert finished.cordoned_at == saved.cordoned_at, "the limit keeps counting from the first grant"


def test_a_restart_does_not_extend_the_drain_limit(make_deployer, drain_settings, orchestrator, store):
    record = queued(store, "v2")
    record.phase = Phase.DRAINING
    record.cordoned_at = "2026-01-01T00:00:00.000000+00:00"
    record.drain_requested_at = record.cordoned_at
    store.save(record)
    orchestrator.cordon_replies = [BUSY]
    # 59 of the 60 seconds were used before the manager stopped.
    later = make_deployer(
        settings=drain_settings, orchestrator=orchestrator, now=lambda: "2026-01-01T00:00:59.000000+00:00"
    )

    finished = later.process(store.load("run-1"))

    assert finished.failure is FailureKind.DRAIN_TIMEOUT
    assert orchestrator.count("cordon") == 2


def test_a_restart_does_not_extend_the_wait_for_the_turn(make_deployer, drain_settings, orchestrator, store):
    record = queued(store, "v2")
    record.phase = Phase.DRAINING
    record.drain_requested_at = "2026-01-01T00:00:00.000000+00:00"
    store.save(record)
    orchestrator.cordon_replies = [WAIT_FOR_TURN]
    later = make_deployer(
        settings=drain_settings, orchestrator=orchestrator, now=lambda: "2026-01-01T00:01:59.000000+00:00"
    )

    finished = later.process(store.load("run-1"))

    assert finished.failure is FailureKind.DRAIN_BLOCKED


# ---------------------------------------------------------------------- The key


def test_the_node_key_reaches_neither_the_record_nor_the_log(
    draining_deployer, orchestrator, drain_settings, store, caplog
):
    orchestrator.cordon_replies = [unreachable(), BUSY, DRAINED]

    with caplog.at_level(logging.DEBUG):
        record = draining_deployer.process(queued(store, "v2"))

    assert drain_settings.node_key not in caplog.text
    assert drain_settings.node_key not in json.dumps(record.to_dict())
    assert drain_settings.node_key not in repr(drain_settings)
