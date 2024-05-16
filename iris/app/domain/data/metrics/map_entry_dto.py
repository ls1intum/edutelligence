# app/domain/data/metrics/map_entry_dto.py

from pydantic import BaseModel


class MapEntryDTO(BaseModel):
    key: int
    value: int
