"""When is a container up?"""

from __future__ import annotations

import pytest
from conftest import CRASHED, NEW, OLD, UNHEALTHY

from logos_node_manager.errors import Interrupted
from logos_node_manager.verify import verify_container


def check(docker, settings, clock, *, expected=NEW, timeout_s=60.0, **kwargs):
    return verify_container(
        docker, settings, expected_image_id=expected, timeout_s=timeout_s, clock=clock, sleep=clock.sleep, **kwargs
    )


@pytest.fixture
def started(docker):
    """A freshly created container of the new image."""
    docker.pull("v2")
    docker.up("v2")
    return docker


def test_a_container_that_becomes_healthy_and_stays_so_passes(started, settings, clock):
    assert check(started, settings, clock).ok
    # The stability window is 10 s with a 5 s poll: the check waited, it did not return at the first healthy sample.
    assert clock.now >= settings.stability_window_s


def test_a_container_that_never_becomes_healthy_times_out(started, settings, clock):
    started.new_container_timeline = [{"health": "starting"}]
    started.up("v2", recreate=True)

    result = check(started, settings, clock, timeout_s=30)

    assert not result.ok
    assert "not healthy after 30 s" in result.reason


def test_an_unhealthy_container_fails_at_once(started, settings, clock):
    started.new_container_timeline = UNHEALTHY
    started.up("v2", recreate=True)

    result = check(started, settings, clock)

    assert not result.ok
    assert "unhealthy" in result.reason
    assert clock.now < settings.stability_window_s


def test_a_container_that_exited_fails(started, settings, clock):
    started.new_container_timeline = CRASHED
    started.up("v2", recreate=True)

    assert "exited with code 1" in check(started, settings, clock).reason


def test_a_container_that_restarted_fails_even_if_it_looks_fine_now(started, settings, clock):
    started.new_container_timeline = [{"health": "healthy", "restart_count": 2}]
    started.up("v2", recreate=True)

    assert "restarted 2 time(s)" in check(started, settings, clock).reason


def test_a_missing_container_fails(docker, settings, clock):
    docker.container_info = None

    assert "does not exist" in check(docker, settings, clock).reason


def test_a_container_of_another_image_fails(started, settings, clock):
    assert "unexpected image" in check(started, settings, clock, expected=OLD).reason


def test_a_container_without_a_health_check_passes_once_it_has_run_for_the_window(started, settings, clock):
    started.new_container_timeline = [{"health": None}]
    started.up("v2", recreate=True)

    assert check(started, settings, clock).ok
    assert clock.now >= settings.stability_window_s


def test_the_stability_window_restarts_when_the_container_stops_being_healthy(started, settings, clock):
    # Healthy, then starting again, then healthy for good: only the last stretch counts.
    started.new_container_timeline = [{"health": "healthy"}, {"health": "starting"}, {"health": "healthy"}]
    started.up("v2", recreate=True)

    assert check(started, settings, clock).ok
    assert clock.now >= 2 * 5 + settings.stability_window_s


def test_a_stop_request_interrupts_the_wait(started, settings, clock):
    with pytest.raises(Interrupted):
        check(started, settings, clock, should_stop=lambda: True)
