"""The in-memory ingestion log buffer Artemis reads over the internal endpoint.

The buffer exists because Iris logs only to stdout: when the log collector is
unavailable, this is the only way an administrator can see why an ingestion run
failed, so it has to capture DEBUG records and whole tracebacks, and it has to
stay bounded while doing it.
"""

import logging

from iris.common import recent_logs


def setup_function() -> None:
    recent_logs.clear()
    recent_logs.install()


def teardown_function() -> None:
    recent_logs.clear()


def test_captures_debug_records_from_a_captured_logger():
    # DEBUG is the level the whole feature exists for: the ingestion story is told at DEBUG, and the
    # root level is higher, so install() has to lower the captured loggers for these to arrive at all.
    logging.getLogger("iris.pipeline.example").debug("preparing %s pages", 12)

    records = recent_logs.snapshot()

    assert len(records) == 1
    assert records[0]["level"] == "DEBUG"
    assert records[0]["message"] == "preparing 12 pages"
    assert records[0]["logger"] == "iris.pipeline.example"


def test_keeps_the_traceback_of_a_failed_run():
    # The error key Artemis receives names a failure without explaining it; the traceback is the reason.
    try:
        raise ValueError("vision model returned nothing")
    except ValueError:
        logging.getLogger("iris.pipeline.example").exception("slide vision failed")

    records = recent_logs.snapshot()

    assert records[0]["stackTrace"] is not None
    assert "ValueError" in records[0]["stackTrace"]
    assert "vision model returned nothing" in records[0]["stackTrace"]


def test_ignores_loggers_outside_the_ingestion_story():
    # Attaching to the root logger would bury ingestion in unrelated request traffic and widen what is
    # exposed; only the captured loggers are collected.
    logging.getLogger("some.unrelated.library").error("noise")

    assert recent_logs.snapshot() == []


def test_returns_newest_first_and_honours_the_limit():
    logger = logging.getLogger("iris.retrieval.example")
    for index in range(5):
        logger.info("record %d", index)

    records = recent_logs.snapshot(limit=2)

    assert [record["message"] for record in records] == ["record 4", "record 3"]


def test_filters_by_level():
    logger = logging.getLogger("iris.retrieval.example")
    logger.debug("a debug line")
    logger.error("an error line")

    records = recent_logs.snapshot(level="error")

    assert len(records) == 1
    assert records[0]["message"] == "an error line"


def test_is_bounded_so_a_long_run_cannot_grow_without_limit():
    capacity = recent_logs._CAPACITY  # pylint: disable=protected-access
    logger = logging.getLogger("iris.pipeline.example")
    for index in range(capacity + 50):
        logger.info("record %d", index)

    records = recent_logs.snapshot(limit=capacity)

    assert len(records) == capacity
    # The oldest were evicted, so the newest record is still the most recent one logged.
    assert records[0]["message"] == f"record {capacity + 49}"


def test_install_is_idempotent():
    recent_logs.install()
    recent_logs.install()

    logging.getLogger("iris.pipeline.example").info("once")

    assert len(recent_logs.snapshot()) == 1
