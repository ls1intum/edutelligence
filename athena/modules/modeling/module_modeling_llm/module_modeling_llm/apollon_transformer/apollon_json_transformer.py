import json

from module_modeling_llm.apollon_transformer.parser.uml_parser import UMLParser
from module_modeling_llm.apollon_transformer.schema_converter import SchemaConverter


class ApollonJSONTransformer:

    @staticmethod
    def transform_json(model: str) -> tuple[str, dict[str, str], str, dict[str, str]]:
        """
        Serialize a given Apollon diagram model to a string representation.
        This method converts the UML diagram model into a format similar to mermaid syntax, called "apollon".
        Supports v2.0.0, v3.0.0, and Apollon v4 (nodes/edges) schema formats for backward compatibility.
    
        :param model: The Apollon diagram model to serialize.
        :return: A tuple containing the serialized model as a string and a dictionary mapping element and relation names
                 to their corresponding IDs.
        """

        model_dict = json.loads(model)

        # Normalize to v3.0.0 format for input version (v2, v3,v4)
        model_dict = SchemaConverter.normalize_to_v3(model_dict)

        parser = UMLParser(model_dict)

        diagram_type = model_dict.get("type", "unknown")
    
        # Convert the UML diagram to the apollon representation
        apollon_representation = parser.to_apollon()
    
        # Get the mapping of element, method, and attribute names to their corresponding IDs
        # This is used to resolve references to as the apollon representation only contains names and not IDs
        names = parser.get_element_id_mapping()

        id_type_mapping = parser.get_id_to_type_mapping()

        return apollon_representation, names, diagram_type, id_type_mapping
