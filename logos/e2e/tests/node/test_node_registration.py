"""Inter-node tier: a simulated worker joining the orchestrator.

The vertical slice this covers is the one every other node scenario builds on —
register, authenticate, establish the WebSocket session, and report hardware the
orchestrator can plan against. The nodes are the real ``logos_worker_node``
running against the GPU simulator, so what the orchestrator receives here is
what it would receive from a physical node with those cards installed.
"""

from __future__ import annotations

import httpx
import pytest
from harness.gpusim.scenario import GpuProfile

pytestmark = pytest.mark.stack

EXPECTED_FLEET = {
    # service name -> (GPU profile, card count)
    "node-l40s": ("l40s", 2),
    "node-2080ti": ("rtx2080ti", 1),
}


def test_every_simulated_node_completes_the_handshake(nodes):
    assert len(nodes) == len(
        EXPECTED_FLEET
    ), f"expected {len(EXPECTED_FLEET)} connected node(s), got {len(nodes)}: {[n.name for n in nodes]}"


def test_orchestrator_sees_the_real_hardware_of_each_node(nodes):
    """Heterogeneous hardware must arrive intact, not flattened to a default.

    Capacity planning and placement are driven entirely by these numbers; a node
    whose VRAM is reported wrong is scheduled wrong, and nothing else in the
    system notices.
    """
    by_total_vram = {round(node.total_vram_mb): node for node in nodes}

    for profile_key, count in EXPECTED_FLEET.values():
        profile = GpuProfile.load(profile_key)
        expected_total = round(profile.memory_total_mb * count)
        assert expected_total in by_total_vram, (
            f"no connected node reports {expected_total} MB total VRAM "
            f"({count}× {profile.name}); saw {sorted(by_total_vram)}"
        )
        node = by_total_vram[expected_total]
        assert len(node.devices) == count
        assert set(node.gpu_names) == {profile.name}


def test_node_devices_are_queryable_through_the_admin_endpoint(admin, nodes):
    """The operator-facing view must agree with the status payload."""
    for node in nodes:
        devices = admin.node_devices(node.provider_id)
        assert devices, f"node {node.name} reports no devices to the admin endpoint"
        assert len(devices) == len(node.devices)


def test_gpu_telemetry_survives_the_whole_path(nodes):
    """Per-card telemetry must arrive intact, not collapsed into a total.

    This is the longest path in the suite: the GPU simulator answers
    `nvidia-smi`, the real worker parses it, the bridge ships it over the
    WebSocket, and the orchestrator stores it. Every field asserted here is one
    a UI panel or the capacity planner reads.
    """
    for node in nodes:
        assert node.telemetry_available, f"{node.name} reports no usable GPU telemetry"
        assert node.degraded_reason == "", f"{node.name} is degraded: {node.degraded_reason}"

        for device in node.devices:
            assert device["kind"] == "nvidia"
            assert device["memory_total_mb"] > 0
            # Idle simulated cards hold nothing, so free must equal total —
            # a mismatch means the ledger and the totals disagree.
            assert device["memory_free_mb"] == device["memory_total_mb"]
            assert device["temperature_celsius"] is not None, "temperature was dropped in transit"
            assert device["device_id"], "device identity was lost in transit"


def test_node_health_is_reported_for_scheduling_decisions(nodes):
    """A node the scheduler can route to must say so, per sensor.

    The aggregate flag alone is not enough: the watchdog escalates on the GPU
    sensor specifically, so that sensor has to reach the orchestrator by name.
    """
    for node in nodes:
        health = node.node_health
        assert health, f"{node.name} reported no health block"
        assert health.get("healthy") is True, f"{node.name} is unhealthy: {health.get('reason_detail')}"
        assert health.get("sensors", {}).get("gpu", {}).get("state") == "ok"


def test_each_node_reports_a_lane_capacity_view(nodes):
    """Capacity has to arrive even with no lanes running.

    An idle node that reports nothing is indistinguishable from one the planner
    cannot use, and the planner would simply never place work on it.
    """
    for node in nodes:
        assert node.lanes == [], "no lanes were requested, so none should be running"
        assert node.free_vram_mb > 0, f"{node.name} reports no free VRAM while idle"
        assert node.free_vram_mb == node.total_vram_mb


def test_registration_mints_a_usable_provider(admin):
    """The bootstrap endpoint must actually create a provider.

    This is the regression this suite found on its first stack run: the endpoint
    called ``add_provider`` without ``privacy_level``, which that function
    rejects outright, so every registration returned 400 and no worker node
    could join. Nothing else covered it — the unit tests mock DBManager, and a
    node registered by hand through the UI takes a different path entirely.
    """
    registration = admin.register_node("registration-contract-probe")

    assert registration["provider_id"], registration
    assert registration["provider_type"] == "logosnode"
    assert registration["shared_key"], "no shared key was minted"


def test_registration_requires_an_admin_key(orchestrator_url):
    """Node registration mints a shared key; a developer key must not reach it."""
    response = httpx.post(
        f"{orchestrator_url}/logosdb/providers/logosnode/register",
        json={
            "logos_key": "lg-e2e-developer-key",
            "provider_name": "rogue-node",
            "base_url": "",
            "privacy_level": "LOCAL",
        },
        timeout=30.0,
    )
    assert response.status_code == 403, f"a non-admin key registered a node (HTTP {response.status_code})"


def test_registration_requires_an_explicit_privacy_level(orchestrator_url, admin_key):
    """Omitting the trust level must be refused, not silently assumed.

    A default would hand the most trusted tier ("our datacentre") to any worker
    that self-registers — rented GPUs and personal machines included — making it
    eligible for traffic restricted to operator-controlled hardware before an
    operator ever sees it.
    """
    response = httpx.post(
        f"{orchestrator_url}/logosdb/providers/logosnode/register",
        json={"logos_key": admin_key, "provider_name": "no-level-node", "base_url": ""},
        timeout=30.0,
    )
    assert response.status_code == 422, f"a node registered without a privacy level (HTTP {response.status_code})"


def test_registration_rejects_an_unknown_privacy_level(orchestrator_url, admin_key):
    response = httpx.post(
        f"{orchestrator_url}/logosdb/providers/logosnode/register",
        json={
            "logos_key": admin_key,
            "provider_name": "bad-level-node",
            "base_url": "",
            "privacy_level": "TOTALLY_TRUSTED",
        },
        timeout=30.0,
    )
    assert response.status_code == 422, f"an unknown privacy level was accepted (HTTP {response.status_code})"


def test_third_party_hardware_can_register_as_such(admin):
    """Rented or personal hardware must be registerable at its real trust level."""
    registration = admin.register_node("mlx-macbook-probe", privacy_level="THIRD_PARTY_HARDWARE")

    assert registration["provider_id"]
    assert registration["shared_key"]


def test_unknown_shared_key_cannot_open_a_session(orchestrator_url):
    response = httpx.post(
        f"{orchestrator_url}/logosdb/providers/logosnode/auth",
        json={"shared_key": "not-a-real-key", "capabilities_models": []},
        timeout=30.0,
    )
    assert response.status_code == 404


def test_auth_issues_a_short_lived_ticket_and_a_usable_session_url(admin, orchestrator_url):
    """Registration alone is not access — a node still has to trade its key for a ticket.

    The ticket is what bounds the damage of a leaked shared key: it expires in
    seconds and is consumed on first use, so a copy of the key is only useful to
    someone who can also open the WebSocket immediately.
    """
    registration = admin.register_node("auth-contract-probe")
    assert registration["provider_type"] == "logosnode"

    response = httpx.post(
        f"{orchestrator_url}/logosdb/providers/logosnode/auth",
        json={"shared_key": registration["shared_key"], "capabilities_models": []},
        timeout=30.0,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["session_token"]
    assert 0 < payload["expires_in_seconds"] <= 60, "the session ticket is not short-lived"
    assert payload["ws_url"].startswith("ws"), payload["ws_url"]
    assert payload["session_token"] in payload["ws_url"]
