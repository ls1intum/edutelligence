from typing import Dict, List, Optional, TypedDict

class Message(TypedDict):
    type: str
    name: str
    direction: str  # 'target' or 'source'

class EndpointData(TypedDict):
    element: str
    multiplicity: Optional[str]
    role: Optional[str]
    direction: Optional[str]

class Relationship(TypedDict):
    id: str
    type: str
    name: str
    owner: Optional[str]
    source: EndpointData
    target: EndpointData
    path: List[Dict[str, float]]
    bounds: Dict[str, float]
    isManuallyLayouted: Optional[bool]
    stroke_dasharray: Optional[str]
    marker_start: Optional[str]
    marker_end: Optional[str]
    messages: Optional[List[Message]]
    _source_point: Optional[Dict[str, float]]
    _target_point: Optional[Dict[str, float]]