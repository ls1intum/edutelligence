from abc import ABC, abstractmethod
from typing import List, Optional, Sequence


class BaseRepository[Entity, EntityId](ABC):
    """
    BaseRepository is an abstract generic class that defines the basic CRUD operations for a repository.
    """

    @abstractmethod
    def save(self, tenant: str, entity: Entity) -> Entity:
        pass

    def save_all(self, tenant: str, entities: List[Entity]) -> List[Entity]:
        return [self.save(tenant, entity) for entity in entities]

    @abstractmethod
    def find(self, tenant: str, entity_id: EntityId) -> Optional[Entity]:
        pass

    @abstractmethod
    def find_by_ids(self, tenant: str, ids: Sequence[EntityId]) -> Sequence[Entity]:
        """
        Retrieve multiple domain objects by their IDs in a single batch operation.

        Args:
            tenant: The tenant identifier
            ids: List of domain IDs to retrieve

        Returns:
            List of domain objects that match the provided IDs
        """
        pass

    @abstractmethod
    def all(self, tenant: str) -> List[Entity]:
        """
        Retrieve all entities for a given tenant.
        """
        pass

    @abstractmethod
    def delete(self, tenant: str, entity_id: EntityId) -> None:
        pass
