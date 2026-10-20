from weaviate.classes.config import DataType, Property, Tokenization
from weaviate.collections import Collection
from weaviate.exceptions import UnexpectedStatusCodeError, WeaviateInvalidInputError


def add_property_if_missing(collection: Collection, new_property: Property) -> None:
    """Add a property to an existing collection unless it is already there.

    Every pipeline initializes its schema when it is built, so several threads can reach this at once. A
    concurrent initializer that added the property between the check and the add is not an error.
    """

    def property_exists() -> bool:
        return any(
            schema_property.name == new_property.name
            for schema_property in collection.config.get(simple=True).properties
        )

    if property_exists():
        return
    try:
        collection.config.add_property(new_property)
    except (UnexpectedStatusCodeError, WeaviateInvalidInputError):
        # Another concurrent initializer may have added the property after our check.
        if not property_exists():
            raise


BASE_URL_EXACT = "base_url_exact"

# Description of a lecture collection whose rows all carry an exact base URL, so its base URL filters can
# use the exact property. Collections created with that property get it at creation; older ones once their
# backfill has finished.
BASE_URL_EXACT_MARKER = "iris:base_url_exact=v1"


def base_url_exact_property() -> Property:
    """The base URL of the Artemis instance, stored as one token so an equality filter matches it exactly.

    The older ``base_url`` property uses the default word tokenization, with which an equality filter on
    "https://artemis.example" also matches "https://artemis-test.artemis.example". Tokenization cannot change
    once a property exists, so the exact value lives in this separate property.
    """
    return Property(
        name=BASE_URL_EXACT,
        description="The base URL of the Artemis instance, matched exactly",
        data_type=DataType.TEXT,
        tokenization=Tokenization.FIELD,
        index_searchable=False,
    )
