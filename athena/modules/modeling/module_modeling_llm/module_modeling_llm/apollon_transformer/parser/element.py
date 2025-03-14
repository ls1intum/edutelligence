# apollon_transformer/parser/element.py

from typing import Dict, Any, List, Optional, Tuple
from string import ascii_uppercase

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
        self.attribute_id_mapping: Dict[str, str] = {}
        self.method_id_mapping: Dict[str, str] = {}
        if element_dict is not None:
            self.resolve_references(element_dict)

    def resolve_references(self, element_dict: Dict[str, Any]):
        """
        Resolve attribute and method references using the provided element dictionary.
        Ensures uniqueness among attribute and method names within the class.
        """
        # Resolve attributes
        self.attributes, self.attribute_id_mapping = self._resolve_uniqueness(
            self.attribute_refs, element_dict)

        # Resolve methods
        self.methods, self.method_id_mapping = self._resolve_uniqueness(
            self.method_refs, element_dict)

    def _resolve_uniqueness(
        self, refs: List[str], element_dict: Dict[str, Any]
    ) -> Tuple[List[str], Dict[str, str]]:
        name_counts: Dict[str, int] = {}
        unique_full_names: List[str] = []
        id_mapping: Dict[str, str] = {}
        for ref in refs:
            if ref in element_dict:
                full_name = element_dict[ref].get("name", "")
                simplified_name = self.extract_name(full_name)
                count = name_counts.get(simplified_name, 0)
                if count > 0:
                    suffix = f"#{ascii_uppercase[count - 1]}"
                    simplified_name_with_suffix = f"{simplified_name}{suffix}"
                else:
                    simplified_name_with_suffix = simplified_name
                name_counts[simplified_name] = count + 1
                unique_full_names.append(full_name)
                id_mapping[simplified_name_with_suffix] = ref
        return unique_full_names, id_mapping

    @staticmethod
    def extract_name(full_name: str) -> str:
        """
        Extracts the simplified name from the full attribute or method name.
        Removes visibility symbols, type annotations, and parameters.
        """
        # Remove visibility symbols and leading/trailing spaces
        name = full_name.lstrip('+-#~ ').strip()
        # For attributes, split on ':'
        if ':' in name:
            name = name.split(':')[0].strip()
        # For methods, split on '('
        elif '(' in name:
            name = name.split('(')[0].strip()
        return name


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
