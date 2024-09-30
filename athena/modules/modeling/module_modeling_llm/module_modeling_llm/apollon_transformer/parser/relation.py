from typing import Dict, Any, List, Optional

class Relation:
    """
    Represents a relationship between elements in a UML diagram.

    This class encapsulates the properties and behavior of a UML relationship,
    including its type, source and target elements, and associated messages.
    """
    def __init__(self, data: Dict[str, Any], element_dict: Optional[Dict[str, Any]], index: int):
        self.id: str = data.get('id', '')
        self.type: str = data.get('type', '')
        # Check if flowType exists, if so use that as the type
        self.type = data.get('flowType', self.type)
        self.label: str = data.get('name', '')
        self.source: Dict[str, Any] = data.get('source', {})
        self.target: Dict[str, Any] = data.get('target', {})
        self.messages: List[Dict[str, str]] = data.get('message', [])
        self.name = f"R{index}"
        if element_dict is not None:
            self.resolve_references(element_dict)

    def resolve_references(self, element_dict: Dict[str, Any]):
        """
        Resolve the source and target element references using the provided element dictionary. The json data contains only references to other elements that represent the source and target elements. This method resolves these references to the actual names of the elements by looking up the corresponding elements via their IDs in the provided element dictionary.
        """
        if self.source['element'] in element_dict:
            self.source['element'] = element_dict[self.source['element']].get("name", "")
        if self.target['element'] in element_dict:
            self.target['element'] = element_dict[self.target['element']].get("name", "")

    def to_apollon(self) -> str:
        parts = [f"{self.name}: {self.source['element']} {get_relation_arrow(self.type)} {self.target['element']}"]

        if self.label:
            parts[0] += f": {self.label}"

        details = []
        for end in ['source', 'target']:
            end_data = getattr(self, end)
            if 'role' in end_data or 'multiplicity' in end_data:
                end_details = [f"    {end_data['element']}: {{"]
                if 'role' in end_data:
                    end_details.append(f"        role: {end_data['role']}")
                if 'multiplicity' in end_data:
                    end_details.append(f"        multiplicity: {end_data['multiplicity']}")
                end_details.append("    }")
                details.extend(end_details)

        if self.messages:
            details.append("    messages: [")
            for message in self.messages:
                to_element = self.target['element'] if message['direction'] == 'target' else self.source['element']
                details.append(f"        {{ name: {message['name']}, to_direction: {to_element} }}")
            details.append("    ]")

        if details:
            parts.append("{\n" + "\n".join(details) + "\n}")

        return " ".join(parts)
    
    def __getitem__(self, key):
        return self.__dict__[key]
    
def get_relation_arrow(relation_type: str) -> str:
    """
    Returns the correct arrow based on the relation type or flow type using string containment.

    Parameters:
    relation_type (str): The type of the relation (e.g., "ClassAggregation", "BPMNFlow_sequence").

    Returns:
    str: The arrow representation for the given relation type in Mermaid syntax.
    """
    arrow_map = {
        # Keys sorted manually by length in descending order to ensure correct matching when using endswith, e.g., when we have dataassociation, dataassociation should be checked before association
        "interfacerequired": "--c",
        "interfaceprovided": "--",
        "dataassociation": "-->",
        "generalization": "<|--",
        "unidirectional": "-->",
        "bidirectional": "<-->",
        "association": "-->",
        "inheritance": "<|--",
        "composition": "*--",
        "aggregation": "o--",
        "realization": "..|>",
        "dependency": "..>",
        "sequence": "-->",
        "message": "-->",
        "include": "..>",
        "message": "-->",
        "extend": "-->",
        "flow": "-->",
        "link": "-->",
        "arc": "-->",
    }

    relation_type = relation_type.replace(" ", "").lower()

    for key, value in arrow_map.items():
        if relation_type.endswith(key):
            return f"({relation_type}) {value}"

    return f"-- {relation_type} --"