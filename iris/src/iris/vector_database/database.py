import atexit
import threading
import time

from weaviate import WeaviateClient
from weaviate.classes.init import Auth
from weaviate.classes.query import Filter
from weaviate.connect import ConnectionParams

from iris.common.logging_config import get_logger
from iris.config import settings

from .base_url_exact_backfill import prepare_exact_filters, start_backfill
from .faq_schema import FaqSchema, init_faq_schema
from .lecture_transcription_schema import (
    LectureTranscriptionSchema,
    init_lecture_transcription_schema,
)
from .lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
    init_lecture_unit_page_chunk_schema,
)
from .lecture_unit_schema import LectureUnitSchema, init_lecture_unit_schema
from .lecture_unit_segment_schema import (
    LectureUnitSegmentSchema,
    init_lecture_unit_segment_schema,
)

logger = get_logger(__name__)
batch_update_lock = threading.Lock()

# How long to wait before trying the collection setup again after Weaviate was unavailable.
_SCHEMA_RETRY_SECONDS = 60.0


def _collection_handles(client: WeaviateClient) -> dict:
    """Handles of the collections by name; creating them makes no request, so they also exist while Weaviate is down."""
    return {
        "lectures": client.collections.get(
            LectureUnitPageChunkSchema.COLLECTION_NAME.value
        ),
        "transcriptions": client.collections.get(
            LectureTranscriptionSchema.COLLECTION_NAME.value
        ),
        "lecture_segments": client.collections.get(
            LectureUnitSegmentSchema.COLLECTION_NAME.value
        ),
        "lecture_units": client.collections.get(
            LectureUnitSchema.COLLECTION_NAME.value
        ),
        "faqs": client.collections.get(FaqSchema.COLLECTION_NAME.value),
    }


class VectorDatabase:
    """
    Class to interact with the Weaviate vector database
    """

    _lock = threading.Lock()
    _schema_lock = threading.Lock()
    static_client_instance = None
    _static_collections: dict = {}
    _schemas_ready = False
    _schema_attempted = False
    _next_schema_attempt = 0.0

    def __init__(self):
        with VectorDatabase._lock:
            if not VectorDatabase.static_client_instance:
                auth = (
                    Auth.api_key(settings.weaviate.api_key)
                    if settings.weaviate.api_key
                    else None
                )
                # Built without connecting: _ensure_schemas connects, so an unreachable Weaviate cannot break
                # every pipeline that creates a VectorDatabase; only the calls that need Weaviate fail.
                VectorDatabase.static_client_instance = WeaviateClient(
                    connection_params=ConnectionParams.from_params(
                        http_host=settings.weaviate.host,
                        http_port=settings.weaviate.port,
                        http_secure=settings.weaviate.http_secure,
                        grpc_host=settings.weaviate.host,
                        grpc_port=settings.weaviate.grpc_port,
                        grpc_secure=settings.weaviate.grpc_secure,
                    ),
                    auth_client_secret=auth,
                    skip_init_checks=True,
                )
                atexit.register(VectorDatabase.static_client_instance.close)
                VectorDatabase._static_collections = _collection_handles(
                    VectorDatabase.static_client_instance
                )
        VectorDatabase._ensure_schemas()

        self.client = VectorDatabase.static_client_instance
        collections = VectorDatabase._static_collections
        self.lectures = collections["lectures"]
        self.transcriptions = collections["transcriptions"]
        self.lecture_segments = collections["lecture_segments"]
        self.lecture_units = collections["lecture_units"]
        self.faqs = collections["faqs"]

    @classmethod
    def _ensure_schemas(cls) -> None:
        """Connect and create the collections once per process, retrying while Weaviate is unavailable.

        Running the schema setup on every call is racy: several threads can pass the ``exists()`` check and all
        call ``create()``, the losers getting a 422 "class already exists". So one thread does it. Every caller
        waits for the first attempt, so nothing writes to a collection before it exists. Once an attempt has
        failed, the plain handles stay in place and a background thread retries at most every
        ``_SCHEMA_RETRY_SECONDS``; no caller waits for it, so a Weaviate that hangs cannot slow down a request.
        """
        if cls._schemas_ready or time.monotonic() < cls._next_schema_attempt:
            return
        if not cls._schema_attempted:
            with cls._schema_lock:
                if not cls._schema_attempted:
                    cls._attempt_schema_setup()
            return
        if not cls._schema_lock.acquire(blocking=False):
            return
        if cls._schemas_ready or time.monotonic() < cls._next_schema_attempt:
            cls._schema_lock.release()
            return
        # The retry waits up to the start-up timeout, so it runs off the request; it owns the lock until it ends.
        cls._next_schema_attempt = time.monotonic() + _SCHEMA_RETRY_SECONDS
        try:
            threading.Thread(
                target=cls._retry_schema_setup,
                name="weaviate-setup-retry",
                daemon=True,
            ).start()
        except Exception:
            cls._schema_lock.release()
            logger.warning("Could not start the Weaviate setup retry", exc_info=True)

    @classmethod
    def _retry_schema_setup(cls) -> None:
        try:
            cls._attempt_schema_setup()
        finally:
            cls._schema_lock.release()

    @classmethod
    def _attempt_schema_setup(cls) -> None:
        """One attempt to connect and create the collections; the caller holds ``_schema_lock``."""
        client = cls.static_client_instance
        try:
            if not client.is_connected():
                client.connect()
                logger.info("Weaviate client initialized")
                # Handles taken before connecting are bound to an unknown server version; take them again.
                cls._static_collections = _collection_handles(client)
            cls._static_collections = {
                "lectures": init_lecture_unit_page_chunk_schema(client),
                "transcriptions": init_lecture_transcription_schema(client),
                "lecture_segments": init_lecture_unit_segment_schema(client),
                "lecture_units": init_lecture_unit_schema(client),
                "faqs": init_faq_schema(client),
            }
            cls._schemas_ready = True
            cls._prepare_exact_base_url_filters(client)
        except Exception:
            cls._next_schema_attempt = time.monotonic() + _SCHEMA_RETRY_SECONDS
            if not client.is_connected():
                # A failed connect leaves its connections open; close them before the next attempt opens new ones.
                try:
                    client.close()
                except Exception:
                    logger.warning(
                        "Could not close the failed Weaviate connection", exc_info=True
                    )
            logger.warning(
                "Weaviate is unavailable; could not set up its collections, retrying in %ss",
                _SCHEMA_RETRY_SECONDS,
                exc_info=True,
            )
        finally:
            cls._schema_attempted = True

    @staticmethod
    def _prepare_exact_base_url_filters(client) -> None:
        """Switch marked lecture collections to exact base URL filters and start the backfill of the others.

        A failure here never fails the setup: the filters then stay on the word-tokenized base_url, as before.
        """
        try:
            start_backfill(client, prepare_exact_filters(client))
        except Exception:
            logger.warning(
                "Could not prepare the exact base URL filters; they stay on base_url",
                exc_info=True,
            )

    def delete_collection(self, collection_name):
        """
        Delete a collection from the database
        """
        if self.client.collections.delete(collection_name):
            logger.info("Collection %s deleted", collection_name)
        else:
            logger.error("Collection %s failed to delete", collection_name)

    def delete_object(self, collection_name, property_name, object_property):
        """
        Delete an object from the collection inside the database
        """
        collection = self.client.collections.get(collection_name)
        collection.data.delete_many(
            where=Filter.by_property(property_name).equal(object_property)
        )

    def get_client(self):
        """
        Get the Weaviate client
        """
        return self.client
