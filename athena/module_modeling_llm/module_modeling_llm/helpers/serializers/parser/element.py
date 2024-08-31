from typing import Dict, Any, List, Optional

class Element:
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
        print(element_dict)
        self.attributes = [element_dict[ref].get("name", "") for ref in self.attribute_refs if ref in element_dict]
        self.methods = [element_dict[ref].get('name', '') for ref in self.method_refs if ref in element_dict]

        for ref_list, target_list in [(self.attribute_refs, self.attributes), (self.method_refs, self.methods)]:
            target_list.extend(
                element_dict.get(ref, {}).get("name", "") for ref in ref_list if ref in element_dict
            )

    def to_apollon(self) -> str:
        parts = [f"[{self.type}] {self.name}"]

        if self.attributes or self.methods:
            details = []
            if self.attributes:
                details.append(f"   attributes:")
                details.extend(f"       {attr}" for attr in self.attributes)
            if self.methods:
                details.append(f"   methods:")
                details.extend(f"       {method}" for method in self.methods)
            parts.append("{\n" + "\n".join(details) + "\n}")

        return " ".join(parts)
    
    def __getitem__(self, key):
        return self.__dict__[key]