"""The report of how a deployment ended, which the orchestrator turns into a notification for the Logos admins.

Only the ending is reported, once, and never in a way that changes the deployment: the deployment is over when the
report is made.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import BUSY, DRAINED, OLD, REPO, UNHEALTHY, queued

from logos_node_manager.errors import Interrupted
from logos_node_manager.orchestrator import CordonReply, OrchestratorUnavailable
from logos_node_manager.state import Outcome


@pytest.fixture
def reporting_deployer(make_deployer, drain_settings, orchestrator):
    return make_deployer(settings=drain_settings, orchestrator=orchestrator)


def finish(deployer, store, tag: str = "v2", deployment_id: str = "run-1"):
    return deployer.process(queued(store, tag, deployment_id))


# ---------------------------------------------------------------------- What is reported


def test_a_success_is_reported_with_what_the_drain_waited_for(reporting_deployer, orchestrator, store):
    # Two requests at the cordon, then drained: the first reply is what the drain had to wait for.
    orchestrator.cordon_replies = [BUSY, DRAINED]
    record = finish(reporting_deployer, store)

    reporting_deployer.report_pending()

    ((deployment_id, details),) = orchestrator.reports
    assert deployment_id == "run-1"
    assert details["outcome"] == "succeeded"
    assert details["tag"] == "v2"
    assert details["failure"] is None
    assert details["drained_requests"] == 2
    assert details["drain_seconds"] is not None
    assert store.load("run-1").reported_at is not None
    assert record.outcome is Outcome.SUCCEEDED


def test_the_two_counts_of_the_orchestrator_are_not_added_up(reporting_deployer, orchestrator, store):
    # A request that runs on the worker is tracked by the orchestrator as well: 4 and 4 are 4 requests, not 8.
    orchestrator.cordon_replies = [
        CordonReply(granted=True, drained=False, session_id="s", in_flight_orchestrator=4, in_flight_worker=4),
        DRAINED,
    ]
    finish(reporting_deployer, store)

    reporting_deployer.report_pending()

    assert orchestrator.reports[0][1]["drained_requests"] == 4


def test_the_worker_count_wins_when_the_orchestrator_lost_track(reporting_deployer, orchestrator, store):
    # After a restart the orchestrator tracks nothing, but the worker still runs three requests.
    orchestrator.cordon_replies = [
        CordonReply(granted=True, drained=False, session_id="s", in_flight_orchestrator=0, in_flight_worker=3),
        DRAINED,
    ]
    finish(reporting_deployer, store)

    reporting_deployer.report_pending()

    assert orchestrator.reports[0][1]["drained_requests"] == 3


def test_a_failure_is_reported_with_its_kind_and_the_reason(reporting_deployer, orchestrator, docker, store):
    docker.new_container_timeline = list(UNHEALTHY)
    record = finish(reporting_deployer, store)

    reporting_deployer.report_pending()

    details = orchestrator.reports[0][1]
    assert details["outcome"] == "rolled_back"
    assert details["failure"] == "verify_failed"
    assert details["message"] == record.message


def test_a_deployment_that_changes_nothing_is_reported_too(reporting_deployer, orchestrator, docker, store):
    # An admin who waits for the result of a deployment gets one, also when the container already ran the image.
    docker.registry[f"{REPO}:latest"] = OLD
    orchestrator.cordon_replies = [BUSY, DRAINED]
    record = finish(reporting_deployer, store, tag="latest")

    reporting_deployer.report_pending()

    ((_, details),) = orchestrator.reports
    assert record.outcome is Outcome.UNCHANGED
    assert details["outcome"] == "unchanged"
    assert details["failure"] is None
    assert details["drained_requests"] == 2, "the node was cordoned and drained all the same"
    assert store.load("run-1").reported_at is not None


def test_a_node_without_a_drain_reports_without_a_figure_for_the_requests(
    make_deployer, drain_settings, orchestrator, store
):
    deployer = make_deployer(settings=replace(drain_settings, drain_enabled=False), orchestrator=orchestrator)
    finish(deployer, store)

    deployer.report_pending()

    details = orchestrator.reports[0][1]
    assert details["outcome"] == "succeeded"
    assert details["drained_requests"] is None
    assert details["drain_seconds"] is None
    assert orchestrator.count("cordon") == 0


def test_the_free_text_is_limited(reporting_deployer, orchestrator, store):
    record = queued(store, "v2")
    record.requested_by = "r" * 1000
    store.save(record)
    finish_record = reporting_deployer.process(record)
    finish_record.message = "m" * 5000
    store.save(finish_record)

    reporting_deployer.report_pending()

    details = orchestrator.reports[0][1]
    assert len(details["message"]) <= 1500
    assert len(details["requested_by"]) <= 300


# ---------------------------------------------------------------------- Once, and only when asked for


def test_an_ending_is_reported_once(reporting_deployer, orchestrator, store):
    finish(reporting_deployer, store)

    reporting_deployer.report_pending()
    reporting_deployer.report_pending()

    assert orchestrator.count("report") == 1


def test_nothing_is_reported_without_an_orchestrator(make_deployer, drain_settings, store):
    deployer = make_deployer(settings=drain_settings, orchestrator=None)
    finish(deployer, store)

    deployer.report_pending()

    assert store.load("run-1").reported_at is None


def test_a_deployment_that_is_still_running_is_not_reported(reporting_deployer, orchestrator, store):
    queued(store, "v2")

    reporting_deployer.report_pending()

    assert orchestrator.count("report") == 0


def test_an_old_record_is_not_announced_late(reporting_deployer, orchestrator, store):
    record = finish(reporting_deployer, store)
    record.finished_at = "2025-12-31T00:00:00.000000+00:00"
    store.save(record)

    reporting_deployer.report_pending()

    assert orchestrator.count("report") == 0


# ---------------------------------------------------------------------- When the orchestrator cannot be asked


def test_an_orchestrator_that_is_down_leaves_the_ending_for_the_next_start(
    make_deployer, drain_settings, orchestrator, store, caplog
):
    deployer = make_deployer(settings=drain_settings, orchestrator=orchestrator)
    finish(deployer, store)
    orchestrator.report_replies = [OrchestratorUnavailable("connection refused", retryable=True)]

    with caplog.at_level("WARNING"):
        deployer.report_pending()

    assert store.load("run-1").reported_at is None
    assert "the ending was not reported" in caplog.text
    attempts = orchestrator.count("report")
    assert attempts > 1, "asked again within the retry window"
    deployer.report_pending()
    assert orchestrator.count("report") == attempts, "not again before the next start"

    restarted = make_deployer(settings=drain_settings, orchestrator=orchestrator)
    orchestrator.report_replies = []
    restarted.report_pending()

    assert store.load("run-1").reported_at is not None


def test_a_report_is_asked_again_for_30_seconds_whatever_the_window_of_the_drain(
    make_deployer, drain_settings, orchestrator, store
):
    deployer = make_deployer(
        settings=replace(drain_settings, orchestrator_retry_window_s=120), orchestrator=orchestrator
    )
    finish(deployer, store)
    orchestrator.report_replies = [OrchestratorUnavailable("connection refused", retryable=True)]

    deployer.report_pending()

    # One try every poll interval (5 s) from second 0 to second 30.
    assert orchestrator.count("report") == 7


def test_a_refusal_is_not_asked_again(make_deployer, drain_settings, orchestrator, store):
    deployer = make_deployer(settings=drain_settings, orchestrator=orchestrator)
    finish(deployer, store)
    orchestrator.report_replies = [OrchestratorUnavailable("the orchestrator answered 404", retryable=False)]

    deployer.report_pending()

    assert orchestrator.count("report") == 1
    assert store.load("run-1").reported_at is None


def test_a_stop_while_reporting_is_tried_again_at_the_next_start(make_deployer, drain_settings, orchestrator, store):
    stopping = {"now": False}
    deployer = make_deployer(settings=drain_settings, orchestrator=orchestrator, should_stop=lambda: stopping["now"])
    finish(deployer, store)
    orchestrator.report_replies = [OrchestratorUnavailable("connection refused", retryable=True)]
    stopping["now"] = True

    with pytest.raises(Interrupted):
        deployer.report_pending()

    stopping["now"] = False
    orchestrator.report_replies = []
    deployer.report_pending()
    assert store.load("run-1").reported_at is not None
