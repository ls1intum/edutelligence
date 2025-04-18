from typing import Dict, List, Optional, TypedDict, Any

class Element(TypedDict):
    id: str
    type: str
    name: str
    owner: Optional[str]
    bounds: Dict[str, float]
    attributes: Optional[List[str]]
    methods: Optional[List[str]]
    properties: Optional[Dict[str, Any]]
