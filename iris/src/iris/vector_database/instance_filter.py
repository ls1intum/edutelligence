"""Filters that keep the lecture rows of one Artemis instance apart from another's.

Every lecture row carries the base URL of the Artemis instance that wrote it twice: in ``base_url`` with word
tokenization, where an equality filter on "https://artemis.example" also matches
"https://artemis-test.artemis.example", and in ``base_url_exact`` with field tokenization, where it matches only
the whole value. A collection switches to the exact property once every row carries it (see
``base_url_exact_backfill``); until then its filters keep the word property, as before.

Ghost rows (still in an index, gone from the object store) of collections older than the exact property never
get the exact value, so exact filters, and the purges built on them, no longer reach them. The census ignores
ghost rows anyway, so they stay as inert index entries.
"""

import threading

from weaviate.classes.query import Filter

_exact_collections: set[str] = set()
_lock = threading.Lock()


def artemis_instance_filter(schema, base_url: str) -> Filter:
    """An equality filter on the base URL for a lecture collection schema.

    :param schema: the schema enum of the collection, with COLLECTION_NAME, BASE_URL and BASE_URL_EXACT
    :param base_url: the Artemis base URL to match
    """
    with _lock:
        exact = schema.COLLECTION_NAME.value in _exact_collections
    if exact:
        return Filter.by_property(schema.BASE_URL_EXACT.value).equal(base_url)
    return Filter.by_property(schema.BASE_URL.value).equal(base_url)


def mark_exact(collection_name: str) -> None:
    """Switch a collection's base URL filters to the exact property."""
    with _lock:
        _exact_collections.add(collection_name)


def is_exact(collection_name: str) -> bool:
    """Whether a collection's base URL filters use the exact property."""
    with _lock:
        return collection_name in _exact_collections
