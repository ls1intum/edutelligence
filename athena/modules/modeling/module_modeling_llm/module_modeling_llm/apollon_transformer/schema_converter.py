"""
Schema Converter for Apollon UML Diagrams

This module provides conversion between different versions of Apollon schema formats.
Currently supports conversion from v4.0.0 to v3.0.0 format for backward compatibility.
"""


class SchemaConverter:
    """Converts between different Apollon schema versions"""

    @staticmethod
    def is_v2_schema(data: dict) -> bool:
        """
        Check if the data is in v2.0.0 schema format.
        
        :param data: The schema data to check
        :return: True if v2 schema, False otherwise
        """
        return data.get("version") == "2.0.0"

    @staticmethod
    def is_v3_schema(data: dict) -> bool:
        """
        Check if the data is in v3.0.0 schema format.
        
        :param data: The schema data to check
        :return: True if v3 schema, False otherwise
        """
        return "model" in data

    @staticmethod
    def is_v4_schema(data: dict) -> bool:
        """
        Check if the data is in v4.0.0 schema format.
        
        :param data: The schema data to check
        :return: True if v4 schema, False otherwise
        """
        return "nodes" in data and "edges" in data

    @staticmethod
    def _convert_handle_to_direction(handle: str) -> str:
        """
        Convert v4 handle position to v3 direction format.
        
        :param handle: Handle position from v4 schema (e.g., "left", "right-top")
        :return: Direction string for v3 schema (e.g., "Left", "RightTop")
        """
        if not handle:
            return "Right"  # Default direction
        
        # Convert hyphenated lowercase to PascalCase
        parts = handle.split("-")
        return "".join(part.capitalize() for part in parts)

    @staticmethod
    def convert_v2_to_v3(v2_data: dict) -> dict:
        """
        Convert v2.0.0 schema to v3.0.0 schema format.
        Changes 'elements' and 'relationships' from lists to dicts.
        
        :param v2_data: Schema data in v2.0.0 format
        :return: Schema data in v3.0.0 format
        """
        v3_data = v2_data.copy()
        v3_data["version"] = "3.0.0"

        v3_data["elements"] = {
            element["id"]: element for element in v2_data.get("elements", [])
        }

        v3_data["relationships"] = {
            rel["id"]: rel for rel in v2_data.get("relationships", [])
        }

        v3_data["interactive"] = {
            "elements": {},
            "relationships": {}
        }

        return v3_data

    @staticmethod
    def _capitalize_type(type_name: str) -> str:
        """
        Capitalize the first letter of a type name.
        
        :param type_name: Type name from v4 schema (e.g., "class")
        :return: Capitalized type name for v3 schema (e.g., "Class")
        """
        if not type_name:
            return type_name
        return type_name[0].upper() + type_name[1:]

    @staticmethod
    def convert_v4_to_v3(v4_data: dict) -> dict:
        """
        Convert v4.0.0 schema to v3.0.0 schema format.
        
        :param v4_data: Schema data in v4.0.0 format
        :return: Schema data in v3.0.0 format
        """
        v3_data = {
            "version": "3.0.0",
            "type": v4_data.get("type", "ClassDiagram"),
            "elements": {},
            "relationships": {}
        }

        # Convert nodes to elements
        if "nodes" in v4_data:
            for node in v4_data["nodes"]:
                element_id = node["id"]
                node_data = node.get("data", {})
                
                # Base element structure
                element = {
                    "id": element_id,
                    "name": node_data.get("name", ""),
                    "type": SchemaConverter._capitalize_type(node.get("type", "")),
                    "owner": node_data.get("owner"),
                    "bounds": {
                        "x": node.get("position", {}).get("x", 0),
                        "y": node.get("position", {}).get("y", 0),
                        "width": node_data.get("width", 200),
                        "height": node_data.get("height", 100)
                    }
                }

                # Handle attributes (convert from embedded objects to ID references)
                if "attributes" in node_data and node_data["attributes"]:
                    attribute_ids: list[str] = []
                    for attr in node_data["attributes"]:
                        attr_id = attr.get("id", f"{element_id}_attr_{len(attribute_ids)}")
                        attribute_ids.append(attr_id)
                        
                        # Create separate attribute element
                        v3_data["elements"][attr_id] = {
                            "id": attr_id,
                            "name": attr.get("name", ""),
                            "type": "ClassAttribute",
                            "owner": element_id,
                            "bounds": {"x": 0, "y": 0, "width": 0, "height": 0}
                        }
                    
                    element["attributes"] = attribute_ids

                # Handle methods (convert from embedded objects to ID references)
                if "methods" in node_data and node_data["methods"]:
                    method_ids: list[str] = []
                    for method in node_data["methods"]:
                        method_id = method.get("id", f"{element_id}_method_{len(method_ids)}")
                        method_ids.append(method_id)
                        
                        # Create separate method element
                        v3_data["elements"][method_id] = {
                            "id": method_id,
                            "name": method.get("name", ""),
                            "type": "ClassMethod",
                            "owner": element_id,
                            "bounds": {"x": 0, "y": 0, "width": 0, "height": 0}
                        }
                    
                    element["methods"] = method_ids

                # Copy other data fields
                for key, value in node_data.items():
                    if key not in ["name", "attributes", "methods", "width", "height"]:
                        element[key] = value

                v3_data["elements"][element_id] = element

        # Convert edges to relationships
        if "edges" in v4_data:
            for edge in v4_data["edges"]:
                relationship_id = edge["id"]
                edge_data = edge.get("data", {})
                
                relationship = {
                    "id": relationship_id,
                    "name": edge_data.get("name", ""),
                    "type": SchemaConverter._capitalize_type(edge.get("type", "")),
                    "source": {
                        "element": edge["source"],
                        "direction": SchemaConverter._convert_handle_to_direction(
                            edge.get("sourceHandle", "right")
                        )
                    },
                    "target": {
                        "element": edge["target"],
                        "direction": SchemaConverter._convert_handle_to_direction(
                            edge.get("targetHandle", "left")
                        )
                    }
                }

                # Copy other data fields
                for key, value in edge_data.items():
                    if key not in ["name"]:
                        relationship[key] = value

                v3_data["relationships"][relationship_id] = relationship

        return v3_data

    @staticmethod
    def normalize_to_v3(data: dict) -> dict:
        """
        Normalize schema data to v3.0.0 format, regardless of input version.
        
        :param data: Schema data in any supported format
        :return: Schema data in v3.0.0 format
        """
        # If it's v2, convert it first
        if SchemaConverter.is_v2_schema(data):
            return SchemaConverter.convert_v2_to_v3(data)
        
        # If it's already v3 with nested model, extract it
        if SchemaConverter.is_v3_schema(data):
            return data["model"]
        
        # If it's v4, convert it
        if SchemaConverter.is_v4_schema(data):
            return SchemaConverter.convert_v4_to_v3(data)
        
        # Assume it's already normalized v3 (has elements/relationships at top level)
        return data
