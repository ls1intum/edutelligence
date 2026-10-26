"""The notification that a node manager's report of a deployment turns into.

Only the ending is reported, and it goes to the Logos admins. A success is the ``deployment`` type, everything that a
person has to look at is ``deployment_failed``.
"""

from __future__ import annotations

import pytest

from logos.dbutils.dbrequest import LogosNodeDeploymentReport
from logos.notifications.deployment import deployment_notification


def _report(**fields) -> LogosNodeDeploymentReport:
    fields.setdefault("tag", "v2")
    fields.setdefault("outcome", "succeeded")
    return LogosNodeDeploymentReport(shared_key="key", deployment_id="d1", **fields)


def test_a_success_says_how_many_requests_the_drain_waited_for():
    notification = deployment_notification(
        "node-a",
        _report(message="now running r/w:v2", drained_requests=3, drain_seconds=42, requested_by="https://ci/run/1"),
    )

    assert notification["notification_type"] == "deployment"
    assert notification["title"] == "node-a now runs v2"
    assert (
        "3 request(s) were still running when the node was cordoned; they finished within 42 s." in notification["body"]
    )
    assert "Requested by https://ci/run/1" in notification["body"]
    assert notification["targets"] == [{"kind": "role", "role": "logos_admin"}]
    assert notification["payload"]["drained_requests"] == 3
    assert notification["payload"]["drain_seconds"] == 42


def test_a_deployment_that_replaced_nothing_is_a_success_that_says_so():
    notification = deployment_notification(
        "node-a", _report(outcome="unchanged", message="the container already runs r/w:v2")
    )

    assert notification["notification_type"] == "deployment"
    assert notification["title"] == "node-a already runs v2"
    assert notification["body"] == "the container already runs r/w:v2"


def test_an_idle_node_is_said_to_have_had_nothing_to_wait_for():
    notification = deployment_notification("node-a", _report(drained_requests=0, drain_seconds=10))

    assert "no running requests" in notification["body"]


def test_a_deployment_without_a_drain_says_nothing_about_requests():
    notification = deployment_notification("node-a", _report(message="now running r/w:v2"))

    assert "request" not in notification["body"]


def test_the_models_that_waited_for_the_node_are_named():
    notification = deployment_notification("node-a", _report(sole_replica_models=["m1", "m2"]))

    assert "No other node served m1, m2 meanwhile." in notification["body"]


@pytest.mark.parametrize(
    ("outcome", "failure", "title"),
    [
        ("rolled_back", "verify_failed", "node-a was rolled back after deploying v2"),
        ("failed", "drain_timeout", "Deploying v2 on node-a failed"),
        ("failed", "rollback_failed", "node-a needs manual action: deploying v2 and its rollback failed"),
    ],
)
def test_what_a_person_has_to_look_at_is_a_failed_deployment(outcome, failure, title):
    notification = deployment_notification("node-a", _report(outcome=outcome, failure=failure, message="why"))

    assert notification["notification_type"] == "deployment_failed"
    assert notification["title"] == title
    assert notification["body"] == "why"


def test_a_title_never_exceeds_the_column_of_the_application_server():
    notification = deployment_notification("n" * 400, _report(outcome="failed", failure="pull_failed"))

    assert len(notification["title"]) == 255
