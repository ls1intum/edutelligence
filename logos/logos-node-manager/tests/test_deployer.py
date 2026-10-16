"""The deployment end to end, against the simulated engine."""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest
from conftest import ANCIENT, CRASHED, NEW, OLD, REPO, UNHEALTHY, queued

from logos_node_manager.deployer import Deployer
from logos_node_manager.errors import DockerError, Interrupted
from logos_node_manager.state import FailureKind, Outcome, Phase


def phases(record) -> list[str]:
    return [event["phase"] for event in record.events]


def rollback_attempts(docker) -> int:
    """How often the old container was started again: ``up`` with ``recreate``."""
    return len([call for call in docker.calls if call[0] == "up" and call[2]])


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
    docker.up_errors = [None] + ["no space left on device"] * 3

    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.FAILED
    assert record.failure is FailureKind.ROLLBACK_FAILED
    assert "no space left" in record.message
    assert "after 3 attempts" in record.message
    assert rollback_attempts(docker) == 3


def test_a_rollback_that_fails_once_is_tried_again(deployer, docker, store):
    docker.new_container_timeline = CRASHED
    # The swap works. The first attempt to restore the old container finds leftovers of the interrupted replacement.
    docker.up_errors = [None, "Error when allocating new name: Conflict. The container name is already in use"]

    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.ROLLED_BACK
    assert docker.container_info.image_id == OLD
    assert rollback_attempts(docker) == 2


def test_the_rollback_waits_longer_before_each_new_attempt(make_deployer, docker, store, clock):
    docker.new_container_timeline = CRASHED
    docker.up_errors = [None] + ["still busy"] * 3
    events = []
    up = docker.up

    def spy_up(*args, **kwargs):
        events.append("rollback up" if kwargs.get("recreate") else "up")
        return up(*args, **kwargs)

    def spy_sleep(seconds):
        events.append(seconds)
        clock.sleep(seconds)

    docker.up = spy_up
    deployer = make_deployer(sleep=spy_sleep)

    deployer.process(queued(store, "v2"))

    # Nothing else waits during a rollback whose attempts all fail, so the pauses show up between the attempts.
    assert events[events.index("rollback up") :] == ["rollback up", 5.0, "rollback up", 10.0, "rollback up"]


def test_a_stop_request_ends_the_rollback_between_two_attempts(make_deployer, docker, store):
    docker.new_container_timeline = CRASHED
    docker.up_errors = [None, "still busy"]
    stop = {"asked": False}
    up = docker.up

    def spy_up(*args, **kwargs):
        result = up(*args, **kwargs)
        if kwargs.get("recreate") and not result.ok:
            stop["asked"] = True  # the daemon is asked to stop while the first attempt fails
        return result

    docker.up = spy_up
    deployer = make_deployer(should_stop=lambda: stop["asked"])
    record = queued(store, "v2")

    with pytest.raises(Interrupted):
        deployer.process(record)

    assert store.load(record.id).phase is Phase.ROLLING_BACK
    assert rollback_attempts(docker) == 1


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


# ---------------------------------------------------------------------- Images on the host
#
# The host starts with the image that runs (OLD) and, under the name `previous`, the image of the deployment before
# it (ANCIENT). The registry has NEW under the tags `latest` and `v2`.


def everything_works(docker):
    pass


def the_release_crashes(docker):
    docker.new_container_timeline = CRASHED


def the_release_is_unhealthy(docker):
    docker.new_container_timeline = UNHEALTHY


def up_fails_and_the_old_container_stays(docker):
    docker.up_errors = ["could not create container"]


def up_fails_and_removes_the_old_container(docker):
    docker.up_errors = ["could not start container"]
    docker.failed_up_removes_container = True


def the_pull_fails(docker):
    docker.pull_error = "unauthorized: authentication required"


def the_container_already_runs_the_image(docker):
    docker.registry[f"{REPO}:latest"] = OLD


def the_rollback_fails(docker):
    docker.new_container_timeline = CRASHED
    docker.up_errors = [None] + ["no space left on device"] * 3


def there_is_no_container_yet_and_the_release_crashes(docker):
    docker.container_info = None
    docker.images.clear()
    docker.new_container_timeline = CRASHED


# tag, how the engine behaves, the images that stay on the host, and of those the ones that have no name
IMAGES_AFTER_THE_DEPLOYMENT = [
    pytest.param("v2", everything_works, {NEW, OLD}, set(), id="succeeded"),
    pytest.param("v2", the_release_crashes, {OLD}, set(), id="rolled back after a crash"),
    pytest.param("v2", the_release_is_unhealthy, {OLD}, set(), id="rolled back as unhealthy"),
    pytest.param("v2", up_fails_and_the_old_container_stays, {OLD}, set(), id="up failed, old container stays"),
    pytest.param("v2", up_fails_and_removes_the_old_container, {OLD}, set(), id="up failed, old container restored"),
    pytest.param("v2", the_pull_fails, {OLD, ANCIENT}, set(), id="pull failed"),
    pytest.param("latest", the_container_already_runs_the_image, {OLD, ANCIENT}, set(), id="unchanged"),
    pytest.param("v2", the_rollback_fails, {OLD, NEW, ANCIENT}, {ANCIENT}, id="rollback failed"),
    pytest.param("v2", there_is_no_container_yet_and_the_release_crashes, {NEW}, set(), id="first deployment failed"),
]


@pytest.mark.parametrize(("tag", "arrange", "on_the_host", "without_a_name"), IMAGES_AFTER_THE_DEPLOYMENT)
def test_no_image_stays_on_the_host_without_a_purpose(
    deployer, docker, store, tag, arrange, on_the_host, without_a_name
):
    docker.images[f"{REPO}:previous"] = ANCIENT
    arrange(docker)

    deployer.process(queued(store, tag))

    assert docker.host_images() == on_the_host
    assert docker.unnamed == without_a_name


@pytest.mark.parametrize("arrange", [everything_works, the_release_crashes])
def test_images_are_removed_only_when_the_deployment_has_ended(deployer, docker, store, arrange):
    docker.images[f"{REPO}:previous"] = ANCIENT
    arrange(docker)
    removed_at_each_inspection = []
    inspect = docker.container

    def spy():
        removed_at_each_inspection.append(list(docker.removed))
        return inspect()

    docker.container = spy

    deployer.process(queued(store, "v2"))

    assert docker.removed
    assert removed_at_each_inspection == [[]] * len(removed_at_each_inspection)


def test_the_result_is_saved_before_an_image_is_removed(deployer, docker, store):
    docker.images[f"{REPO}:previous"] = ANCIENT
    saved_outcomes = []
    remove = docker.remove_image

    def spy(image_id):
        saved_outcomes.append(store.load("run-1").outcome)
        return remove(image_id)

    docker.remove_image = spy

    deployer.process(queued(store, "v2"))

    assert saved_outcomes == [Outcome.SUCCEEDED]


def test_the_old_image_gets_its_name_just_before_its_container_is_replaced(deployer, docker, store):
    docker.images[f"{REPO}:previous"] = ANCIENT
    previous_name_points_to = {}
    pull, up = docker.pull, docker.up

    def spy_pull(tag):
        previous_name_points_to["during the pull"] = docker.images[f"{REPO}:previous"]
        return pull(tag)

    def spy_up(*args, **kwargs):
        previous_name_points_to["during up"] = docker.images[f"{REPO}:previous"]
        return up(*args, **kwargs)

    docker.pull, docker.up = spy_pull, spy_up

    deployer.process(queued(store, "v2"))

    assert previous_name_points_to == {"during the pull": ANCIENT, "during up": OLD}


def test_a_failed_pull_and_an_unchanged_container_leave_the_previous_name_alone(deployer, docker, store):
    docker.images[f"{REPO}:previous"] = ANCIENT
    docker.pull_error = "unauthorized: authentication required"
    deployer.process(queued(store, "v2", "failed-pull"))

    docker.pull_error = None
    docker.registry[f"{REPO}:latest"] = OLD
    deployer.process(queued(store, "latest", "unchanged"))

    assert docker.images[f"{REPO}:previous"] == ANCIENT
    assert not [call for call in docker.calls if call[0] in ("tag", "remove_image")]


def test_a_failed_rollback_does_not_try_to_remove_an_image(deployer, docker, store):
    docker.images[f"{REPO}:previous"] = ANCIENT
    the_rollback_fails(docker)

    record = deployer.process(queued(store, "v2"))

    assert record.failure is FailureKind.ROLLBACK_FAILED
    assert not [call for call in docker.calls if call[0] == "remove_image"]


def test_the_image_that_is_deployed_is_kept_when_the_previous_name_pointed_to_it(deployer, docker, store):
    docker.images[f"{REPO}:previous"] = NEW

    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert record.stale_image_id == NEW
    assert docker.container_info.image_id == NEW
    # The engine would refuse, but the manager must not even try to remove the image of a running container.
    assert not [call for call in docker.calls if call[0] == "remove_image"]


def test_the_previous_version_stays_even_if_no_container_runs_it(deployer, docker, store):
    # A finished record, so that only the clean-up runs. The worker container is gone, and the image that was pulled is
    # also the previous version.
    docker.container_info = None
    docker.images[f"{REPO}:previous"] = ANCIENT
    record = queued(store, "v2")
    record.phase = Phase.DONE
    record.outcome = Outcome.ROLLED_BACK
    record.started_at = record.finished_at = record.requested_at
    record.previous_image_id = record.target_image_id = OLD
    record.stale_image_id = ANCIENT

    deployer.process(record)

    assert docker.removed == [ANCIENT]
    assert OLD in docker.host_images()


def test_an_image_that_is_stale_and_was_pulled_is_removed_once_after_a_rollback(deployer, docker, store):
    docker.images[f"{REPO}:previous"] = NEW
    docker.new_container_timeline = CRASHED

    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.ROLLED_BACK
    assert [call for call in docker.calls if call[0] == "remove_image"] == [("remove_image", NEW)]
    assert docker.host_images() == {OLD}


def test_a_stale_image_is_removed_together_with_its_release_tag(deployer, docker, store):
    docker.images[f"{REPO}:previous"] = ANCIENT
    docker.images[f"{REPO}:v0"] = ANCIENT

    deployer.process(queued(store, "v2"))

    assert docker.removed == [ANCIENT]
    assert f"{REPO}:v0" not in docker.images


def test_a_stale_image_with_several_names_stays_and_the_result_is_unchanged(deployer, docker, store):
    docker.images[f"{REPO}:previous"] = ANCIENT
    docker.images[f"{REPO}:v0"] = ANCIENT
    docker.images[f"{REPO}:v00"] = ANCIENT

    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert ANCIENT in docker.host_images()


def test_a_clean_up_that_fails_does_not_change_the_result(deployer, docker, store, caplog):
    docker.images[f"{REPO}:previous"] = ANCIENT

    def broken(image_id):
        raise DockerError("docker rmi failed: the engine is gone")

    docker.remove_image = broken

    with caplog.at_level(logging.WARNING):
        record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert store.load(record.id).outcome is Outcome.SUCCEEDED
    assert "clean-up failed" in caplog.text


def test_nothing_is_removed_when_the_clean_up_cannot_see_which_image_runs(deployer, docker, store):
    docker.images[f"{REPO}:previous"] = ANCIENT
    inspect = docker.container

    def unreachable():
        if store.load("run-1").finished:
            raise DockerError("docker inspect failed: the engine is gone")
        return inspect()

    docker.container = unreachable

    record = deployer.process(queued(store, "v2"))

    assert record.outcome is Outcome.SUCCEEDED
    assert docker.removed == []


@pytest.mark.parametrize(
    ("arrange", "log_line"),
    [
        (everything_works, "Deployment run-1: clean-up finished, removed 222222222222"),
        (the_pull_fails, "Deployment run-1: clean-up finished, nothing removed"),
    ],
)
def test_the_log_says_what_the_clean_up_removed(deployer, docker, store, caplog, arrange, log_line):
    docker.images[f"{REPO}:previous"] = ANCIENT
    arrange(docker)

    with caplog.at_level(logging.INFO):
        deployer.process(queued(store, "v2"))

    assert log_line in caplog.text


# ---------------------------------------------------------------------- Restart in the middle of a deployment


class Killed(Exception):
    """Stands for the manager process dying in the middle of a step: the call never returns."""


@pytest.mark.parametrize("operation", ["tag", "up"])
def test_a_stop_while_the_container_is_replaced_loses_no_image(deployer, docker, store, operation):
    docker.images[f"{REPO}:previous"] = ANCIENT
    original = getattr(docker, operation)
    attempts = []

    def die_on_the_first_call(*args, **kwargs):
        attempts.append(operation)
        if len(attempts) == 1:
            raise Killed(operation)
        return original(*args, **kwargs)

    setattr(docker, operation, die_on_the_first_call)
    record = queued(store, "v2")

    with pytest.raises(Killed):
        deployer.process(record)
    result = deployer.process(store.load(record.id))

    assert result.outcome is Outcome.SUCCEEDED
    assert docker.removed == [ANCIENT]
    assert docker.images[f"{REPO}:previous"] == OLD
    assert docker.host_images() == {NEW, OLD}


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
