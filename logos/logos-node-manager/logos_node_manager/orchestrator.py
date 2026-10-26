"""The orchestrator's side of a deployment: the cordon of the node.

Before the manager replaces the worker container it asks the orchestrator to cordon the node. A cordoned node gets no
new requests, so the ones that run finish. The manager asks again until the orchestrator says the node has drained, and
gives the cordon back when the deployment is over. After the replacement it asks what the orchestrator sees of the node,
to know that the new worker connected. When the deployment has ended, it reports how, so that the orchestrator notifies
the admins.

The node authenticates with the key of the worker, as the worker does itself, so the orchestrator resolves the node from
the key and the manager can only cordon its own node. The key is sent in the request body and never written to a log.
Only the standard library is used: the manager has no runtime dependencies.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from logos_node_manager.config import Settings

logger = logging.getLogger(__name__)

API_PATH = "/logosdb/providers/logosnode/node-maintenance"
# What of an error answer is kept in the message. It is a reason from the orchestrator, not a place for a dump.
_MAX_DETAIL_CHARS = 200


class OrchestratorUnavailable(Exception):
    """The orchestrator gave no usable answer.

    ``retryable`` tells whether asking again can help: a network error or a server error may pass, a missing endpoint
    or a key the orchestrator does not know will not.
    """

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class CordonReply:
    """The answer to a request for the cordon."""

    granted: bool
    # When denied: why, and the node that holds the cordon (empty if none does).
    reason: str = ""
    holder: str = ""
    # When granted: whether the node has drained, how many requests it still has, and the worker session now connected.
    drained: bool = False
    online: bool = True
    session_id: str | None = None
    in_flight_orchestrator: int = 0
    in_flight_worker: int = 0
    sole_replica_models: tuple[str, ...] = ()

    @property
    def in_flight(self) -> int:
        """The requests the node still has.

        The two counts overlap: the orchestrator tracks a request from its scheduling to its end, so one that runs on
        the worker is in both, and the worker's count adds nothing to it. Only the orchestrator knows a request that is
        scheduled but has not reached the worker; only the worker knows one the orchestrator lost track of, for example
        after its restart. The larger count is therefore the better figure, and the sum would count requests twice.
        """
        return max(self.in_flight_orchestrator, self.in_flight_worker)


@dataclass(frozen=True)
class NodeStatus:
    """What the orchestrator sees of the node."""

    online: bool
    first_status_received: bool
    session_id: str | None


def _count(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


class OrchestratorClient:
    def __init__(self, base_url: str, node_key: str, *, timeout_s: float = 15.0) -> None:
        self._url = base_url.rstrip("/") + API_PATH
        self._key = node_key
        self._timeout_s = timeout_s

    @classmethod
    def from_settings(cls, settings: Settings) -> "OrchestratorClient | None":
        """The client, or None when the address or the key is missing."""
        if not settings.orchestrator_url or not settings.node_key:
            return None
        if not settings.orchestrator_url.startswith(("https://", "http://")):
            logger.warning("NODE_MANAGER_ORCHESTRATOR_URL is not an http(s) address; the node cannot be drained")
            return None
        return cls(settings.orchestrator_url, settings.node_key, timeout_s=settings.orchestrator_timeout_s)

    # ------------------------------------------------------------------ Calls

    def cordon(self, deployment_id: str) -> CordonReply:
        """Ask for the cordon, or renew it. The answer also says whether the node has drained."""
        answer = self._post("cordon", deployment_id)
        status = answer.get("status")
        if status == "denied":
            return CordonReply(
                granted=False, reason=str(answer.get("reason") or ""), holder=str(answer.get("holder") or "")
            )
        if status != "granted":
            raise OrchestratorUnavailable(
                f"the orchestrator answered with the unknown status {status!r}", retryable=False
            )
        in_flight = answer.get("in_flight") if isinstance(answer.get("in_flight"), dict) else {}
        models = answer.get("sole_replica_models")
        return CordonReply(
            granted=True,
            drained=answer.get("drained") is True,
            online=answer.get("online") is not False,
            session_id=self._session(answer),
            in_flight_orchestrator=_count(in_flight.get("orchestrator")),
            in_flight_worker=_count(in_flight.get("worker")),
            sole_replica_models=tuple(str(model) for model in models) if isinstance(models, list) else (),
        )

    def status(self, deployment_id: str) -> NodeStatus:
        """What the orchestrator sees of the node. Renews the cordon if this deployment holds it."""
        answer = self._post("status", deployment_id)
        return NodeStatus(
            online=answer.get("online") is True,
            first_status_received=answer.get("first_status_received") is True,
            session_id=self._session(answer),
        )

    def release(self, deployment_id: str) -> None:
        """Give the cordon back. Repeating it is harmless."""
        self._post("release", deployment_id)

    def report(self, deployment_id: str, details: dict[str, Any]) -> None:
        """Tell the orchestrator how the deployment ended, so that it notifies the admins. Repeating it is harmless."""
        self._post("report", deployment_id, details)

    # ------------------------------------------------------------------ HTTP

    @staticmethod
    def _session(answer: dict[str, Any]) -> str | None:
        session = answer.get("session_id")
        return session if isinstance(session, str) and session else None

    def _post(self, call: str, deployment_id: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps({**(details or {}), "shared_key": self._key, "deployment_id": deployment_id}).encode("utf-8")
        request = urllib.request.Request(
            f"{self._url}/{call}", data=body, method="POST", headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:  # noqa: S310 - http(s) only
                payload = response.read()
        except urllib.error.HTTPError as exc:
            # 5xx and 429 pass; any other status is the orchestrator saying no to the request itself.
            retryable = exc.code >= 500 or exc.code == 429
            raise OrchestratorUnavailable(
                f"the orchestrator answered {exc.code} to {call}{self._detail(exc)}", retryable=retryable
            ) from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # The text of the error can name the address, but it never holds the key: that is in the body only.
            raise OrchestratorUnavailable(
                f"the orchestrator could not be reached for {call}: {exc}", retryable=True
            ) from None
        try:
            answer = json.loads(payload)
        except ValueError:
            raise OrchestratorUnavailable(f"the answer to {call} is not JSON", retryable=True) from None
        if not isinstance(answer, dict):
            raise OrchestratorUnavailable(f"the answer to {call} is not a JSON object", retryable=False)
        return answer

    @staticmethod
    def _detail(exc: urllib.error.HTTPError) -> str:
        try:
            detail = json.loads(exc.read()).get("detail")
        except (ValueError, AttributeError, OSError):
            return ""
        return f": {str(detail)[:_MAX_DETAIL_CHARS]}" if isinstance(detail, str) and detail else ""
