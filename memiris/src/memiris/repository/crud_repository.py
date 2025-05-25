from abc import ABC, abstractmethod
from typing import List


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
    def find(self, tenant: str, entity_id: EntityId) -> Entity:
        pass

    @abstractmethod
    def all(self, tenant: str) -> List[Entity]:
        """
        Retrieve all entities for a given tenant.
        """
        return []

    @abstractmethod
    def delete(self, tenant: str, entity_id: EntityId) -> None:
        pass
