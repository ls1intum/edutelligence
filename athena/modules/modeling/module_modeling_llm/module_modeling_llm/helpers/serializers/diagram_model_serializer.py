from typing import Optional
from module_modeling_llm.helpers.serializers.parser.uml_parser import UMLParser


class DiagramModelSerializer:

    @staticmethod
    def serialize_model(model: dict) -> tuple[Optional[str], dict[str, str]]:
        """
        Serialize a given Apollon diagram model to a string representation.
        This method converts the UML diagram model into a format similar to mermaid syntax, called "apollon".
    
        :param model: The Apollon diagram model to serialize.
        :return: A tuple containing the serialized model as a string and a dictionary mapping element and relation names
                 to their corresponding IDs.
        """
        parser = UMLParser(model)
    
        # Convert the UML diagram to the apollon representation
        apollon_representation = parser.to_apollon()
    
        # Extract elements and relations with their corresponding IDs and names
        names = {
            **{element['name']: element['id'] for element in parser.get_elements()},
            **{relation['name']: relation['id'] for relation in parser.get_relations()}
        }
    
        return apollon_representation, names
    