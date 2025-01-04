from typing import TypedDict, Optional, Dict

class ElementConfigEntry(TypedDict):
    shape: str
    class_name: str
    text_class: str

class RelationshipConfigEntry(TypedDict):
    marker_end: Optional[str]
    stroke_dasharray: Optional[str]

class MarkerConfigEntry(TypedDict):
    path: str
    viewBox: str
    refX: str
    refY: str
    fill: str

ElementConfig = Dict[str, ElementConfigEntry]
RelationshipConfig = Dict[str, RelationshipConfigEntry]
MarkerConfig = Dict[str, MarkerConfigEntry]

class AllConfigs(TypedDict):
    elements: ElementConfig
    relationships: RelationshipConfig
    markers: MarkerConfig