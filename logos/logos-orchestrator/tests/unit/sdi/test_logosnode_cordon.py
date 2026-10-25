"""What the scheduling facade tells the scheduler and the node maintenance service about a worker being replaced."""

from __future__ import annotations

from logos.logosnode_registry import LogosNodeRuntimeRegistry
from logos.queue import PriorityQueueManager
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade


def _facade(registry: LogosNodeRuntimeRegistry | None = None) -> LogosNodeSchedulingDataFacade:
    return LogosNodeSchedulingDataFacade(PriorityQueueManager(), None, runtime_registry=registry)


def test_tracked_requests_are_counted_per_worker():
    facade = _facade()
    facade._request_tracking = {
        "req-1": {"provider_id": 1},
        "req-2": {"provider_id": 1},
        "req-3": {"provider_id": 2},
    }

    assert facade.count_tracked_requests(1) == 2
    assert facade.count_tracked_requests(2) == 1
    assert facade.count_tracked_requests(3) == 0


def test_a_request_counts_from_its_scheduling_until_it_completes():
    facade = _facade()
    facade._request_tracking["req-1"] = {"provider_id": 1}
    assert facade.count_tracked_requests(1) == 1

    facade._request_tracking.pop("req-1")
    assert facade.count_tracked_requests(1) == 0


def test_a_worker_is_cordoned_when_the_registry_says_so():
    registry = LogosNodeRuntimeRegistry()
    registry.cordon_check = lambda provider_id: provider_id == 4
    facade = _facade(registry)

    assert facade.is_provider_cordoned(4) is True
    assert facade.is_provider_cordoned(5) is False


def test_nothing_is_cordoned_without_a_registry():
    assert _facade(None).is_provider_cordoned(1) is False
