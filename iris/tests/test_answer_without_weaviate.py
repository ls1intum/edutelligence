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
    return SimpleNamespace(client=client, build=build, clock=clock)


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


def test_the_collection_setup_is_retried_once_the_wait_is_over(
    monkeypatch, fresh_database
):
    lectures = MagicMock()
    init_lectures = MagicMock(side_effect=[RuntimeError("Weaviate down"), lectures])
    monkeypatch.setattr(database, SCHEMA_INITS[0], init_lectures)

    VectorDatabase()
    VectorDatabase()
    assert init_lectures.call_count == 1
    fresh_database.build.assert_called_once()

    fresh_database.clock.now += database._SCHEMA_RETRY_SECONDS + 1
    db = VectorDatabase()

    assert init_lectures.call_count == 2
    assert db.lectures is lectures
    VectorDatabase()
    assert init_lectures.call_count == 2


def test_memories_are_off_for_the_run_while_weaviate_is_unavailable(monkeypatch):
    from iris.common import memiris_setup  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(
        memiris_setup,
        "settings",
        SimpleNamespace(
            memiris=SimpleNamespace(
                enabled=True,
                llm_configuration=SimpleNamespace(embeddings=[]),
            )
        ),
    )
    monkeypatch.setattr(memiris_setup, "Vectorizer", MagicMock())
    monkeypatch.setattr(
        memiris_setup,
        "_create_memory_creation_pipeline",
        MagicMock(side_effect=RuntimeError("Weaviate down")),
    )

    wrapper = memiris_setup.MemirisWrapper(MagicMock(), "artemis-user-1")

    assert wrapper.enabled is False
    assert wrapper.has_memories() is False
    assert not wrapper.create_memories("text", "reference")
