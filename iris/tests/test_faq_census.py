"""Tests for the FAQ census, the FAQ row write and delete, and the FAQ DTO defaults."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from iris.domain.data.faq_dto import FaqDTO
from iris.domain.ingestion.deletion_pipeline_execution_dto import (
    FaqDeletionExecutionDto,
)
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    FaqIngestionPipelineExecutionDto,
)
from iris.pipeline.faq_ingestion_pipeline import FaqIngestionPipeline
from iris.vector_database.faq_schema import FaqSchema
from iris.web.routers import faq_census

OWN = "https://artemis.example"
OTHER = "https://other.example"


def _row(course_id, faq_id, base_url=None, fingerprint=None, uuid="u"):
    properties = {
        FaqSchema.COURSE_ID.value: course_id,
        FaqSchema.FAQ_ID.value: faq_id,
    }
    if base_url is not None:
        properties[FaqSchema.BASE_URL.value] = base_url
    if fingerprint is not None:
        properties[FaqSchema.CONTENT_FINGERPRINT.value] = fingerprint
    return SimpleNamespace(uuid=uuid, properties=properties)


def _filter_parts(weaviate_filter) -> list:
    """Every (target, value) pair of a Weaviate filter tree, with "not" marking negated parts."""
    parts = []

    def walk(node, negated=False):
        children = [
            value
            for value in vars(node).values()
            if isinstance(value, list) and value and hasattr(value[0], "__dict__")
        ]
        if type(node).__name__ == "_FilterNot":
            for child_list in children:
                for child in child_list:
                    walk(child, True)
            return
        if hasattr(node, "target"):
            value = getattr(node, "value", None)
            values = value if isinstance(value, list) else [value]
            for item in values:
                parts.append(("not" if negated else "is", node.target, str(item)))
        for child_list in children:
            for child in child_list:
                walk(child, negated)

    walk(weaviate_filter)
    return parts


class TestGroupRows:
    """Grouping of confirmed rows by course and FAQ."""

    def test_counts_owned_and_legacy_rows_apart(self):
        entries = faq_census.group_rows(
            [_row(1, 10, OWN, "v1:a"), _row(1, 10), _row(1, 11)], OWN
        )

        assert [(e.course_id, e.faq_id) for e in entries] == [(1, 10), (1, 11)]
        assert entries[0].owned_row_count == 1
        assert entries[0].legacy_row_count == 1
        assert entries[0].owned_fingerprint == "v1:a"
        assert entries[1].owned_row_count == 0
        assert entries[1].legacy_row_count == 1
        assert entries[1].owned_fingerprint is None

    def test_reports_the_fingerprint_of_agreeing_duplicates_and_none_for_disagreeing_ones(
        self,
    ):
        entries = faq_census.group_rows(
            [
                _row(1, 10, OWN, "v1:a"),
                _row(1, 10, OWN, "v1:a"),
                _row(1, 11, OWN, "v1:a"),
                _row(1, 11, OWN, "v1:b"),
            ],
            OWN,
        )

        assert entries[0].owned_row_count == 2
        assert entries[0].owned_fingerprint == "v1:a"
        assert entries[1].owned_row_count == 2
        assert entries[1].owned_fingerprint is None


class TestCensusEndpoint:
    """The census endpoint over a fake collection."""

    def test_ignores_other_instances_and_ghost_rows(self):
        rows = [
            _row(1, 10, OWN, "v1:a", uuid="own"),
            _row(1, 10, OTHER, "v1:x", uuid="other"),
            _row(1, 11, None, None, uuid="legacy"),
            _row(1, 12, OWN, "v1:c", uuid="ghost"),
        ]
        collection = MagicMock()
        collection.iterator.return_value = iter(rows)
        collection.query.fetch_object_by_id.side_effect = lambda uid: (
            None if uid == "ghost" else object()
        )

        with patch.object(faq_census, "VectorDatabase") as database:
            database.return_value.faqs = collection
            census = faq_census.get_faq_census(base_url="https%3A%2F%2Fartemis.example")

        assert [
            (e.faq_id, e.owned_row_count, e.legacy_row_count) for e in census.faqs
        ] == [
            (10, 1, 0),
            (11, 0, 1),
        ]
        checked = [
            call.args[0] for call in collection.query.fetch_object_by_id.call_args_list
        ]
        assert "other" not in checked

    def test_a_read_error_fails_the_request_instead_of_a_partial_list(self):
        def failing_iterator(**_kwargs):
            yield _row(1, 10, OWN, "v1:a")
            raise RuntimeError("weaviate unavailable")

        collection = MagicMock()
        collection.iterator.side_effect = failing_iterator

        with patch.object(faq_census, "VectorDatabase") as database:
            database.return_value.faqs = collection
            with pytest.raises(RuntimeError):
                faq_census.get_faq_census(base_url=OWN)


def _pipeline(collection):
    pipeline = FaqIngestionPipeline.__new__(FaqIngestionPipeline)
    pipeline.collection = collection
    pipeline.llm_embedding = MagicMock()
    pipeline.llm_embedding.embed.return_value = [0.1, 0.2]
    pipeline.tokens = []
    return pipeline


OWN_UUID = "00000000-0000-0000-0000-000000000001"
OTHER_UUID = "00000000-0000-0000-0000-000000000002"
LEGACY_UUID = "00000000-0000-0000-0000-000000000003"


class TestDeleteFaq:
    """Deletion of one FAQ's rows for this instance."""

    def test_keeps_rows_of_other_instances_and_matches_by_identity(self):
        collection = MagicMock()
        collection.query.fetch_objects.return_value = SimpleNamespace(
            objects=[
                _row(1, 10, OWN, uuid=OWN_UUID),
                _row(1, 10, OTHER, uuid=OTHER_UUID),
                _row(1, 10, None, uuid=LEGACY_UUID),
            ]
        )
        collection.data.delete_many.return_value = SimpleNamespace(
            failed=0, successful=2, objects=None
        )

        assert _pipeline(collection).delete_faq(10, 1, OWN)

        parts = _filter_parts(collection.data.delete_many.call_args.kwargs["where"])
        assert ("is", "faq_id", "10") in parts
        assert ("is", "course_id", "1") in parts
        assert ("not", "_id", OTHER_UUID) in parts
        assert not any(part[2] in (OWN_UUID, LEGACY_UUID) for part in parts)

    def test_matches_by_identity_only_when_no_other_instance_has_rows(self):
        collection = MagicMock()
        collection.query.fetch_objects.return_value = SimpleNamespace(
            objects=[_row(1, 10, None, uuid=LEGACY_UUID)]
        )
        collection.data.delete_many.return_value = SimpleNamespace(
            failed=0, successful=1, objects=None
        )

        _pipeline(collection).delete_faq(10, 1, OWN)

        parts = _filter_parts(collection.data.delete_many.call_args.kwargs["where"])
        assert sorted(parts) == [("is", "course_id", "1"), ("is", "faq_id", "10")]

    def test_raises_when_rows_cannot_be_deleted(self):
        collection = MagicMock()
        collection.query.fetch_objects.return_value = SimpleNamespace(objects=[])
        collection.data.delete_many.return_value = SimpleNamespace(
            failed=1, successful=0, objects=[SimpleNamespace(error="boom")]
        )

        with pytest.raises(Exception):
            _pipeline(collection).delete_faq(10, 1, OWN)


class TestInsertFaq:
    """Writing one FAQ row."""

    def test_stores_base_url_and_fingerprint(self):
        collection = MagicMock()
        faq = FaqDTO(faqId=10, courseId=1, questionTitle="Q", contentFingerprint="v1:a")

        _pipeline(collection).insert_faq(faq, OWN)

        properties = collection.data.insert.call_args.kwargs["properties"]
        assert properties[FaqSchema.BASE_URL.value] == OWN
        assert properties[FaqSchema.CONTENT_FINGERPRINT.value] == "v1:a"
        assert properties[FaqSchema.QUESTION_ANSWER.value] == ""

    def test_a_rejected_write_raises(self):
        collection = MagicMock()
        collection.data.insert.side_effect = RuntimeError("rejected")

        with pytest.raises(RuntimeError):
            _pipeline(collection).insert_faq(FaqDTO(faqId=10, courseId=1), OWN)


class TestFaqPayloads:
    """Payloads of old and new Artemis versions."""

    SETTINGS = {
        "authenticationToken": "token",
        "artemisBaseUrl": OWN,
        "variant": "default",
    }

    def test_old_artemis_payload_without_answer_and_fingerprint_is_accepted(self):
        dto = FaqIngestionPipelineExecutionDto.model_validate(
            {
                "pyrisFaqWebhookDTO": {
                    "faqId": 10,
                    "courseId": 1,
                    "questionTitle": "Q",
                    "courseName": "C",
                },
                "settings": self.SETTINGS,
            }
        )

        assert dto.faq.question_answer == ""
        assert dto.faq.content_fingerprint is None

    def test_minimal_and_full_deletion_payloads_are_accepted(self):
        minimal = FaqDeletionExecutionDto.model_validate(
            {
                "pyrisFaqWebhookDTO": {"faqId": 10, "courseId": 1},
                "settings": self.SETTINGS,
            }
        )
        full = FaqDeletionExecutionDto.model_validate(
            {
                "pyrisFaqWebhookDTO": {
                    "faqId": 10,
                    "courseId": 1,
                    "questionTitle": "Q",
                    "questionAnswer": "A",
                    "courseName": "C",
                    "courseDescription": "D",
                },
                "settings": self.SETTINGS,
            }
        )

        assert minimal.faq.faq_id == full.faq.faq_id == 10
