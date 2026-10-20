"""The loop that takes deployments from the state directory."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace

from conftest import OLD

from logos_node_manager.daemon import MAX_ATTEMPTS, Daemon
from logos_node_manager.errors import DockerError, Interrupted
from logos_node_manager.state import Deployment, FailureKind, Outcome, Phase


class ScriptedDeployer:
    """Stands in for the real deployer: finishes every deployment, or fails in a way the test chose."""

    def __init__(self, store, stop, *, error: Exception | None = None, fail_ids: tuple[str, ...] = ()) -> None:
        self.store = store
        self.stop = stop
        self.error = error
        self.fail_ids = fail_ids
        self.seen: list[str] = []

    def process(self, deployment: Deployment) -> Deployment:
        self.seen.append(deployment.id)
        if deployment.id in self.fail_ids and self.error is not None:
            if isinstance(self.error, Interrupted):
                self.stop.set()
            raise self.error
        deployment.phase = Phase.DONE
        deployment.outcome = Outcome.SUCCEEDED
        self.store.save(deployment)
        return deployment

    def give_up(self, deployment: Deployment, error: Exception) -> None:
        deployment.phase = Phase.DONE
        deployment.outcome = Outcome.FAILED
        deployment.failure = FailureKind.INTERNAL_ERROR
        deployment.message = f"the node manager failed {deployment.attempts} times: {error}"
        self.store.save(deployment)


def queue(store, deployment_id: str, requested_at: str) -> None:
    store.submit(Deployment(id=deployment_id, tag="v2", requested_at=requested_at))


def wait_for(predicate, timeout_s: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def start(settings, store, deployer, stop, **kwargs):
    daemon = Daemon(replace(settings, loop_interval_s=0.02), store, deployer, stop, retry_delay_s=0, **kwargs)
    thread = threading.Thread(target=daemon.run, daemon=True)
    thread.start()
    return thread


def test_deployments_are_processed_oldest_first_and_then_the_loop_waits(settings, store):
    stop = threading.Event()
    deployer = ScriptedDeployer(store, stop)
    queue(store, "second", "2026-01-01T00:00:02")
    queue(store, "first", "2026-01-01T00:00:01")

    thread = start(settings, store, deployer, stop)
    try:
        assert wait_for(lambda: store.next_unfinished() is None)
        queue(store, "third", "2026-01-01T00:00:03")
        assert wait_for(lambda: len(deployer.seen) == 3)
    finally:
        stop.set()
        thread.join(timeout=5)

    assert deployer.seen == ["first", "second", "third"]
    assert not thread.is_alive()


def test_a_file_with_an_invalid_name_does_not_stop_the_loop(settings, store):
    stop = threading.Event()
    deployer = ScriptedDeployer(store, stop)
    queue(store, "fine", "2026-01-01T00:00:01")
    (store.deployments_dir / "run 1.json").write_text("{}", encoding="utf-8")

    thread = start(settings, store, deployer, stop)
    try:
        assert wait_for(lambda: deployer.seen == ["fine"], timeout_s=3)
        assert thread.is_alive()
    finally:
        stop.set()
        thread.join(timeout=5)


def test_the_heartbeat_is_written_from_the_start(settings, store):
    stop = threading.Event()

    thread = start(settings, store, ScriptedDeployer(store, stop), stop)
    try:
        assert wait_for(lambda: store.heartbeat_age() is not None)
    finally:
        stop.set()
        thread.join(timeout=5)


def test_a_deployment_that_keeps_failing_unexpectedly_is_marked_failed_and_the_loop_goes_on(settings, store):
    stop = threading.Event()
    deployer = ScriptedDeployer(store, stop, error=RuntimeError("docker is gone"), fail_ids=("broken",))
    queue(store, "broken", "2026-01-01T00:00:01")
    queue(store, "fine", "2026-01-01T00:00:02")

    thread = start(settings, store, deployer, stop)
    try:
        assert wait_for(lambda: store.next_unfinished() is None)
    finally:
        stop.set()
        thread.join(timeout=5)

    broken = store.load("broken")
    assert broken.outcome is Outcome.FAILED
    assert broken.failure is FailureKind.INTERNAL_ERROR
    assert broken.attempts == MAX_ATTEMPTS
    assert "docker is gone" in broken.message
    assert deployer.seen.count("broken") == MAX_ATTEMPTS
    assert store.load("fine").outcome is Outcome.SUCCEEDED


# ---------------------------------------------------------------------- Giving up after repeated errors


def engine_fails(docker, store, deployment_id, phase, times):
    """After the swap, the next ``times`` inspections made in ``phase`` fail like an engine that does not answer."""
    inspect = docker.container
    left = [times]

    def container():
        record = store.load(deployment_id)
        replaced = any(call[0] == "up" for call in docker.calls)
        if left[0] and replaced and record is not None and record.phase is phase:
            left[0] -= 1
            raise DockerError("docker inspect failed: the engine did not answer")
        return inspect()

    docker.container = container


def run_to_the_end(settings, store, deployer, deployment_id):
    stop = threading.Event()
    thread = start(settings, store, deployer, stop)
    try:
        assert wait_for(lambda: store.load(deployment_id).finished, timeout_s=5)
    finally:
        stop.set()
        thread.join(timeout=5)
    return store.load(deployment_id)


def test_repeated_errors_while_the_new_container_is_checked_roll_the_worker_back(
    settings, store, docker, make_deployer
):
    queue(store, "d1", "2026-01-01T00:00:01")
    engine_fails(docker, store, "d1", Phase.VERIFYING, MAX_ATTEMPTS)

    record = run_to_the_end(settings, store, make_deployer(), "d1")

    assert record.outcome is Outcome.ROLLED_BACK
    assert record.failure is FailureKind.INTERNAL_ERROR
    assert f"failed {MAX_ATTEMPTS} times" in record.message
    assert docker.container_info.image_id == OLD
    # The release that was never checked does not stay on the host.
    assert docker.host_images() == {OLD}


def test_repeated_errors_right_after_the_swap_roll_the_worker_back(settings, store, docker, make_deployer):
    queue(store, "d1", "2026-01-01T00:00:01")
    engine_fails(docker, store, "d1", Phase.SWAPPING, MAX_ATTEMPTS)

    record = run_to_the_end(settings, store, make_deployer(), "d1")

    assert record.outcome is Outcome.ROLLED_BACK
    assert record.failure is FailureKind.INTERNAL_ERROR
    assert docker.container_info.image_id == OLD


def test_errors_that_are_overcome_do_not_add_up_across_phases(settings, store, docker, make_deployer):
    queue(store, "d1", "2026-01-01T00:00:01")
    pull = docker.pull
    pulls = []

    def pull_that_crashes_once(tag):
        pulls.append(tag)
        if len(pulls) == 1:
            raise RuntimeError("the pull crashed")
        return pull(tag)

    docker.pull = pull_that_crashes_once
    engine_fails(docker, store, "d1", Phase.SWAPPING, 1)
    engine_fails(docker, store, "d1", Phase.VERIFYING, 1)

    record = run_to_the_end(settings, store, make_deployer(), "d1")

    # One error in each of three phases is as many as MAX_ATTEMPTS, but none of them repeated in its phase.
    assert record.outcome is Outcome.SUCCEEDED
    assert docker.container_info.image_id != OLD


def test_the_rollback_after_repeated_errors_gets_attempts_of_its_own(settings, store, docker, make_deployer):
    queue(store, "d1", "2026-01-01T00:00:01")
    engine_fails(docker, store, "d1", Phase.VERIFYING, MAX_ATTEMPTS)
    engine_fails(docker, store, "d1", Phase.ROLLING_BACK, MAX_ATTEMPTS - 1)

    record = run_to_the_end(settings, store, make_deployer(), "d1")

    assert record.outcome is Outcome.ROLLED_BACK
    assert docker.container_info.image_id == OLD


def test_a_rollback_that_keeps_failing_ends_as_a_failed_rollback_and_keeps_every_image(
    settings, store, docker, make_deployer
):
    queue(store, "d1", "2026-01-01T00:00:01")
    engine_fails(docker, store, "d1", Phase.VERIFYING, MAX_ATTEMPTS)
    engine_fails(docker, store, "d1", Phase.ROLLING_BACK, MAX_ATTEMPTS)

    record = run_to_the_end(settings, store, make_deployer(), "d1")

    assert record.outcome is Outcome.FAILED
    assert record.failure is FailureKind.ROLLBACK_FAILED
    assert "rollback failed too" in record.message
    assert docker.removed == []


def test_repeated_errors_after_the_swap_without_a_previous_version_fail_the_deployment(
    settings, store, docker, make_deployer
):
    docker.container_info = None
    docker.images.clear()
    queue(store, "d1", "2026-01-01T00:00:01")
    engine_fails(docker, store, "d1", Phase.VERIFYING, MAX_ATTEMPTS)

    record = run_to_the_end(settings, store, make_deployer(), "d1")

    assert record.outcome is Outcome.FAILED
    assert record.failure is FailureKind.INTERNAL_ERROR
    assert "no previous version" in record.message


def test_repeated_errors_before_the_swap_fail_the_deployment_and_leave_the_worker_alone(
    settings, store, docker, make_deployer
):
    queue(store, "d1", "2026-01-01T00:00:01")

    def crashing_pull(tag):
        raise RuntimeError("the pull crashed")

    docker.pull = crashing_pull

    record = run_to_the_end(settings, store, make_deployer(), "d1")

    assert record.outcome is Outcome.FAILED
    assert record.failure is FailureKind.INTERNAL_ERROR
    assert docker.container_info.id == "c-old"
    assert not [call for call in docker.calls if call[0] == "up"]


def test_the_deployment_after_a_recovery_starts_from_the_restored_version(settings, store, docker, make_deployer):
    queue(store, "d1", "2026-01-01T00:00:01")
    engine_fails(docker, store, "d1", Phase.VERIFYING, MAX_ATTEMPTS)
    deployer = make_deployer()
    run_to_the_end(settings, store, deployer, "d1")
    queue(store, "d2", "2026-01-01T00:00:02")

    record = run_to_the_end(settings, store, deployer, "d2")

    assert record.previous_image_id == OLD
    assert record.outcome is Outcome.SUCCEEDED


def test_an_interrupted_deployment_stays_unfinished_for_the_next_start(settings, store):
    stop = threading.Event()
    deployer = ScriptedDeployer(store, stop, error=Interrupted(), fail_ids=("cut",))
    queue(store, "cut", "2026-01-01T00:00:01")

    thread = start(settings, store, deployer, stop)
    thread.join(timeout=5)

    assert not thread.is_alive()
    record = store.load("cut")
    assert not record.finished
    assert record.attempts == 0


def test_the_start_is_logged_with_the_docker_versions_and_missing_files(settings, store, docker, caplog):
    stop = threading.Event()
    stop.set()
    daemon = Daemon(settings, store, ScriptedDeployer(store, stop), stop, docker=docker)

    with caplog.at_level(logging.INFO):
        daemon.run()

    assert "Node manager" in caplog.text
    assert "engine fake, compose fake" in caplog.text
    assert "docker-compose.yml does not exist" in caplog.text
