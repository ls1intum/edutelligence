"""The ``node-manager`` command.

``run`` starts the daemon, which is the main process of the container. The other commands are for the people and the
scripts that talk to it, usually through ``docker exec``:

* ``deploy`` queues a deployment and, with ``--wait``, follows it to its end and exits with its result.
* ``wait`` attaches to a deployment that is already queued, for example after a dropped SSH connection.
* ``status`` shows a deployment. ``ping`` tells whether the daemon is alive.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Callable, TextIO

from logos_node_manager.config import Settings
from logos_node_manager.daemon import Daemon
from logos_node_manager.deployer import Deployer
from logos_node_manager.docker_ops import Docker
from logos_node_manager.errors import StateError
from logos_node_manager.runner import SubprocessRunner
from logos_node_manager.state import Deployment, Outcome, StateStore, utc_now, validate_id, validate_tag

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
# The deployment finished, but not as asked: the new version failed and the previous one runs again.
EXIT_ROLLED_BACK = 10
EXIT_FAILED = 11
# The wait ended before the deployment did. The deployment itself keeps running.
EXIT_WAIT_TIMED_OUT = 12

DEFAULT_WAIT_S = 2400.0
FOLLOW_POLL_S = 2.0
# The daemon writes its heartbeat every 5 s.
HEARTBEAT_MAX_AGE_S = 30.0
DOCKER_CONFIG_FILE = Path(os.environ.get("DOCKER_CONFIG", "/root/.docker")) / "config.json"

EXIT_CODES = {
    Outcome.SUCCEEDED: EXIT_OK,
    Outcome.UNCHANGED: EXIT_OK,
    Outcome.ROLLED_BACK: EXIT_ROLLED_BACK,
    Outcome.FAILED: EXIT_FAILED,
}


def exit_code_for(deployment: Deployment) -> int:
    return EXIT_CODES[deployment.outcome] if deployment.outcome else EXIT_ERROR


# ---------------------------------------------------------------------- Output


def follow(
    store: StateStore,
    deployment_id: str,
    *,
    timeout_s: float,
    out: TextIO,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Deployment | None:
    """Print the events of a deployment as they appear. Returns the last record read, finished or not."""
    deadline = clock() + timeout_s
    shown = 0
    record: Deployment | None = None
    while True:
        record = store.load(deployment_id) or record
        if record is not None:
            for event in record.events[shown:]:
                line = f"[{event['at'][11:19]}] {event['phase']}"
                print(f"{line}: {event['note']}" if event["note"] else line, file=out)
            shown = len(record.events)
            if record.finished:
                return record
        if clock() >= deadline:
            return record
        sleep(FOLLOW_POLL_S)


def print_report(record: Deployment, out: TextIO, *, show_logs: bool) -> None:
    result = record.outcome.value if record.outcome else "unfinished"
    kind = f" ({record.failure.value})" if record.failure else ""
    print(f"Deployment {record.id}: {result}{kind}", file=out)
    if record.message:
        print(record.message, file=out)
    if show_logs and record.failure_logs:
        print("--- end of the log of the failed container ---", file=out)
        print(record.failure_logs, file=out)
        print("--- end of the log ---", file=out)


def report_after_wait(
    store: StateStore,
    deployment_id: str,
    *,
    timeout_s: float,
    show_logs: bool,
    out: TextIO,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> int:
    record = follow(store, deployment_id, timeout_s=timeout_s, out=out, clock=clock, sleep=sleep)
    if record is None:
        print(f"error: there is no deployment {deployment_id}", file=sys.stderr)
        return EXIT_NOT_FOUND
    if not record.finished:
        print(
            f"error: deployment {deployment_id} did not finish within {int(timeout_s)} s. It keeps running. "
            f"Attach again with: node-manager wait {deployment_id}",
            file=sys.stderr,
        )
        return EXIT_WAIT_TIMED_OUT
    print_report(record, out, show_logs=show_logs)
    return exit_code_for(record)


# ---------------------------------------------------------------------- Commands


def cmd_deploy(
    args: argparse.Namespace,
    settings: Settings,
    *,
    out: TextIO | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    out = out or sys.stdout
    store = StateStore(settings.state_dir)
    try:
        deployment = store.submit(
            Deployment(
                id=validate_id(args.id),
                tag=validate_tag(args.tag),
                requested_at=utc_now(),
                requested_by=args.requested_by,
            )
        )
    except (ValueError, StateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    age = store.heartbeat_age()
    if age is None or age > HEARTBEAT_MAX_AGE_S:
        print("warning: the node manager daemon does not answer. The request waits until it runs.", file=sys.stderr)
    print(f"Deployment {deployment.id} is queued for tag {deployment.tag}", file=out)
    if not args.wait:
        return EXIT_OK
    return report_after_wait(
        store,
        deployment.id,
        timeout_s=args.timeout,
        show_logs=not args.no_logs,
        out=out,
        clock=clock,
        sleep=sleep,
    )


def cmd_wait(
    args: argparse.Namespace,
    settings: Settings,
    *,
    out: TextIO | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    try:
        validate_id(args.id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return report_after_wait(
        StateStore(settings.state_dir),
        args.id,
        timeout_s=args.timeout,
        show_logs=not args.no_logs,
        out=out or sys.stdout,
        clock=clock,
        sleep=sleep,
    )


def cmd_status(args: argparse.Namespace, settings: Settings, *, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    store = StateStore(settings.state_dir)
    try:
        record = store.load(validate_id(args.id)) if args.id else store.latest()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if record is None:
        print("there is no such deployment" if args.id else "there are no deployments yet", file=out)
        return EXIT_NOT_FOUND if args.id else EXIT_OK
    if args.json:
        print(json.dumps(record.to_dict(), indent=2, sort_keys=True), file=out)
        return EXIT_OK
    print(f"Deployment {record.id}: tag {record.tag}, phase {record.phase.value}", file=out)
    if record.finished:
        print_report(record, out, show_logs=False)
    return EXIT_OK


def cmd_ping(args: argparse.Namespace, settings: Settings) -> int:
    age = StateStore(settings.state_dir).heartbeat_age()
    if age is not None and age <= args.max_age:
        return EXIT_OK
    print("the node manager daemon is not running", file=sys.stderr)
    return EXIT_ERROR


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    stop = threading.Event()
    docker = Docker(settings, SubprocessRunner())
    store = StateStore(settings.state_dir)
    deployer = Deployer(settings, docker, store, should_stop=stop.is_set)
    daemon = Daemon(settings, store, deployer, stop, docker=docker, registry_login_file=DOCKER_CONFIG_FILE)
    # Stop between steps. A deployment that is cut off continues from its recorded phase at the next start.
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    daemon.run()
    return EXIT_OK


# ---------------------------------------------------------------------- Entry point


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="node-manager", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="start the daemon")
    run.set_defaults(handler=cmd_run)

    deploy = commands.add_parser("deploy", help="queue a deployment")
    deploy.add_argument("--id", required=True, help="unique id of the deployment; repeating an id attaches to it")
    deploy.add_argument("--tag", required=True, help="image tag to deploy")
    deploy.add_argument("--requested-by", default="", help="free text for the record, for example a CI run URL")
    deploy.add_argument("--wait", action="store_true", help="follow the deployment and exit with its result")
    deploy.add_argument("--timeout", type=float, default=DEFAULT_WAIT_S, help="seconds to wait (default: %(default)s)")
    deploy.add_argument("--no-logs", action="store_true", help="do not print the log of a failed container")
    deploy.set_defaults(handler=cmd_deploy)

    wait = commands.add_parser("wait", help="follow a deployment that is already queued")
    wait.add_argument("id")
    wait.add_argument("--timeout", type=float, default=DEFAULT_WAIT_S, help="seconds to wait (default: %(default)s)")
    wait.add_argument("--no-logs", action="store_true", help="do not print the log of a failed container")
    wait.set_defaults(handler=cmd_wait)

    status = commands.add_parser("status", help="show a deployment (default: the latest)")
    status.add_argument("id", nargs="?")
    status.add_argument("--json", action="store_true", help="print the whole record")
    status.set_defaults(handler=cmd_status)

    ping = commands.add_parser("ping", help="exit 0 if the daemon is alive")
    ping.add_argument("--max-age", type=float, default=HEARTBEAT_MAX_AGE_S, help="seconds (default: %(default)s)")
    ping.set_defaults(handler=cmd_ping)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.handler(args, settings)
