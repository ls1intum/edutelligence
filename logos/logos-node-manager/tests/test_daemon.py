"""The loop that takes deployments from the state directory."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace

from logos_node_manager.daemon import MAX_ATTEMPTS, Daemon
from logos_node_manager.errors import Interrupted
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
