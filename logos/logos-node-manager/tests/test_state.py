"""Deployment records on disk."""

from __future__ import annotations

import logging
import os
import time

import pytest

from logos_node_manager.errors import StateError
from logos_node_manager.state import Deployment, FailureKind, Outcome, Phase, validate_id, validate_tag


def deployment(deployment_id: str = "run-1", tag: str = "v2", requested_at: str = "2026-01-01T00:00:00") -> Deployment:
    return Deployment(id=deployment_id, tag=tag, requested_at=requested_at)


def test_a_record_survives_a_round_trip(store):
    record = deployment()
    record.phase = Phase.DONE
    record.outcome = Outcome.ROLLED_BACK
    record.failure = FailureKind.VERIFY_FAILED
    record.events.append({"at": "2026-01-01T00:00:01", "phase": "pulling", "note": "x"})
    store.submit(record)
    store.save(record)

    loaded = store.load("run-1")

    assert loaded == record
    assert loaded.finished


def test_submitting_the_same_deployment_again_attaches_to_the_first(store):
    first = store.submit(deployment())
    first.phase = Phase.PULLING
    store.save(first)

    second = store.submit(deployment())

    assert second.phase is Phase.PULLING
    assert len(store.all()) == 1


def test_an_id_cannot_be_reused_for_another_tag(store):
    store.submit(deployment(tag="v2"))

    with pytest.raises(StateError, match="already used for tag v2"):
        store.submit(deployment(tag="v3"))


@pytest.mark.parametrize("value", ["", "../etc/passwd", "a/b", ".hidden", "x" * 65, "has space"])
def test_unsafe_ids_are_rejected(value):
    with pytest.raises(ValueError):
        validate_id(value)


@pytest.mark.parametrize("value", ["", "-leading-dash", "a:b", "x" * 129, "has space", "a/b"])
def test_invalid_tags_are_rejected(value):
    with pytest.raises(ValueError):
        validate_tag(value)


@pytest.mark.parametrize("value", ["latest", "pr-1187", "v1.2.3", "1234567890-1", "A_b.c-d", "previous-1", "Previous"])
def test_ordinary_ids_and_tags_are_accepted(value):
    assert validate_id(value) == value
    assert validate_tag(value) == value


def test_the_tag_previous_is_reserved_for_the_rollback_image():
    with pytest.raises(ValueError, match="reserved"):
        validate_tag("previous")


def test_a_deployment_for_the_reserved_tag_is_not_queued(store):
    with pytest.raises(ValueError, match="reserved"):
        store.submit(deployment(tag="previous"))

    assert store.all() == []


def test_deployments_run_oldest_request_first(store):
    store.submit(deployment("late", requested_at="2026-01-01T00:00:09"))
    store.submit(deployment("early", requested_at="2026-01-01T00:00:01"))

    assert store.next_unfinished().id == "early"


def test_a_finished_deployment_is_not_picked_up_again(store):
    record = store.submit(deployment())
    record.phase = Phase.DONE
    record.outcome = Outcome.SUCCEEDED
    store.save(record)

    assert store.next_unfinished() is None
    assert store.latest().id == "run-1"


@pytest.mark.parametrize("name", ["run 1.json", "run-1 (copy).json", "x" * 65 + ".json", ".hidden.json"])
def test_a_file_whose_name_is_not_a_deployment_id_is_ignored(store, name):
    store.submit(deployment("good"))
    (store.deployments_dir / name).write_text("{}", encoding="utf-8")

    assert [record.id for record in store.all()] == ["good"]
    assert store.next_unfinished().id == "good"
    assert store.latest().id == "good"


def test_an_ignored_file_is_reported_once_and_not_on_every_pass(store, caplog):
    store.ensure()
    (store.deployments_dir / "run 1.json").write_text("{}", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            store.all()

    assert caplog.text.count("run 1.json") == 1


def test_pruning_deletes_finished_records_and_leaves_ignored_files_alone(store):
    old = deployment("old")
    store.submit(old)
    old.phase = Phase.DONE
    old.outcome = Outcome.SUCCEEDED
    store.save(old)
    (store.deployments_dir / "run 1.json").write_text("{}", encoding="utf-8")

    store.prune(keep=0)

    assert not (store.deployments_dir / "old.json").exists()
    assert (store.deployments_dir / "run 1.json").exists()


def test_a_record_that_cannot_be_read_is_skipped(store):
    store.submit(deployment("good"))
    (store.deployments_dir / "broken.json").write_text("{not json", encoding="utf-8")

    assert [record.id for record in store.all()] == ["good"]
    assert store.load("broken") is None


def test_unknown_fields_in_a_record_are_ignored(store):
    store.submit(deployment())
    path = store.deployments_dir / "run-1.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"tag"', '"future_field": 1, "tag"'), encoding="utf-8")

    assert store.load("run-1").tag == "v2"


def test_only_the_newest_finished_records_are_kept(store):
    for index in range(5):
        record = store.submit(deployment(f"run-{index}", requested_at=f"2026-01-01T00:00:0{index}"))
        record.phase = Phase.DONE
        record.outcome = Outcome.SUCCEEDED
        store.save(record)
    pending = store.submit(deployment("pending", requested_at="2026-01-01T00:00:09"))

    store.prune(keep=2)

    assert [record.id for record in store.all()] == ["run-3", "run-4", pending.id]


def test_saving_leaves_no_temporary_files(store):
    record = store.submit(deployment())
    store.save(record)

    assert sorted(path.name for path in store.deployments_dir.iterdir()) == ["run-1.json"]


def test_the_heartbeat_reports_its_age(store):
    assert store.heartbeat_age() is None

    store.touch_heartbeat()
    assert store.heartbeat_age() < 5

    old = time.time() - 120
    os.utime(store.heartbeat_file, (old, old))
    assert store.heartbeat_age() > 100
