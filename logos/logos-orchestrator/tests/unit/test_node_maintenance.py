"""The cordon a node manager holds while it replaces a worker's container.

The service keeps one lease per node and at most one lease in the cluster. A node counts as drained when neither the
orchestrator nor the worker sees a request on it for the settle time. A lease that its manager stops renewing expires.
"""

from __future__ import annotations

import pytest

from logos.logosnode_registry import LogosNodeRuntimeRegistry
from logos.node_maintenance import NodeMaintenance

TTL_S = 600.0
SETTLE_S = 10.0


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeRegistry:
    """The few things of the registry that the service reads."""

    def __init__(self) -> None:
        self.nodes: dict[int, dict] = {}

    def add(
        self,
        provider_id: int,
        name: str,
        models: list[str],
        *,
        lanes: list[dict] | None = None,
        online: bool = True,
        calibrating: bool = False,
        first_status: bool = True,
    ) -> None:
        self.nodes[provider_id] = {
            "name": name,
            "models": models,
            "lanes": lanes or [],
            "online": online,
            "calibrating": calibrating,
            "first_status": first_status,
            "session_id": f"session-{provider_id}",
        }

    def active_provider_ids(self) -> list[int]:
        return list(self.nodes)

    def is_provider_online(self, provider_id: int, stale_after_seconds: int = 30) -> bool:
        node = self.nodes.get(provider_id)
        return bool(node and node["online"])

    def has_received_first_status(self, provider_id: int) -> bool:
        node = self.nodes.get(provider_id)
        return bool(node and node["first_status"])

    def is_calibrating(self, provider_id: int) -> bool:
        node = self.nodes.get(provider_id)
        return bool(node and node["calibrating"])

    def peek_runtime_snapshot(self, provider_id: int) -> dict | None:
        node = self.nodes.get(provider_id)
        if node is None:
            return None
        return {
            "worker_id": node["name"],
            "session_id": node["session_id"],
            "capabilities_models": node["models"],
            "runtime": {"lanes": node["lanes"]},
        }


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def registry() -> FakeRegistry:
    fake = FakeRegistry()
    fake.add(1, "node-a", ["model-a", "model-shared"])
    fake.add(2, "node-b", ["model-b", "model-shared"])
    return fake


@pytest.fixture
def maintenance(registry: FakeRegistry, clock: FakeClock) -> NodeMaintenance:
    return NodeMaintenance(registry, ttl_s=TTL_S, settle_s=SETTLE_S, clock=clock)


def _busy_lane(active: int = 1, queue: float = 0.0, running: float = 0.0) -> dict:
    return {
        "lane_id": "lane-1",
        "model": "model-a",
        "active_requests": active,
        "backend_metrics": {"queue_waiting": queue, "requests_running": running},
    }


# ── the lease ────────────────────────────────────────────────────────────────


def test_an_idle_node_gets_the_lease_and_is_cordoned(maintenance):
    answer = maintenance.request(1, "d1")

    assert answer["status"] == "granted"
    assert maintenance.is_cordoned(1)
    assert not maintenance.is_cordoned(2)


def test_the_lease_is_idempotent_for_the_same_deployment(maintenance, clock):
    maintenance.request(1, "d1")
    clock.advance(6)
    first = maintenance.request(1, "d1")
    clock.advance(6)
    second = maintenance.request(1, "d1")

    # The idle clock keeps running across repeated calls instead of starting over.
    assert first["idle_for_s"] == pytest.approx(6)
    assert second["idle_for_s"] == pytest.approx(12)


def test_a_new_deployment_of_the_same_node_takes_the_lease_over(maintenance, clock):
    maintenance.request(1, "d1")
    clock.advance(20)

    answer = maintenance.request(1, "d2")

    assert answer["status"] == "granted"
    assert answer["drained"] is False
    assert maintenance.release(1, "d1") == {"status": "held_by_other_deployment"}
    assert maintenance.release(1, "d2") == {"status": "released"}


def test_a_second_node_is_denied_while_the_first_is_cordoned(maintenance):
    maintenance.request(1, "d1")

    denied = maintenance.request(2, "d2")

    assert denied == {"status": "denied", "reason": "another_node_in_maintenance", "holder": "node-a"}
    assert not maintenance.is_cordoned(2)


def test_the_second_node_gets_the_lease_once_the_first_released_it(maintenance):
    maintenance.request(1, "d1")
    maintenance.release(1, "d1")

    assert maintenance.request(2, "d2")["status"] == "granted"
    assert maintenance.request(1, "d3")["status"] == "denied"


def test_a_calibrating_node_gets_no_lease(maintenance, registry):
    registry.nodes[1]["calibrating"] = True

    assert maintenance.request(1, "d1") == {"status": "denied", "reason": "calibrating"}
    assert not maintenance.is_cordoned(1)


def test_an_unknown_node_is_not_cordoned(maintenance):
    assert not maintenance.is_cordoned(99)


# ── expiry ───────────────────────────────────────────────────────────────────


def test_a_lease_expires_when_its_manager_stops_calling(maintenance, clock):
    maintenance.request(1, "d1")

    clock.advance(TTL_S + 1)

    assert not maintenance.is_cordoned(1)
    assert maintenance.request(2, "d2")["status"] == "granted"


def test_status_calls_keep_the_lease_alive(maintenance, clock):
    maintenance.request(1, "d1")
    for _ in range(3):
        clock.advance(TTL_S - 1)
        assert maintenance.status(1, "d1")["status"] == "leased"

    assert maintenance.is_cordoned(1)


def test_a_status_call_of_another_deployment_does_not_keep_the_lease_alive(maintenance, clock):
    maintenance.request(1, "d1")
    clock.advance(TTL_S - 1)
    assert maintenance.status(1, "other")["status"] == "no_lease"
    clock.advance(2)

    assert not maintenance.is_cordoned(1)


# ── release ──────────────────────────────────────────────────────────────────


def test_release_ends_the_cordon_and_tells_the_scheduler(maintenance):
    released: list[int] = []
    maintenance.on_released = released.append
    maintenance.request(1, "d1")

    assert maintenance.release(1, "d1") == {"status": "released"}

    assert not maintenance.is_cordoned(1)
    assert released == [1]


def test_releasing_twice_is_harmless(maintenance):
    maintenance.request(1, "d1")
    maintenance.release(1, "d1")

    assert maintenance.release(1, "d1") == {"status": "no_lease"}


def test_only_the_holding_deployment_can_release(maintenance):
    maintenance.request(1, "d1")

    assert maintenance.release(1, "d2") == {"status": "held_by_other_deployment"}
    assert maintenance.is_cordoned(1)


def test_a_failing_notification_does_not_undo_the_release(maintenance):
    def broken(_provider_id: int) -> None:
        raise RuntimeError("scheduler is gone")

    maintenance.on_released = broken
    maintenance.request(1, "d1")

    assert maintenance.release(1, "d1") == {"status": "released"}
    assert not maintenance.is_cordoned(1)


# ── drained ──────────────────────────────────────────────────────────────────


def test_an_idle_node_counts_as_drained_only_after_the_settle_time(maintenance, clock):
    assert maintenance.request(1, "d1")["drained"] is False

    clock.advance(SETTLE_S - 1)
    assert maintenance.status(1, "d1")["drained"] is False

    clock.advance(1)
    answer = maintenance.status(1, "d1")
    assert answer["drained"] is True
    assert answer["in_flight"] == {"orchestrator": 0, "worker": 0}


def test_a_request_tracked_by_the_orchestrator_blocks_the_drain(maintenance, clock):
    tracked = {1: 1}
    maintenance.tracked_requests = lambda provider_id: tracked.get(provider_id, 0)
    maintenance.request(1, "d1")

    clock.advance(60)
    busy = maintenance.status(1, "d1")
    assert busy["drained"] is False
    assert busy["in_flight"]["orchestrator"] == 1

    tracked[1] = 0
    assert maintenance.status(1, "d1")["drained"] is False
    clock.advance(SETTLE_S)
    assert maintenance.status(1, "d1")["drained"] is True


@pytest.mark.parametrize(
    "lane",
    [
        pytest.param(_busy_lane(active=1), id="active-request"),
        pytest.param(_busy_lane(active=0, running=2), id="running-in-the-engine"),
        pytest.param(_busy_lane(active=0, queue=3), id="waiting-in-the-engine"),
    ],
)
def test_a_request_on_the_worker_blocks_the_drain(maintenance, registry, clock, lane):
    registry.nodes[1]["lanes"] = [lane]
    maintenance.request(1, "d1")

    clock.advance(60)

    answer = maintenance.status(1, "d1")
    assert answer["drained"] is False
    assert answer["in_flight"]["worker"] >= 1


def test_a_new_request_restarts_the_settle_time(maintenance, registry, clock):
    maintenance.request(1, "d1")
    clock.advance(SETTLE_S - 1)
    registry.nodes[1]["lanes"] = [_busy_lane()]
    assert maintenance.status(1, "d1")["drained"] is False
    registry.nodes[1]["lanes"] = []

    # The node is idle again, but the time it was idle before does not count any more.
    assert maintenance.status(1, "d1")["drained"] is False
    clock.advance(SETTLE_S - 1)
    assert maintenance.status(1, "d1")["drained"] is False
    clock.advance(1)
    assert maintenance.status(1, "d1")["drained"] is True


def test_a_node_that_is_offline_has_nothing_to_drain(maintenance, registry):
    registry.nodes[1]["online"] = False

    answer = maintenance.request(1, "d1")

    assert answer["status"] == "granted"
    assert answer["online"] is False
    assert answer["drained"] is True


def test_the_answer_carries_what_the_manager_needs_to_see_a_reconnect(maintenance, registry):
    before = maintenance.request(1, "d1")["session_id"]
    registry.nodes[1]["session_id"] = "session-after-the-swap"
    registry.nodes[1]["first_status"] = False

    reconnecting = maintenance.status(1, "d1")
    registry.nodes[1]["first_status"] = True
    reconnected = maintenance.status(1, "d1")

    assert before == "session-1"
    assert reconnecting["session_id"] == "session-after-the-swap"
    assert reconnecting["first_status_received"] is False
    assert reconnected["first_status_received"] is True


def test_status_without_a_lease_still_reports_the_node(maintenance):
    answer = maintenance.status(1, "d1")

    assert answer["status"] == "no_lease"
    assert answer["online"] is True
    assert answer["session_id"] == "session-1"
    assert "drained" not in answer


# ── models without another node ──────────────────────────────────────────────


def test_a_model_no_other_node_serves_is_reported(maintenance):
    answer = maintenance.request(1, "d1")

    assert answer["sole_replica_models"] == ["model-a"]


def test_a_model_only_counts_as_covered_by_a_node_that_is_connected(maintenance, registry):
    registry.nodes[2]["online"] = False

    assert maintenance.sole_replica_models(1) == ["model-a", "model-shared"]


def test_a_cordoned_peer_does_not_cover_a_model(maintenance, registry):
    maintenance.request(2, "d2")

    assert maintenance.sole_replica_models(1) == ["model-a", "model-shared"]


def test_a_node_without_a_snapshot_serves_nothing(maintenance):
    assert maintenance.sole_replica_models(99) == []


# ── the registry asks the service ────────────────────────────────────────────


def test_the_registry_reports_no_cordon_until_a_service_is_attached():
    registry = LogosNodeRuntimeRegistry()

    assert registry.is_cordoned(1) is False


def test_the_registry_passes_the_question_to_the_service(clock):
    registry = LogosNodeRuntimeRegistry()
    service = NodeMaintenance(registry, ttl_s=TTL_S, settle_s=SETTLE_S, clock=clock)
    registry.cordon_check = service.is_cordoned

    service.request(7, "d1")

    assert registry.is_cordoned(7) is True
    assert registry.is_cordoned(8) is False
