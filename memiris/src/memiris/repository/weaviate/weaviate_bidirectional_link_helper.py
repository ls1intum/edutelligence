from uuid import UUID

from weaviate.collections import Collection
from weaviate.collections.classes.data import DataReference
from weaviate.collections.classes.grpc import QueryReference


class WeaviateBidirectionalLinkHelper:
    """
    Helper class to manage bidirectional links in Weaviate.
    """

    @staticmethod
    def add_link(
        entity1: UUID,
        entity2: UUID,
        property1: str,
        property2: str,
        collection1: Collection,
        collection2: Collection,
    ) -> None:
        """
        Add a bidirectional link between two objects in Weaviate.
        """
        if not WeaviateBidirectionalLinkHelper.link_exists(
            entity1, entity2, property1, property2, collection1, collection2
        ):
            collection1.data.reference_add(entity1, property1, entity2)
            collection2.data.reference_add(entity2, property2, entity1)

    @staticmethod
    def remove_link(
        entity1: UUID,
        entity2: UUID,
        property1: str,
        property2: str,
        collection1: Collection,
        collection2: Collection,
    ) -> None:
        """
        Remove a bidirectional link between two objects in Weaviate.
        """
        if WeaviateBidirectionalLinkHelper.link_exists(
            entity1, entity2, property1, property2, collection1, collection2
        ):
            collection1.data.reference_delete(entity1, property1, entity2)
            collection2.data.reference_delete(entity2, property2, entity1)

    @staticmethod
    def link_exists(
        entity1: UUID,
        entity2: UUID,
        property1: str,
        property2: str,
        collection1: Collection,
        collection2: Collection,
    ) -> bool:
        """
        Check if a bidirectional link exists between two objects in Weaviate.
        """
        refs1 = collection1.query.fetch_object_by_id(
            uuid=entity1, return_references=QueryReference(link_on=property1)
        ).references

        refs2 = collection2.query.fetch_object_by_id(
            uuid=entity2, return_references=QueryReference(link_on=property2)
        ).references

        return (
            refs1 is not None
            and property1 in refs1
            and any(ref.uuid == entity2 for ref in refs1[property1].objects)
            and refs2 is not None
            and property2 in refs2
            and any(ref.uuid == entity1 for ref in refs2[property2].objects)
        )

    @staticmethod
    def add_links(
        entity1: UUID,
        entities2: list[UUID],
        property1: str,
        property2: str,
        collection1: Collection,
        collection2: Collection,
    ) -> None:
        """
        Add multiple bidirectional links from one object to multiple others.
        """
        if entities2:
            collection1.data.reference_add_many(
                [DataReference(property1, entity1, entity2) for entity2 in entities2]
            )
            collection2.data.reference_add_many(
                [DataReference(property2, entity2, entity1) for entity2 in entities2]
            )

    @staticmethod
    def remove_links(
        entity1: UUID,
        entities2: list[UUID],
        property1: str,
        property2: str,
        collection1: Collection,
        collection2: Collection,
    ) -> None:
        """
        Remove multiple bidirectional links from one object to multiple others.
        """
        for entity2 in entities2:
            WeaviateBidirectionalLinkHelper.remove_link(
                entity1, entity2, property1, property2, collection1, collection2
            )

    @staticmethod
    def update_links(
        entity1: UUID,
        entities2: list[UUID],
        property1: str,
        property2: str,
        collection1: Collection,
        collection2: Collection,
    ) -> None:
        """
        Update bidirectional links by removing existing ones and adding new ones.
        """
        # Remove existing links
        existing_refs = collection1.query.fetch_object_by_id(
            uuid=entity1, return_references=QueryReference(link_on=property1)
        ).references

        # Delete existing links that are not in the new list
        if existing_refs and property1 in existing_refs:
            for ref in existing_refs[property1].objects:
                if ref.uuid not in [e for e in entities2]:
                    collection1.data.reference_delete(entity1, property1, ref.uuid)
                    collection2.data.reference_delete(ref.uuid, property2, entity1)

        # Remove existing links in the second collection
        existing_ref_ids = (
            [id.uuid for id in existing_refs[property1].objects if id.uuid in entities2]
            if existing_refs and property1 in existing_refs
            else []
        )
        new_entities2 = [
            entity for entity in entities2 if entity not in existing_ref_ids
        ]

        # Add new links
        WeaviateBidirectionalLinkHelper.add_links(
            entity1, new_entities2, property1, property2, collection1, collection2
        )
