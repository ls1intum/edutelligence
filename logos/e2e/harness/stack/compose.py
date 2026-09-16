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

#: Traefik's port when the `ui` profile is up. The browser tier must go through
#: it rather than straight to the UI container: the UI and the API share an
#: origin in production, and testing them on separate origins would miss every
#: CORS and cookie problem that shape causes.
UI_PORT = int(os.environ.get("E2E_UI_PORT", "18091"))
UI_URL = f"http://localhost:{UI_PORT}"

KEYCLOAK_PORT = int(os.environ.get("E2E_KEYCLOAK_PORT", "18095"))
KEYCLOAK_URL = f"http://localhost:{KEYCLOAK_PORT}"

ADMIN_KEY = "lg-e2e-admin-key"
DEVELOPER_KEY = "lg-e2e-developer-key"

NODE_SERVICES = ("node-l40s", "node-2080ti")


def _compose(*args: str, check: bool = True, capture: bool = False, ui: bool = False) -> subprocess.CompletedProcess:
    profile = ["--profile", "ui"] if ui else []
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "-p", PROJECT, *profile, *args]
    return subprocess.run(cmd, check=check, text=True, capture_output=capture)


def pull(*, attempts: int = 3, ui: bool = False) -> None:
    """Pre-pull base images, retrying past registry flakes.

    Docker Hub resets connections often enough on shared CI runners that a
    single ``up`` is a coin flip: one "connection reset by peer" on a postgres
    manifest fails the whole stack and reads as a broken test suite. Pulling
    first, with retries, keeps a registry hiccup from being reported as a
    product regression.

    Never fatal on its own — if the pulls still fail, ``up`` is left to try and
    to produce the real error.
    """
    for attempt in range(1, attempts + 1):
        result = _compose("pull", "--ignore-buildable", "--policy", "missing", check=False, ui=ui)
        if result.returncode == 0:
            return
        if attempt == attempts:
            print(f"warning: image pull still failing after {attempts} attempt(s); letting `up` try anyway")
            return
        delay = 5 * attempt
        print(f"image pull failed (attempt {attempt}/{attempts}); retrying in {delay}s")
        time.sleep(delay)


def up(*, timeout_s: float = 900.0, ui: bool = False, pull_attempts: int = 3) -> None:
    """Bring the stack up. *ui* adds Keycloak, the webservice and the UI.

    Those three roughly triple the startup cost, so the inter-node and SDK tiers
    deliberately run without them.
    """
    pull(attempts=pull_attempts, ui=ui)
    _compose("up", "-d", "--build", "--wait", "--wait-timeout", str(int(timeout_s)), ui=ui)
    wait_for_orchestrator()
    if ui:
        wait_for_ui()


def down(*, volumes: bool = True) -> None:
    args = ["down", "--remove-orphans"]
    if volumes:
        args.append("--volumes")
    # Always with the profile, so a `down` after a UI run removes those
    # containers too instead of orphaning them.
    _compose(*args, check=False, ui=True)


def logs(service: str | None = None, tail: int = 200) -> str:
    args = ["logs", f"--tail={tail}"]
    if service:
        args.append(service)
    result = _compose(*args, check=False, capture=True, ui=True)
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


def ui_is_up() -> bool:
    """True once the UI can actually *bootstrap*, not merely serve its index.

    nginx answers 200 for `/` the moment the UI container starts, but the
    Angular app blocks its own bootstrap on an app initializer that fetches
    `/api/info` and throws unless the response carries `keycloak.issuer` and
    `keycloak.client_id` (see logos-ui/src/app/core/auth/keycloak.ts). That
    endpoint is served by the webservice — a Spring app with no healthcheck,
    which the UI only `depends_on: service_started`.

    Probing the static root therefore declared the stack ready while the app
    would still fail to start. That is not hypothetical: it is why a Playwright
    run timed out looking for the sign-in button, a symptom first papered over
    by raising the timeout. Readiness now means the same call the app makes
    succeeds with the config it requires.
    """
    try:
        if httpx.get(UI_URL, timeout=2.0, follow_redirects=True).status_code >= 500:
            return False
        response = httpx.get(f"{UI_URL}/api/info", timeout=5.0, follow_redirects=True)
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    try:
        keycloak = (response.json() or {}).get("keycloak") or {}
    except ValueError:
        return False
    return bool(keycloak.get("issuer") and keycloak.get("client_id"))


def wait_for_ui(timeout_s: float = 240.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if ui_is_up():
            return
        time.sleep(2.0)
    raise TimeoutError(
        f"the UI could not bootstrap within {timeout_s:.0f}s: {UI_URL}/api/info never returned "
        f"a keycloak issuer and client_id. Webservice logs:\n{logs('logos-webservice', tail=40)}"
    )


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
    parser.add_argument(
        "--ui",
        action="store_true",
        help="also start Keycloak, the webservice and the UI (needed for the Playwright tier)",
    )
    args = parser.parse_args()

    if args.action == "up":
        try:
            up(ui=args.ui)
        except (subprocess.CalledProcessError, TimeoutError) as exc:
            # A failed `up` leaves containers behind with the actual reason in
            # their logs; a bare traceback here sends the reader hunting for it.
            print(f"stack failed to start: {exc}\n", file=sys.stderr)
            print(logs(tail=80), file=sys.stderr)
            return 1
        nodes = wait_for_nodes()
        print(f"stack ready at {ORCHESTRATOR_URL} with {len(nodes)} worker node(s)")
        if args.ui:
            print(f"UI ready at {UI_URL} (Keycloak at {KEYCLOAK_URL})")
    elif args.action == "down":
        down()
    elif args.action == "logs":
        print(logs(args.service))
    else:
        print(f"orchestrator reachable: {is_up()}")
        print(f"UI reachable: {ui_is_up()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
