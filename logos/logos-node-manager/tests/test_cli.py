"""The command line: what CI calls, and the exit codes it relies on."""

from __future__ import annotations

import json
import os
import time

import pytest

from logos_node_manager import cli
from logos_node_manager.config import Settings
from logos_node_manager.state import Deployment, FailureKind, Outcome, Phase


def parse(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def finishing(store, clock, deployment_id, outcome, *, failure=None, message="", logs=""):
    """A sleep function that lets the "daemon" finish the deployment while the command waits."""

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        record = store.load(deployment_id)
        if record.finished:
            return
        record.events.append({"at": "2026-01-01T12:00:01.000000+00:00", "phase": "pulling", "note": "pulled v2"})
        record.phase = Phase.DONE
        record.outcome = outcome
        record.failure = failure
        record.message = message
        record.failure_logs = logs
        store.save(record)

    return sleep


def pulling(store, clock, deployment_id, *, ending=None):
    """A sleep function that lets the "daemon" pull the image while the command waits.

    With ``ending`` the deployment is also finished by then, as a fast one would be.
    """

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        record = store.load(deployment_id)
        if record.phase is Phase.QUEUED:
            record.events.append({"at": "2026-01-01T12:00:01.000000+00:00", "phase": "draining", "note": "pulled v2"})
            record.phase = Phase.DRAINING
            if ending is not None:
                record.phase = Phase.DONE
                record.outcome, record.failure = ending
            store.save(record)

    return sleep


def deploy(settings, store, clock, *argv, sleep=None):
    args = parse("deploy", "--id", "run-1", "--tag", "v2", *argv)
    return cli.cmd_deploy(args, settings, clock=clock, sleep=sleep or clock.sleep)


def test_deploy_without_wait_queues_the_deployment_and_returns(settings, store, clock, capsys):
    assert deploy(settings, store, clock) == cli.EXIT_OK

    assert store.load("run-1").phase is Phase.QUEUED
    assert "is queued for tag v2" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("outcome", "failure", "exit_code"),
    [
        (Outcome.SUCCEEDED, None, cli.EXIT_OK),
        (Outcome.UNCHANGED, None, cli.EXIT_OK),
        (Outcome.ROLLED_BACK, FailureKind.VERIFY_FAILED, cli.EXIT_ROLLED_BACK),
        (Outcome.FAILED, FailureKind.PULL_FAILED, cli.EXIT_FAILED),
    ],
)
def test_the_exit_code_tells_how_the_deployment_ended(settings, store, clock, capsys, outcome, failure, exit_code):
    store.submit(Deployment(id="run-1", tag="v2", requested_at="2026-01-01T00:00:00"))
    sleep = finishing(store, clock, "run-1", outcome, failure=failure, message="the message")

    assert deploy(settings, store, clock, "--wait", sleep=sleep) == exit_code

    out = capsys.readouterr().out
    assert f"Deployment run-1: {outcome.value}" in out
    assert "the message" in out
    assert "pulling: pulled v2" in out


def test_the_log_of_a_failed_container_is_printed_unless_switched_off(settings, store, clock, capsys):
    store.submit(Deployment(id="run-1", tag="v2", requested_at="2026-01-01T00:00:00"))
    sleep = finishing(
        store, clock, "run-1", Outcome.ROLLED_BACK, failure=FailureKind.VERIFY_FAILED, logs="ImportError: no module"
    )
    deploy(settings, store, clock, "--wait", sleep=sleep)
    assert "ImportError: no module" in capsys.readouterr().out

    deploy(settings, store, clock, "--wait", "--no-logs")
    assert "ImportError" not in capsys.readouterr().out


def test_a_wait_that_runs_out_leaves_the_deployment_running(settings, store, clock, capsys):
    code = deploy(settings, store, clock, "--wait", "--timeout", "30")

    assert code == cli.EXIT_WAIT_TIMED_OUT
    assert "node-manager wait run-1" in capsys.readouterr().err
    assert store.load("run-1").phase is Phase.QUEUED


def test_the_same_id_attaches_to_the_deployment_that_exists(settings, store, clock, capsys):
    deploy(settings, store, clock)
    record = store.load("run-1")
    record.phase = Phase.SWAPPING
    store.save(record)

    assert deploy(settings, store, clock) == cli.EXIT_OK

    assert store.load("run-1").phase is Phase.SWAPPING


def test_an_id_for_another_tag_is_refused(settings, store, clock, capsys):
    deploy(settings, store, clock)

    args = parse("deploy", "--id", "run-1", "--tag", "v3")
    assert cli.cmd_deploy(args, settings, clock=clock, sleep=clock.sleep) == cli.EXIT_USAGE
    assert "already used for tag v2" in capsys.readouterr().err


@pytest.mark.parametrize(("flag", "value"), [("--tag", "no spaces allowed"), ("--id", "../escape")])
def test_invalid_input_is_refused_before_anything_is_written(settings, store, clock, capsys, flag, value):
    arguments = {"--id": "run-1", "--tag": "v2", flag: value}
    args = parse("deploy", *[part for pair in arguments.items() for part in pair])

    assert cli.cmd_deploy(args, settings, clock=clock, sleep=clock.sleep) == cli.EXIT_USAGE
    assert store.all() == []


def test_the_reserved_tag_is_refused_with_a_reason(settings, store, clock, capsys):
    args = parse("deploy", "--id", "run-1", "--tag", "previous")

    assert cli.cmd_deploy(args, settings, clock=clock, sleep=clock.sleep) == cli.EXIT_USAGE
    assert "reserved" in capsys.readouterr().err
    assert store.all() == []


def test_a_missing_daemon_is_pointed_out_but_the_request_is_kept(settings, store, clock, capsys):
    deploy(settings, store, clock)

    assert "does not answer" in capsys.readouterr().err
    assert store.load("run-1") is not None


def test_no_warning_while_the_daemon_is_alive(settings, store, clock, capsys):
    store.touch_heartbeat()

    deploy(settings, store, clock)

    assert "does not answer" not in capsys.readouterr().err


def test_wait_attaches_to_a_deployment_that_is_already_queued(settings, store, clock, capsys):
    store.submit(Deployment(id="run-1", tag="v2", requested_at="2026-01-01T00:00:00"))
    sleep = finishing(store, clock, "run-1", Outcome.SUCCEEDED)

    assert cli.cmd_wait(parse("wait", "run-1"), settings, clock=clock, sleep=sleep) == cli.EXIT_OK


def test_wait_for_an_unknown_deployment_does_not_hang(settings, clock, capsys):
    code = cli.cmd_wait(parse("wait", "nope", "--timeout", "5"), settings, clock=clock, sleep=clock.sleep)

    assert code == cli.EXIT_NOT_FOUND
    assert "there is no deployment nope" in capsys.readouterr().err


def test_status_without_an_id_shows_the_latest_deployment(settings, store, capsys):
    store.submit(Deployment(id="old", tag="v1", requested_at="2026-01-01T00:00:01"))
    store.submit(Deployment(id="new", tag="v2", requested_at="2026-01-01T00:00:02"))

    assert cli.cmd_status(parse("status"), settings) == cli.EXIT_OK

    assert "Deployment new: tag v2, phase queued" in capsys.readouterr().out


def test_status_can_print_the_whole_record(settings, store, capsys):
    store.submit(Deployment(id="run-1", tag="v2", requested_at="2026-01-01T00:00:00"))

    cli.cmd_status(parse("status", "run-1", "--json"), settings)

    record = json.loads(capsys.readouterr().out)
    assert record["id"] == "run-1"
    assert record["phase"] == "queued"


def test_status_of_an_unknown_deployment_is_not_found(settings, capsys):
    assert cli.cmd_status(parse("status", "nope"), settings) == cli.EXIT_NOT_FOUND


def test_ping_follows_the_age_of_the_heartbeat(settings, store, capsys):
    assert cli.cmd_ping(parse("ping"), settings) == cli.EXIT_ERROR

    store.touch_heartbeat()
    assert cli.cmd_ping(parse("ping"), settings) == cli.EXIT_OK

    old = time.time() - 120
    os.utime(store.heartbeat_file, (old, old))
    assert cli.cmd_ping(parse("ping"), settings) == cli.EXIT_ERROR


def test_main_reads_the_state_directory_from_the_environment(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NODE_MANAGER_STATE_DIR", str(tmp_path / "state"))

    assert cli.main(["status"]) == cli.EXIT_OK

    assert "there are no deployments yet" in capsys.readouterr().out


def test_a_command_is_required(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])

    assert exit_info.value.code == cli.EXIT_USAGE


# ---------------------------------------------------------------------- --until-pulled


def test_until_pulled_returns_as_soon_as_the_image_is_on_the_host(settings, store, clock, capsys):
    code = deploy(settings, store, clock, "--until-pulled", sleep=pulling(store, clock, "run-1"))

    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert "draining: pulled v2" in out
    assert "The image of deployment run-1 is on the host" in out
    assert "node-manager wait run-1" in out
    assert store.load("run-1").phase is Phase.DRAINING, "the deployment goes on without the command"


def test_until_pulled_reports_the_result_of_a_deployment_that_was_already_over(settings, store, clock, capsys):
    ending = (Outcome.SUCCEEDED, None)

    code = deploy(settings, store, clock, "--until-pulled", sleep=pulling(store, clock, "run-1", ending=ending))

    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert "Deployment run-1: succeeded" in out
    assert "is on the host" not in out


def test_until_pulled_exits_with_the_failure_of_the_pull(settings, store, clock, capsys):
    store.submit(Deployment(id="run-1", tag="v2", requested_at="2026-01-01T00:00:00"))
    sleep = finishing(store, clock, "run-1", Outcome.FAILED, failure=FailureKind.PULL_FAILED, message="no such tag")

    assert deploy(settings, store, clock, "--until-pulled", sleep=sleep) == cli.EXIT_FAILED

    assert "no such tag" in capsys.readouterr().out


def test_until_pulled_waits_while_the_daemon_is_busy_with_an_earlier_deployment(settings, store, clock, capsys):
    code = deploy(settings, store, clock, "--until-pulled", "--timeout", "30")

    assert code == cli.EXIT_WAIT_TIMED_OUT
    assert "did not pull the image within 30 s" in capsys.readouterr().err
    assert store.load("run-1").phase is Phase.QUEUED


def test_wait_and_until_pulled_exclude_each_other(capsys):
    with pytest.raises(SystemExit) as exit_info:
        parse("deploy", "--id", "run-1", "--tag", "v2", "--wait", "--until-pulled")

    assert exit_info.value.code == cli.EXIT_USAGE


# ---------------------------------------------------------------------- status


def test_status_shows_what_happened_so_far(settings, store, capsys):
    record = store.submit(Deployment(id="run-1", tag="v2", requested_at="2026-01-01T00:00:00"))
    record.phase = Phase.DRAINING
    record.events = [
        {"at": "2026-01-01T12:00:01.000000+00:00", "phase": "pulling", "note": "running x"},
        {
            "at": "2026-01-01T12:03:15.000000+00:00",
            "phase": "draining",
            "note": "waiting for its turn: node-b is being replaced",
        },
    ]
    store.save(record)

    cli.cmd_status(parse("status", "run-1"), settings)

    out = capsys.readouterr().out
    assert "Deployment run-1: tag v2, phase draining" in out
    assert "[12:00:01] pulling: running x" in out
    assert "[12:03:15] draining: waiting for its turn: node-b is being replaced" in out


def test_status_prints_the_log_of_a_failed_container_only_on_request(settings, store, capsys):
    record = store.submit(Deployment(id="run-1", tag="v2", requested_at="2026-01-01T00:00:00"))
    record.phase = Phase.DONE
    record.outcome = Outcome.ROLLED_BACK
    record.failure = FailureKind.VERIFY_FAILED
    record.failure_logs = "ImportError: no module"
    store.save(record)

    cli.cmd_status(parse("status", "run-1"), settings)
    assert "ImportError" not in capsys.readouterr().out

    cli.cmd_status(parse("status", "run-1", "--logs"), settings)
    assert "ImportError: no module" in capsys.readouterr().out


# ---------------------------------------------------------------------- run


class RecordingDaemon:
    def __init__(self, settings, store, deployer, stop, **kwargs) -> None:
        RecordingDaemon.deployer = deployer

    def run(self) -> None:
        return None


@pytest.mark.parametrize(
    ("environ", "expects_client"),
    [
        ({}, False),
        ({"NODE_MANAGER_DRAIN_ENABLED": "true"}, False),
        ({"NODE_MANAGER_ORCHESTRATOR_URL": "https://logos.example", "NODE_MANAGER_NODE_KEY": "k"}, False),
        (
            {
                "NODE_MANAGER_DRAIN_ENABLED": "true",
                "NODE_MANAGER_ORCHESTRATOR_URL": "https://logos.example",
                "NODE_MANAGER_NODE_KEY": "k",
            },
            True,
        ),
    ],
)
def test_the_daemon_gets_an_orchestrator_client_only_when_the_node_drains(
    tmp_path, monkeypatch, environ, expects_client
):
    monkeypatch.setattr(cli, "Daemon", RecordingDaemon)
    monkeypatch.setattr(cli.signal, "signal", lambda *args: None)
    settings = Settings.from_env({"NODE_MANAGER_STATE_DIR": str(tmp_path / "state"), **environ})

    assert cli.cmd_run(parse("run"), settings) == cli.EXIT_OK

    assert (RecordingDaemon.deployer.orchestrator is not None) is expects_client
