"""Iris keeps answering while Weaviate is unavailable: the lookups that need it are switched off, nothing else fails."""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from iris.pipeline.chat.chat_pipeline import ChatPipeline
from iris.retrieval.faq_retrieval_utils import should_allow_faq_tool
from iris.retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from iris.vector_database import database
from iris.vector_database.database import VectorDatabase
from iris.web.routers.health import health_endpoint, weaviate_health
from iris.web.routers.health.health_model import ModuleStatus, ServiceStatus

SCHEMA_INITS = (
    "init_lecture_unit_page_chunk_schema",
    "init_lecture_transcription_schema",
    "init_lecture_unit_segment_schema",
    "init_lecture_unit_schema",
    "init_faq_schema",
)


def _db_whose_queries_fail():
    db = MagicMock()
    db.lecture_units.query.fetch_objects.side_effect = RuntimeError("Weaviate down")
    db.faqs.query.fetch_objects.side_effect = RuntimeError("Weaviate down")
    return db


def test_the_lecture_and_faq_tools_are_off_while_weaviate_fails():
    db = _db_whose_queries_fail()

    assert should_allow_lecture_tool(db, 7) is False
    assert should_allow_faq_tool(db, 7) is False


def test_the_tools_still_follow_the_index_while_weaviate_answers():
    db = MagicMock()
    db.lecture_units.query.fetch_objects.return_value = SimpleNamespace(
        objects=[object()]
    )
    db.faqs.query.fetch_objects.return_value = SimpleNamespace(objects=[])

    assert should_allow_lecture_tool(db, 7) is True
    assert should_allow_faq_tool(db, 7) is False


def test_the_memory_tool_is_off_while_memories_cannot_be_read():
    wrapper = MagicMock()
    wrapper.has_memories.side_effect = RuntimeError("Weaviate down")
    state = SimpleNamespace(
        dto=SimpleNamespace(user=SimpleNamespace(memiris_enabled=True)),
        memiris_wrapper=wrapper,
    )

    assert ChatPipeline._has_memories(state) is False


def test_an_unavailable_weaviate_is_degraded_and_iris_stays_healthy(monkeypatch):
    monkeypatch.setattr(
        weaviate_health,
        "VectorDatabase",
        MagicMock(side_effect=RuntimeError("Meta endpoint 404")),
    )
    monkeypatch.setattr(
        health_endpoint,
        "MODULES",
        [
            weaviate_health.check_weaviate_status,
            lambda: ("Pipelines", ModuleStatus(status=ServiceStatus.UP)),
        ],
    )

    response = health_endpoint.health(
        request=SimpleNamespace(headers={}), response=SimpleNamespace()
    )

    weaviate_status = response.modules["Weaviate Vector Database"]
    assert weaviate_status.status == ServiceStatus.DEGRADED
    assert "Meta endpoint 404" in weaviate_status.error
    assert response.is_healthy is True


@pytest.fixture
def fresh_database(monkeypatch):
    """A VectorDatabase class with no client yet, connecting to a mock client, on a clock the test moves."""
    monkeypatch.setattr(VectorDatabase, "static_client_instance", None)
    monkeypatch.setattr(VectorDatabase, "_static_collections", {})
    monkeypatch.setattr(VectorDatabase, "_schemas_ready", False)
    monkeypatch.setattr(VectorDatabase, "_schema_attempted", False)
    monkeypatch.setattr(VectorDatabase, "_next_schema_attempt", 0.0)
    client = MagicMock()
    client.is_connected.return_value = False
    build = MagicMock(return_value=client)
    monkeypatch.setattr(database, "WeaviateClient", build)
    monkeypatch.setattr(database.atexit, "register", MagicMock())
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(database.time, "monotonic", lambda: clock.now)
    for name in SCHEMA_INITS[1:]:
        monkeypatch.setattr(database, name, MagicMock(return_value=MagicMock()))
    # The exact base URL filters are covered in test_base_url_exact_backfill; these tests count connection handles
    monkeypatch.setattr(database, "prepare_exact_filters", MagicMock(return_value=[]))
    retries = []

    class _HeldThread:
        """Records the retry instead of starting it, so the test decides when it runs."""

        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            retries.append(self.target)

    monkeypatch.setattr(database.threading, "Thread", _HeldThread)
    return SimpleNamespace(client=client, build=build, clock=clock, retries=retries)


def test_a_pipeline_gets_a_database_while_weaviate_is_unreachable(fresh_database):
    fresh_database.client.connect.side_effect = RuntimeError("Weaviate down")

    db = VectorDatabase()

    fresh_database.client.connect.assert_called_once()
    assert db.client is fresh_database.client
    assert db.faqs is fresh_database.client.collections.get.return_value
    fresh_database.client.collections.get.assert_any_call("Faqs")


def test_a_pipeline_gets_a_database_while_the_collections_cannot_be_set_up(
    monkeypatch, fresh_database
):
    monkeypatch.setattr(
        database,
        SCHEMA_INITS[0],
        MagicMock(side_effect=RuntimeError("Weaviate down")),
    )

    db = VectorDatabase()

    assert db.faqs is fresh_database.client.collections.get.return_value


def test_the_collection_setup_is_retried_in_the_background_once_the_wait_is_over(
    monkeypatch, fresh_database
):
    lectures = MagicMock()
    init_lectures = MagicMock(side_effect=[RuntimeError("Weaviate down"), lectures])
    monkeypatch.setattr(database, SCHEMA_INITS[0], init_lectures)

    VectorDatabase()
    VectorDatabase()
    assert init_lectures.call_count == 1
    assert not fresh_database.retries

    fresh_database.clock.now += database._SCHEMA_RETRY_SECONDS + 1
    VectorDatabase()
    VectorDatabase()

    # The caller did not wait: the retry is handed to one background thread, and only once.
    assert init_lectures.call_count == 1
    assert len(fresh_database.retries) == 1
    assert VectorDatabase._schema_lock.locked()

    fresh_database.retries[0]()

    assert init_lectures.call_count == 2
    assert not VectorDatabase._schema_lock.locked()
    assert VectorDatabase().lectures is lectures
    fresh_database.clock.now += database._SCHEMA_RETRY_SECONDS + 1
    VectorDatabase()
    assert len(fresh_database.retries) == 1


def test_a_failed_connect_is_closed_and_handles_are_taken_again_after_connecting(
    monkeypatch, fresh_database
):
    monkeypatch.setattr(database, SCHEMA_INITS[0], MagicMock(return_value=MagicMock()))
    client = fresh_database.client
    client.connect.side_effect = [RuntimeError("Weaviate down"), None]

    VectorDatabase()
    client.close.assert_called_once()
    handles_before = client.collections.get.call_count

    fresh_database.clock.now += database._SCHEMA_RETRY_SECONDS + 1
    VectorDatabase()
    fresh_database.retries[0]()

    assert client.connect.call_count == 2
    assert client.collections.get.call_count == handles_before + 5
    assert VectorDatabase._schemas_ready is True


def test_a_run_goes_on_without_memories_while_weaviate_is_unavailable(monkeypatch):
    from iris.pipeline import (  # pylint: disable=import-outside-toplevel
        abstract_agent_pipeline,
    )

    monkeypatch.setattr(
        abstract_agent_pipeline,
        "MemirisWrapper",
        MagicMock(side_effect=RuntimeError("Weaviate down")),
    )
    pipeline = MagicMock()
    state = SimpleNamespace(db=SimpleNamespace(client=MagicMock()), dto=MagicMock())

    wrapper = abstract_agent_pipeline.AbstractAgentPipeline._create_memiris_wrapper(
        pipeline, state
    )

    assert wrapper is None
    assert (
        ChatPipeline._has_memories(SimpleNamespace(dto=state.dto, memiris_wrapper=None))
        is False
    )


@pytest.mark.usefixtures("fresh_database")
def test_a_failing_exact_filter_preparation_does_not_fail_the_schema_setup(monkeypatch):
    monkeypatch.setattr(database, SCHEMA_INITS[0], MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(
        database, "prepare_exact_filters", MagicMock(side_effect=RuntimeError("boom"))
    )

    VectorDatabase()

    assert VectorDatabase._schemas_ready is True
