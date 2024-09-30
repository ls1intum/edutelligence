from typing import Dict, Any, List, Optional

class Element:
    """
    Represents an element in a UML diagram.

    This class encapsulates the properties and behavior of a UML element,
    including its attributes and methods.
    """

    def __init__(self, data: Dict[str, Any], element_dict: Optional[Dict[str, Any]] = None):
        self.id: str = data.get('id', '')
        self.type: str = data.get('type', '')
        self.name: str = data.get('name', '')
        self.owner: str = data.get('owner', '')
        self.attribute_refs: List[str] = data.get('attributes', [])
        self.method_refs: List[str] = data.get('methods', [])
        self.attributes: List[str] = []
        self.methods: List[str] = []
        if element_dict is not None:
            self.resolve_references(element_dict)

    def resolve_references(self, element_dict: Dict[str, Any]):
        """
        Resolve attribute and method references using the provided element dictionary. The json data contains only references to other elements that represent attributes and methods. This method resolves these references to the actual names of the attributes and methods by looking up the corresponding elements via their IDs in the provided element dictionary.
        """
        self.attributes = [element_dict[ref].get("name", "") for ref in self.attribute_refs if ref in element_dict]
        self.methods = [element_dict[ref].get('name', '') for ref in self.method_refs if ref in element_dict]

    def to_apollon(self) -> str:
        parts = [f"[{self.type}] {self.name}"]

        if self.attributes or self.methods:
            details = []
            if self.attributes:
                details.append("   attributes:")
                details.extend(f"       {attr}" for attr in self.attributes)
            if self.methods:
                details.append("   methods:")
                details.extend(f"       {method}" for method in self.methods)
            parts.append("{\n" + "\n".join(details) + "\n}")

        return " ".join(parts)
    
    def __getitem__(self, key):
        return self.__dict__[key]