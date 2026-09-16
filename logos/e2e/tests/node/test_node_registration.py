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
    """The operator-facing view must agree with the scheduler's."""
    for node in nodes:
        devices = admin.node_devices(node.provider_id)
        assert devices, f"node {node.name} reports no devices to the admin endpoint"
        assert len(devices) == len(node.devices)


def test_registration_requires_an_admin_key(orchestrator_url):
    """Node registration mints a shared key; a developer key must not reach it."""
    response = httpx.post(
        f"{orchestrator_url}/logosdb/providers/logosnode/register",
        json={"logos_key": "lg-e2e-developer-key", "provider_name": "rogue-node", "base_url": ""},
        timeout=30.0,
    )
    assert response.status_code == 403, f"a non-admin key registered a node (HTTP {response.status_code})"


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
