from fastapi import APIRouter, Depends, HTTPException, Response, status
from memiris import MemoryWithRelationsDTO
from memiris.api.memory_dto import MemoryDTO

from iris.common.memiris_setup import MemirisWrapper, get_tenant_for_user
from iris.dependencies import TokenValidator
from iris.vector_database.database import VectorDatabase

router = APIRouter(prefix="/api/v1/memiris", tags=["memiris"])


@router.get(
    "/user/{user_id}",
    dependencies=[Depends(TokenValidator())],
    response_model=list[MemoryDTO],
)
def list_memories(user_id: int) -> list[MemoryDTO]:
    """
    List all Memiris memories for a user.

    Resolves the tenant for the given user and returns all memories owned by
    that tenant. If the vector database client is not initialized, returns an
    empty list.

    Args:
        user_id: The user identifier used to derive the tenant.

    Returns:
        list[Memory]: List of memories for the resolved tenant.
    """
    if not VectorDatabase.static_client_instance:
        return []
    tenant = get_tenant_for_user(user_id)
    memories = MemirisWrapper(
        VectorDatabase.static_client_instance, tenant
    ).memory_service.get_all_memories(tenant)
    return [MemoryDTO.from_memory(memory) for memory in memories]


@router.delete(
    "/user/{user_id}/{memory_id}",
    dependencies=[Depends(TokenValidator())],
)
def delete_memory(user_id: int, memory_id: str) -> Response:
    """
    Delete a specific Memiris memory for a user.

    Resolves the tenant for the given user, deletes the memory by its
    identifier, and returns 204 No Content. If the vector database client is
    not initialized, it still returns 204 No Content.

    Args:
        user_id: The user identifier used to derive the tenant.
        memory_id: The memory identifier to delete.

    Returns:
        Response: Empty response with HTTP 204 No Content.
    """
    if not VectorDatabase.static_client_instance:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    tenant = get_tenant_for_user(user_id)
    MemirisWrapper(
        VectorDatabase.static_client_instance, tenant
    ).memory_service.delete_memory(tenant, memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/user/{user_id}/{memory_id}",
    dependencies=[Depends(TokenValidator())],
    response_model=MemoryWithRelationsDTO,
)
def get_memory_with_relations(user_id: int, memory_id: str) -> MemoryWithRelationsDTO:
    """
    Load a memory by its ID and return it with learnings and connections fully fetched.
    """
    if not VectorDatabase.static_client_instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    tenant = get_tenant_for_user(user_id)
    wrapper = MemirisWrapper(VectorDatabase.static_client_instance, tenant)
    result = wrapper.get_memory_with_relations(memory_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return result
