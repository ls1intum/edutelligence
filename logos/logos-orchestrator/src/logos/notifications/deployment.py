"""The notification for the end of a node's deployment.

A node manager reports how a deployment ended. This module turns that report into the arguments of
``emit_notification``. Only the ending is worth an inbox item, whatever it is: an admin who waits for the result of a
deployment should get one. The phases in between stay in the log of the node manager.
"""

from __future__ import annotations

from typing import Any

from logos.dbutils.dbrequest import LogosNodeDeploymentReport

# The title column of the application server holds 255 characters.
_MAX_TITLE_CHARS = 255
_LOGOS_ADMINS = [{"kind": "role", "role": "logos_admin"}]
# The endings that a person has to look at. A deployment that replaced nothing is a success as well.
_FAILED = ("rolled_back", "failed")


def _drain_sentence(report: LogosNodeDeploymentReport) -> str:
    if report.drained_requests is None or report.drain_seconds is None:
        return ""
    if report.drained_requests == 0:
        return f"The node had no running requests when it was cordoned; it was drained in {report.drain_seconds} s."
    return (
        f"{report.drained_requests} request(s) were still running when the node was cordoned; "
        f"they finished within {report.drain_seconds} s."
    )


def _title(node: str, report: LogosNodeDeploymentReport) -> str:
    if report.outcome == "succeeded":
        title = f"{node} now runs {report.tag}"
    elif report.outcome == "unchanged":
        title = f"{node} already runs {report.tag}"
    elif report.outcome == "rolled_back":
        title = f"{node} was rolled back after deploying {report.tag}"
    elif report.failure == "rollback_failed":
        title = f"{node} needs manual action: deploying {report.tag} and its rollback failed"
    else:
        title = f"Deploying {report.tag} on {node} failed"
    return title[:_MAX_TITLE_CHARS]


def deployment_notification(node: str, report: LogosNodeDeploymentReport) -> dict[str, Any]:
    """The arguments of ``emit_notification`` for a reported ending, addressed to the Logos admins."""
    lines = [report.message.strip()]
    drain = _drain_sentence(report)
    if drain:
        lines.append(drain)
    if report.sole_replica_models:
        lines.append(f"No other node served {', '.join(report.sole_replica_models)} meanwhile.")
    if report.requested_by:
        lines.append(f"Requested by {report.requested_by}")
    return {
        "notification_type": "deployment_failed" if report.outcome in _FAILED else "deployment",
        "title": _title(node, report),
        "body": "\n".join(line for line in lines if line),
        "payload": {
            "node": node,
            "deployment_id": report.deployment_id,
            "tag": report.tag,
            "outcome": report.outcome,
            "failure": report.failure,
            "drained_requests": report.drained_requests,
            "drain_seconds": report.drain_seconds,
            "sole_replica_models": report.sole_replica_models,
            "requested_by": report.requested_by,
        },
        "targets": _LOGOS_ADMINS,
    }
