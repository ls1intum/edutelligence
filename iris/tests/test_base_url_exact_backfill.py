"""Tests for the exact base URL filters of the lecture collections and their backfill."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from weaviate.classes.config import Tokenization
from weaviate.exceptions import UnexpectedStatusCodeError

from iris.vector_database import base_url_exact_backfill as backfill
from iris.vector_database import instance_filter
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)
from iris.vector_database.lecture_unit_schema import LectureUnitSchema
from iris.vector_database.schema_properties import (
    BASE_URL_EXACT,
    BASE_URL_EXACT_MARKER,
)

OWN = "https://artemis.example"


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    monkeypatch.setattr(instance_filter, "_exact_collections", set())
    monkeypatch.setattr(backfill, "_started", False)


def _target(weaviate_filter) -> str:
    return weaviate_filter.target


def _config(tokenization=Tokenization.FIELD, description=None, exact=True):
    properties = [SimpleNamespace(name="base_url", tokenization=Tokenization.WORD)]
    if exact:
        properties.append(
            SimpleNamespace(name=BASE_URL_EXACT, tokenization=tokenization)
        )
    return SimpleNamespace(properties=properties, description=description)


def _row(uuid, base_url, exact=None):
    properties = {"base_url": base_url}
    if exact is not None:
        properties[BASE_URL_EXACT] = exact
    return SimpleNamespace(uuid=uuid, properties=properties)


def _status_error(code):
    return UnexpectedStatusCodeError(
        "update failed", httpx.Response(status_code=code, json={"error": []})
    )


class TestArtemisInstanceFilter:
    """Switching each collection's base URL filter on its own."""

    def test_uses_the_word_property_until_the_collection_is_marked(self):
        assert (
            _target(instance_filter.artemis_instance_filter(LectureUnitSchema, OWN))
            == "base_url"
        )

        instance_filter.mark_exact(LectureUnitSchema.COLLECTION_NAME.value)

        assert (
            _target(instance_filter.artemis_instance_filter(LectureUnitSchema, OWN))
            == BASE_URL_EXACT
        )
        # Other collections keep their own state
        assert (
            _target(
                instance_filter.artemis_instance_filter(LectureUnitPageChunkSchema, OWN)
            )
            == "base_url"
        )


class TestPrepareExactFilters:
    """The startup check of every lecture collection."""

    def test_switches_marked_collections_and_returns_every_field_tokenized_one(self):
        configs = {
            schema.COLLECTION_NAME.value: _config()
            for schema in backfill.LECTURE_SCHEMAS
        }
        configs[LectureUnitSchema.COLLECTION_NAME.value] = _config(
            description=BASE_URL_EXACT_MARKER
        )
        client = MagicMock()
        client.collections.get.side_effect = lambda name: SimpleNamespace(
            config=SimpleNamespace(get=lambda: configs[name])
        )

        eligible = backfill.prepare_exact_filters(client)

        assert eligible == list(backfill.LECTURE_SCHEMAS)
        assert instance_filter.is_exact(LectureUnitSchema.COLLECTION_NAME.value)
        assert not instance_filter.is_exact(
            LectureUnitPageChunkSchema.COLLECTION_NAME.value
        )

    def test_never_switches_a_collection_whose_exact_property_is_word_tokenized_or_missing(
        self,
    ):
        configs = {
            schema.COLLECTION_NAME.value: _config()
            for schema in backfill.LECTURE_SCHEMAS
        }
        # Auto-schema created the property from a racing write, with word tokenization
        configs[LectureUnitSchema.COLLECTION_NAME.value] = _config(
            tokenization=Tokenization.WORD, description=BASE_URL_EXACT_MARKER
        )
        configs[LectureUnitPageChunkSchema.COLLECTION_NAME.value] = _config(exact=False)
        client = MagicMock()
        client.collections.get.side_effect = lambda name: SimpleNamespace(
            config=SimpleNamespace(get=lambda: configs[name])
        )

        eligible = backfill.prepare_exact_filters(client)

        assert LectureUnitSchema not in eligible
        assert LectureUnitPageChunkSchema not in eligible
        assert not instance_filter.is_exact(LectureUnitSchema.COLLECTION_NAME.value)


def _collection(rows, description=None):
    collection = MagicMock()
    collection.iterator.return_value = iter(rows)
    collection.config.get.return_value = SimpleNamespace(
        description=description, properties=[]
    )
    return collection


def _client(collection):
    client = MagicMock()
    client.collections.get.return_value = collection
    return client


class TestBackfillCollection:
    """One backfill pass over a collection."""

    def test_fills_missing_values_then_marks_the_collection(self):
        collection = _collection(
            [_row("a", OWN), _row("b", OWN, exact=OWN), _row("c", None)]
        )

        assert backfill.backfill_collection(_client(collection), LectureUnitSchema)

        collection.data.update.assert_called_once_with(
            uuid="a", properties={BASE_URL_EXACT: OWN}
        )
        collection.config.update.assert_called_once_with(
            description=BASE_URL_EXACT_MARKER
        )
        assert instance_filter.is_exact(LectureUnitSchema.COLLECTION_NAME.value)

    def test_fills_a_row_written_later_by_an_older_pyris_when_already_marked(self):
        collection = _collection([_row("a", OWN)], description=BASE_URL_EXACT_MARKER)

        assert backfill.backfill_collection(_client(collection), LectureUnitSchema)

        collection.data.update.assert_called_once()
        collection.config.update.assert_not_called()

    def test_ignores_rows_deleted_meanwhile(self):
        collection = _collection([_row("a", OWN)])
        collection.data.update.side_effect = _status_error(404)

        assert backfill.backfill_collection(_client(collection), LectureUnitSchema)

    def test_does_not_mark_after_a_failed_update(self):
        collection = _collection([_row("a", OWN)])
        collection.data.update.side_effect = _status_error(500)

        assert not backfill.backfill_collection(_client(collection), LectureUnitSchema)

        collection.config.update.assert_not_called()
        assert not instance_filter.is_exact(LectureUnitSchema.COLLECTION_NAME.value)

    def test_does_not_mark_when_two_spellings_differ_only_in_case_or_a_trailing_slash(
        self,
    ):
        collection = _collection(
            [
                _row("a", OWN, exact=OWN),
                _row("b", OWN + "/", exact=OWN + "/"),
                _row("c", "https://Artemis.example", exact="https://Artemis.example"),
            ]
        )

        assert not backfill.backfill_collection(_client(collection), LectureUnitSchema)

        collection.config.update.assert_not_called()


class TestCollapsedSpellingsOnAMarkedCollection:
    """A marked collection that later finds two spellings stays exact and says so."""

    def test_stays_exact_and_keeps_the_marker(self):
        instance_filter.mark_exact(LectureUnitSchema.COLLECTION_NAME.value)
        collection = _collection(
            [_row("a", OWN, exact=OWN), _row("b", OWN + "/", exact=OWN + "/")],
            description=BASE_URL_EXACT_MARKER,
        )

        assert backfill.backfill_collection(_client(collection), LectureUnitSchema)

        collection.config.update.assert_not_called()
        assert instance_filter.is_exact(LectureUnitSchema.COLLECTION_NAME.value)


class TestPrepareFailures:
    """A collection whose configuration cannot be read does not stop the others."""

    def test_a_failing_collection_is_skipped(self):
        configs = {
            schema.COLLECTION_NAME.value: _config()
            for schema in backfill.LECTURE_SCHEMAS
        }

        def get(name):
            if name == LectureUnitPageChunkSchema.COLLECTION_NAME.value:
                raise RuntimeError("timeout")
            return SimpleNamespace(config=SimpleNamespace(get=lambda: configs[name]))

        client = MagicMock()
        client.collections.get.side_effect = get

        eligible = backfill.prepare_exact_filters(client)

        assert LectureUnitPageChunkSchema not in eligible
        assert LectureUnitSchema in eligible


class TestStartBackfill:
    """The background pass runs once per process."""

    def test_starts_one_thread_only(self, monkeypatch):
        started = []
        monkeypatch.setattr(
            backfill.threading,
            "Thread",
            lambda target, args, name, daemon: SimpleNamespace(
                start=lambda: started.append(args)
            ),
        )

        backfill.start_backfill(MagicMock(), [LectureUnitSchema])
        backfill.start_backfill(MagicMock(), [LectureUnitSchema])

        assert len(started) == 1

    def test_one_failing_collection_does_not_stop_the_others(self):
        client = MagicMock()
        good = _collection([_row("a", OWN)])
        client.collections.get.side_effect = lambda name: (
            good
            if name == LectureUnitSchema.COLLECTION_NAME.value
            else (_ for _ in ()).throw(RuntimeError("down"))
        )

        backfill.backfill_all(client, [LectureUnitPageChunkSchema, LectureUnitSchema])

        assert instance_filter.is_exact(LectureUnitSchema.COLLECTION_NAME.value)
