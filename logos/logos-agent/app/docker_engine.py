"""A minimal async client for the Docker Engine API over its Unix socket.

Only the calls this service needs are implemented. Talking to the socket
directly rather than through the docker SDK keeps the dependency set small and
makes the security-relevant fields of a container creation explicit and
reviewable in one place — see :func:`create_session_container`, which is where
the isolation of an agent session is actually decided.
"""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Any, AsyncIterator

import httpx

from .config import settings

# The Engine API is versioned; pin low enough to work with older daemons but
# high enough for the fields used here (PidsLimit, NanoCPUs, ReadonlyRootfs).
_API_VERSION = "v1.43"
_BASE = f"http://docker/{_API_VERSION}"


class DockerError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"docker api {status}: {message}")
        self.status = status
        self.message = message


def _client(timeout: float = 30.0) -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(uds=settings.docker_socket)
    return httpx.AsyncClient(transport=transport, base_url=_BASE, timeout=timeout)


async def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    async with _client() as client:
        response = await client.request(method, path, **kwargs)
    if response.status_code >= 400:
        try:
            message = response.json().get("message", response.text)
        except Exception:
            message = response.text
        raise DockerError(response.status_code, message)
    return response


async def ping() -> bool:
    try:
        await _request("GET", "/_ping")
        return True
    except Exception:
        return False


async def ensure_volume(name: str, labels: dict[str, str] | None = None) -> None:
    """Create a named volume if it does not exist. Idempotent."""
    try:
        await _request("GET", f"/volumes/{name}")
        return
    except DockerError as exc:
        if exc.status != 404:
            raise
    await _request(
        "POST",
        "/volumes/create",
        json={"Name": name, "Labels": labels or {}},
    )


async def volume_mountpoint(name: str) -> str:
    """The host path of a named volume (local driver only).

    Named volumes can only be mounted whole into a container, so binding a
    session to just its own subdirectory goes through the volume's host
    path: the daemon resolves the bind on the host, where the subdirectory
    exists (the service creates it through its own mount of the same volume).

    `GET /volumes/{name}` returns the volume object itself — `Mountpoint` is
    a top-level field, not nested under the volume's name.
    """
    response = await _request("GET", f"/volumes/{name}")
    info = response.json()
    mountpoint = info.get("Mountpoint")
    if not mountpoint:
        raise DockerError(500, f"volume {name} has no host mountpoint (driver: {info.get('Driver')})")
    return mountpoint


async def remove_volume(name: str, *, force: bool = False) -> None:
    try:
        await _request("DELETE", f"/volumes/{name}", params={"force": str(force).lower()})
    except DockerError as exc:
        if exc.status != 404:
            raise


async def ensure_network(name: str, *, internal: bool = False) -> None:
    """Create a network if it does not exist, and verify what is there.

    For the session network ``internal`` *is* the isolation boundary: an
    internal bridge has no route out of the host, which is the only reason a
    container running an agent with permission prompts disabled may hold no
    reusable credential and still be safe. So an existing network is not
    taken on trust — one created as a plain bridge by an older deployment,
    or by hand, would silently give every session external egress. A
    mismatch raises rather than being corrected, because rewriting a live
    network would disconnect whatever is attached to it; the fix is an
    operator removing it while nothing runs.
    """
    try:
        response = await _request("GET", f"/networks/{name}")
    except DockerError as exc:
        if exc.status != 404:
            raise
    else:
        actual = bool(response.json().get("Internal", False))
        if actual != internal:
            raise DockerError(
                409,
                f"network '{name}' exists with Internal={actual}, but this runner "
                f"requires Internal={internal}. Sessions on a non-internal session "
                f"network would have external egress. Remove the network while no "
                f"session is running and let the runner recreate it.",
            )
        return
    await _request(
        "POST",
        "/networks/create",
        json={
            "Name": name,
            "Driver": "bridge",
            "Internal": internal,
            "Labels": {"logos.agent": "session-network"},
        },
    )


async def image_present(image: str) -> bool:
    """Whether an image is on this host already.

    Sessions run an image the registry publishes on every build of the
    default branch. Between a merge and that build finishing — or when a
    deployment has never pulled it — the first session dies with a bare
    `404: No such image`, which reads like a bug in the runner rather than
    a missing artefact. Asking first turns that into a sentence.
    """
    try:
        await _request("GET", f"/images/{image}/json")
        return True
    except DockerError as exc:
        if exc.status == 404:
            return False
        raise


async def create_session_container(
    *,
    name: str,
    image: str,
    env: dict[str, str],
    workspace_volume: str,
    artifact_host_path: str,
    state_host_path: str | None = None,
    session_id: int,
    labels: dict[str, str] | None = None,
    network: str | None = None,
) -> str:
    """Create the container an agent session runs in.

    This is the isolation boundary, so the restrictions are set here rather
    than left to the image:

    * no Docker socket — a session can never reach the daemon that runs it,
      which is what stops it escaping into the rest of the stack;
    * all capabilities dropped and privilege escalation disabled;
    * memory, CPU, and PID ceilings, so one runaway session cannot take the
      host down or eat the capacity this runner exists to reclaim;
    * only two writable mounts, the workspace volume and this session's own
      artefact directory (a host path, so the bind cannot grow to the shared
      volume and expose other sessions' output); everything else is
      read-only.

    ``state_host_path``, when given, adds a third mount that is
    deliberately *not* writable: the runner's own state for this session
    (the pause mark) at ``/logos/state``, read-only. The enforcement is the
    ``:ro`` flag itself — the container runs with every capability dropped
    and no privilege escalation, so the agent cannot remount it — which is
    what keeps the mark out of reach even though the artefact directory
    next door is the agent's to write. The helper phases pass nothing, so a
    container that never reads the mark also never mounts it.

    The default network is the internal session network (the agent phase);
    the trusted helper containers pass the egress network explicitly.
    """
    binds = [
        f"{workspace_volume}:/workspace",
        f"{artifact_host_path}:/artifacts",
    ]
    if state_host_path:
        binds.append(f"{state_host_path}:/logos/state:ro")
    host_config: dict[str, Any] = {
        "Binds": binds,
        "NetworkMode": network or settings.session_network,
        "ReadonlyRootfs": True,
        # The agent needs scratch space; give it tmpfs rather than a writable
        # root so nothing it writes outside /workspace survives the session.
        "Tmpfs": {"/tmp": "rw,exec,nosuid,size=2g", "/home/agent/.cache": "rw,nosuid,size=2g"},
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges:true"],
        "Memory": settings.session_memory_mb * 1024 * 1024,
        "MemorySwap": settings.session_memory_mb * 1024 * 1024,  # no swap: OOM instead of thrash
        "NanoCpus": int(settings.session_cpus * 1_000_000_000),
        "PidsLimit": settings.session_pids_limit,
        "AutoRemove": False,  # keep exit status readable after the run
        "RestartPolicy": {"Name": "no"},
    }

    payload: dict[str, Any] = {
        "Image": image,
        "Env": [f"{k}={v}" for k, v in env.items()],
        "Labels": {
            "logos.agent.session": str(session_id),
            "logos.agent.managed": "true",
            **(labels or {}),
        },
        "WorkingDir": "/workspace",
        "HostConfig": host_config,
        "Tty": False,
        "OpenStdin": False,
        # Never run as root inside the container; the image creates this user.
        "User": "agent",
    }

    response = await _request("POST", "/containers/create", params={"name": name}, json=payload)
    return response.json()["Id"]


async def create_screenshot_container(
    *,
    name: str,
    image: str,
    url: str,
    output_path: str,
    artifact_host_path: str,
    session_id: int,
) -> str:
    """Create a one-shot container that renders one page to a PNG.

    Screenshots run *outside* the session, after any dev deploy has finished,
    so this is a small dedicated container rather than part of a session: it
    runs the same workspace image's browser tooling on the same isolation
    footing — no socket, no capabilities, read-only rootfs, capped resources —
    and gets exactly the session's own artefact directory to write into.
    """
    host_config: dict[str, Any] = {
        "Binds": [f"{artifact_host_path}:/artifacts"],
        # The page to photograph is on the dev environment, i.e. outside:
        # the screenshot runs on the egress network, not the internal
        # session network.
        "NetworkMode": settings.session_egress_network,
        "ReadonlyRootfs": True,
        "Tmpfs": {"/tmp": "rw,nosuid,size=2g"},
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges:true"],
        "Memory": settings.session_memory_mb * 1024 * 1024,
        "MemorySwap": settings.session_memory_mb * 1024 * 1024,
        "NanoCpus": int(settings.session_cpus * 1_000_000_000),
        "PidsLimit": settings.session_pids_limit,
        "AutoRemove": False,  # keep exit status readable
        "RestartPolicy": {"Name": "no"},
    }

    payload: dict[str, Any] = {
        "Image": image,
        # The image's entrypoint is the session harness; a screenshot has no
        # session, so run the page-capture script directly.
        "Entrypoint": ["node", "/usr/local/lib/screenshot.js"],
        "Cmd": [url, output_path],
        "Env": [
            # HOME lives on the read-only rootfs here; /tmp is the scratch
            # space Chromium and Node need.
            "HOME=/tmp",
            "PLAYWRIGHT_BROWSERS_PATH=/opt/playwright",
        ],
        "Labels": {
            "logos.agent.session": str(session_id),
            "logos.agent.screenshot": "true",
            "logos.agent.managed": "true",
        },
        "WorkingDir": "/tmp",
        "HostConfig": host_config,
        "User": "agent",
        "Tty": False,
        "OpenStdin": False,
    }

    response = await _request("POST", "/containers/create", params={"name": name}, json=payload)
    return response.json()["Id"]


async def start_container(container_id: str) -> None:
    await _request("POST", f"/containers/{container_id}/start")


async def stop_container(container_id: str, *, timeout_s: int = 10) -> None:
    try:
        await _request(
            "POST",
            f"/containers/{container_id}/stop",
            params={"t": timeout_s},
            # Stopping waits for the grace period, so the HTTP timeout must
            # outlast it or the call raises while the daemon is still working.
        )
    except DockerError as exc:
        # 304 = already stopped, 404 = already gone. Both are the desired state.
        if exc.status not in (304, 404):
            raise


async def pause_container(container_id: str) -> bool:
    """Freeze a session so its CPU and GPU-adjacent work stops immediately.

    Pausing (SIGSTOP via the freezer cgroup) keeps the process tree and the
    workspace intact, which is what lets a paused session resume mid-task when
    load drops again.

    Returns whether the container is actually frozen now. Docker answers 409
    for a container that is not running and 404 for one that is gone: both
    mean there is nothing to freeze, and the caller must not record the
    session as paused on the strength of them — a row moved to 'paused'
    around an exited container can never be settled.
    """
    try:
        await _request("POST", f"/containers/{container_id}/pause")
    except DockerError as exc:
        if exc.status == 304:
            # Already paused: the desired state, just not by this call.
            return True
        if exc.status in (404, 409):
            return False
        raise
    return True


async def unpause_container(container_id: str) -> bool:
    """Thaw a paused session. Returns whether it is running again.

    304 means it was not frozen in the first place, which is the desired
    end state; 404 and 409 mean there is no running container to thaw, and
    the caller must not record the session as running again.

    Docker also answers 500 "Container … is not paused" for a container
    that is running — the same situation as 304, reported differently, and
    in production it escaped as an exception that killed the whole
    scheduler pass. A container that is already running is what the caller
    asked for.
    """
    try:
        await _request("POST", f"/containers/{container_id}/unpause")
    except DockerError as exc:
        if exc.status == 304 or (exc.status == 500 and "is not paused" in str(exc)):
            return True
        if exc.status in (404, 409):
            return False
        raise
    return True


async def disconnect_network(network: str, container_id: str) -> bool:
    """Detach a container from a network, ending its open connections.

    Freezing a session stops its process tree, but not the generation it
    already started: the request is running upstream, and a frozen client
    neither cancels it nor closes its socket — it simply stops reading, and
    the serving slot stays occupied for as long as the pause lasts. Cutting
    the container off the network tears that connection down, so the
    orchestrator sees the client go away and can release the slot, which is
    the entire point of pausing.

    Best effort: a container that is already detached, or gone, is the
    desired state.
    """
    try:
        await _request("POST", f"/networks/{network}/disconnect", json={"Container": container_id, "Force": True})
    except DockerError as exc:
        if exc.status in (403, 404):
            return False
        raise
    return True


async def connect_network(network: str, container_id: str) -> bool:
    """Attach a container to a network again. Idempotent."""
    try:
        await _request("POST", f"/networks/{network}/connect", json={"Container": container_id})
    except DockerError as exc:
        # 403 is Docker's answer for an endpoint that already exists on this
        # network — which is what the caller wanted.
        if exc.status == 403:
            return True
        if exc.status == 404:
            return False
        raise
    return True


async def remove_container(container_id: str, *, force: bool = True) -> None:
    try:
        await _request("DELETE", f"/containers/{container_id}", params={"force": str(force).lower()})
    except DockerError as exc:
        if exc.status != 404:
            raise


async def inspect_container(container_id: str) -> dict[str, Any] | None:
    try:
        response = await _request("GET", f"/containers/{container_id}/json")
    except DockerError as exc:
        if exc.status == 404:
            return None
        raise
    return response.json()


async def container_state(container_id: str) -> tuple[str, int | None]:
    """Return (status, exit_code). Status is Docker's own vocabulary."""
    info = await inspect_container(container_id)
    if info is None:
        return "gone", None
    state = info.get("State", {})
    exit_code = state.get("ExitCode")
    return state.get("Status", "unknown"), exit_code


def _demux(chunk: bytes) -> AsyncIterator[str]:  # pragma: no cover - helper shape
    raise NotImplementedError


async def stream_logs(container_id: str, *, since: int = 0, follow: bool = True) -> AsyncIterator[str]:
    """Yield log lines from a container.

    Without a TTY the daemon multiplexes stdout and stderr into a framed
    stream: an 8-byte header per frame, where byte 0 is the stream index and
    bytes 4..8 are the payload length. Both streams are merged here — for an
    agent transcript the interleaving is the useful part.
    """
    params = {
        "stdout": "true",
        "stderr": "true",
        "follow": "true" if follow else "false",
        "since": str(since),
        "timestamps": "false",
    }
    transport = httpx.AsyncHTTPTransport(uds=settings.docker_socket)
    async with httpx.AsyncClient(transport=transport, base_url=_BASE, timeout=None) as client:
        async with client.stream("GET", f"/containers/{container_id}/logs", params=params) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise DockerError(response.status_code, body.decode("utf-8", "replace"))
            buffer = bytearray()
            async for chunk in response.aiter_bytes():
                buffer.extend(chunk)
                while len(buffer) >= 8:
                    header = bytes(buffer[:8])
                    # A plain (non-multiplexed) stream can appear when the
                    # container was created with a TTY. Detect it by an
                    # implausible stream index and fall back to raw decoding.
                    if header[0] not in (0, 1, 2):
                        text = bytes(buffer).decode("utf-8", "replace")
                        buffer.clear()
                        for line in text.splitlines():
                            yield line
                        break
                    (length,) = struct.unpack(">I", header[4:8])
                    if len(buffer) < 8 + length:
                        break
                    payload = bytes(buffer[8 : 8 + length])
                    del buffer[: 8 + length]
                    for line in payload.decode("utf-8", "replace").splitlines():
                        yield line


async def wait_container(container_id: str, timeout_s: int) -> int | None:
    """Wait for a container to exit; return its exit code, or None on timeout."""
    try:
        async with _client(timeout=timeout_s) as client:
            response = await client.post(f"/containers/{container_id}/wait")
        if response.status_code >= 400:
            raise DockerError(response.status_code, response.text)
        return int(response.json().get("StatusCode", -1))
    except (httpx.TimeoutException, asyncio.TimeoutError):
        return None


async def list_managed_containers() -> list[dict[str, Any]]:
    """Every container this service owns, including ones it has forgotten.

    Used on startup to reconcile: a restart of the runner must not orphan
    running sessions, and must not leave dead ones marked running.
    """
    filters = json.dumps({"label": ["logos.agent.managed=true"]})
    response = await _request("GET", "/containers/json", params={"all": "true", "filters": filters})
    return response.json()
