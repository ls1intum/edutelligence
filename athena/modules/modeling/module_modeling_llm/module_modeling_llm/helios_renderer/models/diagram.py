from typing import Dict, Any, TypedDict
from .element import Element
from .relationship import Relationship

class UMLDiagram(TypedDict):
    id: str
    title: str
    elements: Dict[str, Element]
    relationships: Dict[str, Relationship]
    version: str
    type: str
    size: Dict[str, int]
    interactive: Dict[str, Any]
    assessments: Dict[str, Any]
    lastUpdate: str
