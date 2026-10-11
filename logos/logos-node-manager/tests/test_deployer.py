"""The deployment end to end, against the simulated engine."""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest
from conftest import ANCIENT, CRASHED, NEW, OLD, REPO, UNHEALTHY, queued

from logos_node_manager.deployer import Deployer
from logos_node_manager.errors import Interrupted
from logos_node_manager.state import FailureKind, Outcome, Phase


def phases(record) -> list[str]:
    return [event["phase"] for event in record.events]


def test_a_healthy_release_replaces_the_container(deployer, docker, store):
    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert record.failure is None
    assert record.phase is Phase.DONE
    assert docker.container_info.image_id == NEW
    assert record.target_image_id == NEW
    assert record.previous_image_id == OLD
    assert phases(record) == ["pulling", "draining", "swapping", "verifying", "done"]
    assert store.load(record.id).outcome is Outcome.SUCCEEDED


def test_the_previous_version_is_kept_under_its_own_name(deployer, docker, store):
    deployer.process(queued(store, "v2"))

    assert docker.images[f"{REPO}:previous"] == OLD


def test_the_image_from_two_deployments_ago_is_removed_after_a_success(deployer, docker, store):
    docker.images[f"{REPO}:previous"] = ANCIENT

    record = deployer.process(queued(store, "v2"))

    assert record.stale_image_id == ANCIENT
    assert docker.removed == [ANCIENT]
    assert docker.images[f"{REPO}:previous"] == OLD


def test_no_image_is_removed_when_the_deployment_does_not_succeed(deployer, docker, store):
    docker.images[f"{REPO}:previous"] = ANCIENT
    docker.new_container_timeline = CRASHED

    deployer.process(queued(store, "v2"))

    assert docker.removed == []


def test_nothing_changes_when_the_container_already_runs_the_image(deployer, docker, store):
    docker.registry[f"{REPO}:latest"] = OLD

    record = deployer.process(queued(store, "latest"))

    assert record.outcome is Outcome.UNCHANGED
    assert docker.container_info.id == "c-old"
    assert "verifying" not in phases(record)


def test_a_stopped_container_that_compose_starts_is_verified(deployer, docker, store):
    docker.registry[f"{REPO}:latest"] = OLD
    docker.container_info = replace(docker.container_info, running=False, status="exited")

    record = deployer.process(queued(store, "latest"))

    assert record.outcome is Outcome.SUCCEEDED
    assert docker.container_info.id == "c-old"
    assert "verifying" in phases(record)


def test_a_failed_pull_leaves_the_running_container_alone(deployer, docker, store):
    docker.pull_error = "unauthorized: authentication required"

    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.FAILED
    assert record.failure is FailureKind.PULL_FAILED
    assert "unauthorized" in record.message
    assert docker.container_info.id == "c-old"
    assert not [call for call in docker.calls if call[0] == "up"]


def test_a_tag_that_does_not_exist_fails_the_pull(deployer, docker, store):
    record = deployer.process(queued(store, "nope"))

    assert record.failure is FailureKind.PULL_FAILED
    assert docker.container_info.image_id == OLD


def test_a_failing_up_that_left_the_old_container_running_is_not_rolled_back(deployer, docker, store):
    docker.up_errors = ["could not create container"]

    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.FAILED
    assert record.failure is FailureKind.SWAP_FAILED
    assert "still running" in record.message
    assert [call for call in docker.calls if call[0] == "up"] == [("up", "v2", False, False)]


def test_a_failing_up_that_removed_the_old_container_restores_it(deployer, docker, store):
    docker.up_errors = ["could not start container"]
    docker.failed_up_removes_container = True

    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.ROLLED_BACK
    assert record.failure is FailureKind.SWAP_FAILED
    assert docker.container_info.image_id == OLD


def test_an_unhealthy_release_is_rolled_back_to_the_previous_image(deployer, docker, store):
    docker.new_container_timeline = UNHEALTHY

    record = deployer.process(queued(store, "latest"))

    assert record.outcome is Outcome.ROLLED_BACK
    assert record.failure is FailureKind.VERIFY_FAILED
    assert "unhealthy" in record.message
    assert docker.container_info.image_id == OLD
    # `latest` pointed to the new image after the pull. The rollback must point it at the old one again.
    assert docker.images[f"{REPO}:latest"] == OLD
    # The restart used the local image: a pull would fetch the bad release again.
    assert ("up", "latest", True, True) in docker.calls


def test_the_log_of_a_crashed_container_is_saved_before_the_rollback_removes_it(deployer, docker, store):
    docker.new_container_timeline = CRASHED
    docker.logs = "Traceback: the new release cannot import its model"

    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.ROLLED_BACK
    assert "cannot import its model" in record.failure_logs
    assert "exited with code 1" in record.message


def test_a_container_that_restarts_fails_the_check_even_if_it_looks_healthy_now(deployer, docker, store):
    docker.new_container_timeline = [{"health": "healthy", "restart_count": 1}]

    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.ROLLED_BACK
    assert "restarted" in record.message


def test_a_failed_rollback_is_reported_as_failed(deployer, docker, store):
    docker.new_container_timeline = CRASHED
    docker.up_errors = [None, "no space left on device"]

    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.FAILED
    assert record.failure is FailureKind.ROLLBACK_FAILED
    assert "no space left" in record.message


def test_a_first_deployment_has_nothing_to_roll_back_to(deployer, docker, store):
    docker.container_info = None
    docker.images.clear()
    docker.new_container_timeline = CRASHED

    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.FAILED
    assert record.failure is FailureKind.VERIFY_FAILED
    assert "no previous version" in record.message
    assert record.previous_image_id is None


def test_a_first_deployment_that_works_succeeds(deployer, docker, store):
    docker.container_info = None
    docker.images.clear()

    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert docker.container_info.image_id == NEW


def test_the_drain_phase_is_passed_through_and_warns_when_enabled(settings, docker, store, clock, caplog):
    deployer = Deployer(replace(settings, drain_enabled=True), docker, store, clock=clock, sleep=clock.sleep)

    with caplog.at_level(logging.WARNING):
        record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert "Draining is not implemented" in caplog.text


# ---------------------------------------------------------------------- Restart in the middle of a deployment


def test_a_stop_request_keeps_the_phase_for_the_next_start(make_deployer, store):
    seen = iter([False, True])
    deployer = make_deployer(should_stop=lambda: next(seen))
    record = queued(store, "v2")

    with pytest.raises(Interrupted):
        deployer.process(record)

    saved = store.load(record.id)
    assert saved.phase is Phase.PULLING
    assert saved.outcome is None


def test_a_record_saved_in_the_swapping_phase_continues_after_a_restart(deployer, docker, store):
    record = queued(store, "v2")
    docker.pull("v2")
    record.phase = Phase.SWAPPING
    record.previous_container_id = "c-old"
    record.previous_running = True
    record.previous_image_id = OLD
    record.previous_image_ref = f"{REPO}:latest"
    record.target_image_ref = f"{REPO}:v2"
    record.target_image_id = NEW

    result = deployer.process(record)

    assert result.outcome is Outcome.SUCCEEDED
    assert docker.container_info.image_id == NEW


def test_a_swap_that_finished_before_the_stop_is_not_done_twice(deployer, docker, store):
    record = queued(store, "v2")
    docker.pull("v2")
    docker.up("v2")
    created = docker.container_info.id
    record.phase = Phase.SWAPPING
    record.previous_container_id = "c-old"
    record.previous_running = True
    record.previous_image_id = OLD
    record.previous_image_ref = f"{REPO}:latest"
    record.target_image_ref = f"{REPO}:v2"
    record.target_image_id = NEW

    result = deployer.process(record)

    assert result.outcome is Outcome.SUCCEEDED
    assert docker.container_info.id == created
    assert len([call for call in docker.calls if call[0] == "up"]) == 1


def test_a_record_saved_in_the_rolling_back_phase_finishes_the_rollback(deployer, docker, store):
    docker.pull("v2")
    docker.up("v2")
    record = queued(store, "v2")
    record.phase = Phase.ROLLING_BACK
    record.failure = FailureKind.VERIFY_FAILED
    record.message = "the container exited with code 1"
    record.previous_container_id = "c-old"
    record.previous_image_id = OLD
    record.previous_image_ref = f"{REPO}:latest"

    result = deployer.process(record)

    assert result.outcome is Outcome.ROLLED_BACK
    assert docker.container_info.image_id == OLD
