"""Container entrypoint for a simulated worker node.

Materialises the GPU scenario this node was configured with, then hands over to
the real ``logos_worker_node`` process. Nothing about the worker is patched —
the only difference from production is which binaries are first on ``PATH``.

Configured entirely through the environment so a compose file can describe a
heterogeneous fleet without a config file per node:

``LOGOS_SIM_PROFILE``       GPU profile key, or a comma-separated list for a
                            mixed-architecture node (default ``l40s``)
``LOGOS_SIM_GPU_COUNT``     number of cards, when a single profile is named
``LOGOS_SIM_BASELINE_MB``   VRAM already in use before any lane starts
``LOGOS_URL``               orchestrator base URL
``LOGOS_ADMIN_KEY``         admin key used to self-register when ``LOGOS_API_KEY``
                            is not supplied (default: the seeded E2E admin key)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/app")

from harness.gpusim import state as gpustate  # noqa: E402
from harness.gpusim.scenario import GpuScenario, VllmScript  # noqa: E402

DEFAULT_ADMIN_KEY = "lg-e2e-admin-key"
REGISTER_PATH = "/logosdb/providers/logosnode/register"


def build_scenario() -> GpuScenario:
    raw_profiles = os.environ.get("LOGOS_SIM_PROFILE", "l40s").strip()
    profiles = [p.strip() for p in raw_profiles.split(",") if p.strip()]
    if len(profiles) == 1:
        count = int(os.environ.get("LOGOS_SIM_GPU_COUNT", "1"))
        profiles = profiles * count
    return GpuScenario(
        profiles=profiles,
        baseline_used_mb=float(os.environ.get("LOGOS_SIM_BASELINE_MB", "0") or 0),
    )


def _post_json(url: str, payload: dict, timeout: float = 10.0) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def self_register(logos_url: str, provider_name: str, deadline_s: float = 120.0) -> str:
    """Register this node and return its shared key.

    Deliberately the real endpoint rather than a pre-seeded provider row: node
    registration is one of the things the inter-node tier is here to cover, and
    a fixture that skips it would let a regression in it reach production.

    Retries because the orchestrator's healthcheck passing does not yet mean its
    database session pool is warm.
    """
    admin_key = os.environ.get("LOGOS_ADMIN_KEY", DEFAULT_ADMIN_KEY)
    # Required by the endpoint — there is no default, so every caller states the
    # trust level explicitly. Overridable so a scenario can register a node as
    # third-party hardware and assert the routing restrictions that follow.
    privacy_level = os.environ.get("LOGOS_SIM_PRIVACY_LEVEL", "LOCAL")
    url = logos_url.rstrip("/") + REGISTER_PATH
    payload = {
        "logos_key": admin_key,
        "provider_name": provider_name,
        "base_url": "",
        "privacy_level": privacy_level,
    }

    deadline = time.monotonic() + deadline_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = _post_json(url, payload)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            last_error = exc
            time.sleep(2.0)
            continue
        shared_key = result.get("shared_key")
        if shared_key:
            print(f"[nodesim] registered as provider {result.get('provider_id')} ({provider_name})", flush=True)
            return shared_key
        last_error = RuntimeError(f"register returned no shared_key: {result}")
        time.sleep(2.0)

    raise RuntimeError(f"[nodesim] could not register with {url} within {deadline_s:.0f}s: {last_error}")


def write_config(path: Path) -> None:
    """Minimal worker config. Credentials stay in the environment, as in production."""
    path.write_text(
        "\n".join(
            [
                "worker:",
                "  port: 80",
                "  name: " + os.environ.get("HOSTNAME", "nodesim"),
                "  gpu_poll_interval: 2",
                "  models_path: /app/models",
                "  cache_path: /app/cache",
                "  auto_reboot_on_stuck_gpu: false",
                "logos:",
                "  heartbeat_interval_seconds: 2",
                "  reconnect_backoff_seconds: 1",
                "lanes: []",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    state_file = Path(os.environ[gpustate.STATE_ENV_VAR])
    state_file.parent.mkdir(parents=True, exist_ok=True)
    gpustate.save(build_scenario().to_state(), state_file)

    script_file = Path(os.environ["LOGOS_GPUSIM_VLLM_SCRIPT"])
    if not script_file.is_file():
        VllmScript().write(script_file)

    state = gpustate.load(state_file)
    print(
        f"[nodesim] simulating {len(state.devices)} device(s): "
        f"{', '.join(d.fields.get('name', '?') for d in state.devices)}",
        flush=True,
    )

    write_config(Path(os.environ["LOGOS_WORKER_NODE_CONFIG"]))

    logos_url = os.environ.get("LOGOS_URL", "").strip()
    if logos_url and not os.environ.get("LOGOS_API_KEY", "").strip():
        provider_name = os.environ.get("LOGOS_SIM_NODE_NAME") or os.environ.get("HOSTNAME", "nodesim")
        os.environ["LOGOS_API_KEY"] = self_register(logos_url, provider_name)

    from logos_worker_node.main import main as worker_main  # noqa: PLC0415

    worker_main()


if __name__ == "__main__":
    main()
