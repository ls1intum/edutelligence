"""Lifecycle for the E2E compose stack.

Usable two ways: as a module the pytest fixtures call, and as a CLI so a
developer (or a CI step) can bring the stack up once and run the tests against
it repeatedly:

    python -m harness.stack.compose up
    python -m harness.stack.compose logs logos-orchestrator
    python -m harness.stack.compose down

The tests never start the stack themselves by default — a suite that owns the
stack lifecycle re-pays the build cost on every invocation and makes a failure
much harder to inspect, because everything is gone by the time you look.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

COMPOSE_FILE = Path(__file__).parent / "docker-compose.e2e.yaml"
PROJECT = "logos-e2e"

#: Host port the orchestrator is published on. Deliberately not 18080 (the dev
#: stack's) so an E2E run cannot silently talk to someone's dev orchestrator.
ORCHESTRATOR_PORT = int(os.environ.get("E2E_ORCHESTRATOR_PORT", "18090"))
ORCHESTRATOR_URL = f"http://localhost:{ORCHESTRATOR_PORT}"

ADMIN_KEY = "lg-e2e-admin-key"
DEVELOPER_KEY = "lg-e2e-developer-key"

NODE_SERVICES = ("node-l40s", "node-2080ti")


def _compose(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "-p", PROJECT, *args]
    return subprocess.run(cmd, check=check, text=True, capture_output=capture)


def up(*, timeout_s: float = 600.0) -> None:
    _compose("up", "-d", "--build", "--wait", "--wait-timeout", str(int(timeout_s)))
    wait_for_orchestrator()


def down(*, volumes: bool = True) -> None:
    args = ["down", "--remove-orphans"]
    if volumes:
        args.append("--volumes")
    _compose(*args, check=False)


def logs(service: str | None = None, tail: int = 200) -> str:
    args = ["logs", f"--tail={tail}"]
    if service:
        args.append(service)
    result = _compose(*args, check=False, capture=True)
    return (result.stdout or "") + (result.stderr or "")


def restart(service: str) -> None:
    _compose("restart", service)


def stop(service: str) -> None:
    _compose("stop", service)


def start(service: str) -> None:
    _compose("start", service)


def is_up() -> bool:
    try:
        return httpx.get(f"{ORCHESTRATOR_URL}/docs", timeout=2.0).status_code < 500
    except httpx.HTTPError:
        return False


def wait_for_orchestrator(timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if is_up():
            return
        time.sleep(1.0)
    raise TimeoutError(f"orchestrator did not answer at {ORCHESTRATOR_URL} within {timeout_s:.0f}s")


def wait_for_nodes(expected: int = len(NODE_SERVICES), timeout_s: float = 180.0) -> list[dict]:
    """Block until *expected* worker nodes have completed their WS handshake.

    Registration is an HTTP call but the node is only usable once its session is
    live, so polling the provider list would report success too early.
    """
    from harness.clients.admin import AdminClient  # noqa: PLC0415

    admin = AdminClient(ORCHESTRATOR_URL, ADMIN_KEY)
    deadline = time.monotonic() + timeout_s
    connected: list[dict] = []
    while time.monotonic() < deadline:
        connected = admin.connected_nodes()
        if len(connected) >= expected:
            return connected
        time.sleep(2.0)
    raise TimeoutError(
        f"only {len(connected)}/{expected} worker node(s) connected within {timeout_s:.0f}s. "
        f"Node logs:\n{logs(NODE_SERVICES[0], tail=60)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Logos E2E stack")
    parser.add_argument("action", choices=["up", "down", "logs", "status"])
    parser.add_argument("service", nargs="?")
    args = parser.parse_args()

    if args.action == "up":
        up()
        nodes = wait_for_nodes()
        print(f"stack ready at {ORCHESTRATOR_URL} with {len(nodes)} worker node(s)")
    elif args.action == "down":
        down()
    elif args.action == "logs":
        print(logs(args.service))
    else:
        print(f"orchestrator reachable: {is_up()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
