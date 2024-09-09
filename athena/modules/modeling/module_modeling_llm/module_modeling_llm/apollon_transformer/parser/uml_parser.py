from typing import Dict, Any, List
from string import ascii_uppercase

from module_modeling_llm.apollon_transformer.parser.element import Element
from module_modeling_llm.apollon_transformer.parser.relation import Relation


class UMLParser:
    def __init__(self, json_data: Dict[str, Any]):
        self.data = json_data
        self.title = self.data['type']
        self.elements: List[Element] = []
        self.relations: List[Relation] = []
        self.owners: Dict[str, List[str]] = {}
        self._parse()

    def _parse(self):
        name_counts = {}
        referenced_ids : List[str] = []
        name_suffix_counters = {}

        # Get all referenced attributes and methods
        for element_data in self.data['elements'].values():
            referenced_ids.extend(element_data.get('attributes', []))
            referenced_ids.extend(element_data.get('methods', []))

        # Count occurrences of each name
        for element_data in self.data['elements'].values():
            name = element_data.get('name')
            name_counts[name] = name_counts.get(name, 0) + 1
            name_suffix_counters[name] = 0

        # Filter elements and ensure unique names for duplicates
        # This filters out all Elements that are referenced by any other Element, as they are attributes or methods
        for element_data in self.data['elements'].values():
            if element_data.get('id') not in referenced_ids:
                name = element_data.get('name')
                if name_counts[name] > 1:
                    suffix_index = name_suffix_counters[name]
                    element_data['name'] = f"{name}{ascii_uppercase[suffix_index]}"
                    name_suffix_counters[name] += 1

                element = Element(element_data, self.data['elements'])
                self.elements.append(element)

        # Parse relations
        for index, relation_data in enumerate(self.data['relationships'].values()):
            relation = Relation(relation_data, self.data['elements'], index + 1)
            self.relations.append(relation)

        # Get all owners and their elements
        for element in self.elements:
            ownerId = element.owner
            if ownerId:
                owner_element = next((el for el in self.elements if el.id == ownerId), None)
                if owner_element:
                    ownerName = owner_element.name
                    if ownerName not in self.owners:
                        self.owners[ownerName] = []
                    self.owners[ownerName].append(element.name)

    def to_apollon(self) -> str:
        lines = [f"UML Diagram Type: {self.title}", ""]

        if self.elements:
            lines.append("@Elements:\n")
            lines.extend(element.to_apollon() for element in self.elements)

        if self.relations:
            lines.append("\n\n@Relations:\n")
            lines.extend(relation.to_apollon() for relation in self.relations)

        if self.owners:
            lines.append("\n\n@Owners:\n")
            for owner, children in self.owners.items():
                lines.append(f"{owner}: {', '.join(children)}")

        return "\n".join(lines)

    def get_elements(self) -> List[Element]:
        return self.elements

    def get_relations(self) -> List[Relation]:
        return self.relations