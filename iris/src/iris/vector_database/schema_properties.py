from weaviate.classes.config import Property
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
